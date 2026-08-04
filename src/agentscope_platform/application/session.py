import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agentscope_platform.application.ports import AgentSessionStore, ResumableAgentRunner
from agentscope_platform.application.privacy import redact_pii
from agentscope_platform.domain.agent import AgentStep, RunContext
from agentscope_platform.domain.session import (
    AgentSessionCheckpoint,
    AgentSessionStatus,
    goal_sha256,
)


class AgentSessionNotFoundError(RuntimeError):
    pass


class AgentSessionActiveError(RuntimeError):
    pass


class AgentSessionGoalMismatchError(RuntimeError):
    pass


class AgentSessionResumeConfirmationRequiredError(RuntimeError):
    pass


class AgentSessionConflictError(RuntimeError):
    pass


class AgentSessionService:
    def __init__(
        self,
        runner: ResumableAgentRunner,
        store: AgentSessionStore,
        *,
        ttl_seconds: int = 86_400,
        lease_seconds: int = 180,
        lease_owner_id: str | None = None,
    ) -> None:
        self._runner = runner
        self._store = store
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lease = timedelta(seconds=lease_seconds)
        self._lease_owner_id = lease_owner_id or f"session-worker-{uuid4().hex}"

    async def get(
        self,
        session_id: str,
        context: RunContext,
    ) -> AgentSessionCheckpoint:
        checkpoint = await self._store.get(session_id)
        if checkpoint is None or not self._owned_by(checkpoint, context):
            raise AgentSessionNotFoundError("agent session not found")
        return checkpoint

    async def run(
        self,
        session_id: str,
        goal: str,
        context: RunContext,
    ) -> AgentSessionCheckpoint:
        normalized_goal = goal.strip()
        digest = goal_sha256(normalized_goal)
        checkpoint = await self._store.get(session_id)
        now = datetime.now(UTC)
        if checkpoint is None:
            checkpoint = AgentSessionCheckpoint(
                sessionId=session_id,
                revision=0,
                tenantId=context.identity.tenant_id,
                userId=context.identity.user_id,
                goalSha256=digest,
                status=AgentSessionStatus.RUNNING,
                idempotencyKeySha256=self._idempotency_digest(context),
                leaseOwnerId=self._lease_owner_id,
                leaseExpiresAt=now + self._lease,
                createdAt=now,
                updatedAt=now,
                expiresAt=now + self._ttl,
            )
            if not await self._store.compare_and_set(checkpoint, expected_revision=None):
                raise AgentSessionConflictError("agent session creation raced with another request")
        else:
            self._validate_resume(checkpoint, digest, context, now)
            if checkpoint.status.terminal:
                return checkpoint
            running = checkpoint.model_copy(
                update={
                    "revision": checkpoint.revision + 1,
                    "status": AgentSessionStatus.RUNNING,
                    "lease_owner_id": self._lease_owner_id,
                    "lease_expires_at": now + self._lease,
                    "updated_at": now,
                    "expires_at": now + self._ttl,
                    "error": None,
                }
            )
            if not await self._store.compare_and_set(
                running,
                expected_revision=checkpoint.revision,
            ):
                raise AgentSessionConflictError("agent session was modified concurrently")
            checkpoint = running

        current = checkpoint

        async def persist_progress(
            steps: tuple[AgentStep, ...],
            side_effect_observed: bool,
        ) -> None:
            nonlocal current
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "steps": self._safe_steps(steps),
                    "side_effect_observed": (current.side_effect_observed or side_effect_observed),
                    "updated_at": datetime.now(UTC),
                    "lease_expires_at": datetime.now(UTC) + self._lease,
                }
            )
            if updated.side_effect_observed and updated.idempotency_key_sha256 is None:
                raise AgentSessionResumeConfirmationRequiredError(
                    "side-effect progress requires an idempotency key"
                )
            if not await self._store.compare_and_set(
                updated,
                expected_revision=current.revision,
            ):
                raise AgentSessionConflictError("agent session progress lost its lease")
            current = updated

        execution = await self._runner.run_from_checkpoint(
            normalized_goal,
            current,
            context,
            persist_progress,
        )
        now = datetime.now(UTC)
        succeeded = execution.stop_reason == "DONE"
        completed = current.model_copy(
            update={
                "revision": current.revision + 1,
                "status": (
                    AgentSessionStatus.SUCCEEDED if succeeded else AgentSessionStatus.PAUSED
                ),
                "steps": self._safe_steps(execution.steps),
                "final_answer": self._safe_text(execution.final_answer, 100_000),
                "stop_reason": execution.stop_reason[:128],
                "error": None if succeeded else "agent execution did not complete",
                "lease_owner_id": None,
                "lease_expires_at": None,
                "updated_at": now,
                "expires_at": now + self._ttl,
            }
        )
        if not await self._store.compare_and_set(
            completed,
            expected_revision=current.revision,
        ):
            raise AgentSessionConflictError("agent session completion lost its lease")
        return completed

    def _validate_resume(
        self,
        checkpoint: AgentSessionCheckpoint,
        digest: str,
        context: RunContext,
        now: datetime,
    ) -> None:
        if not self._owned_by(checkpoint, context):
            raise AgentSessionNotFoundError("agent session not found")
        if checkpoint.goal_sha256 != digest:
            raise AgentSessionGoalMismatchError("session goal does not match the original goal")
        if (
            checkpoint.status is AgentSessionStatus.RUNNING
            and checkpoint.lease_expires_at is not None
            and checkpoint.lease_expires_at > now
        ):
            raise AgentSessionActiveError("agent session is already running")
        if checkpoint.side_effect_observed and not checkpoint.status.terminal:
            current_digest = self._idempotency_digest(context)
            fresh_confirmation = any(
                not grant.expired
                and grant.tenant_id == context.identity.tenant_id
                and grant.user_id == context.identity.user_id
                and grant.idempotency_key == context.idempotency_key
                for grant in context.confirmation_grants
            )
            if current_digest != checkpoint.idempotency_key_sha256 or not fresh_confirmation:
                raise AgentSessionResumeConfirmationRequiredError(
                    "side-effect session resume requires the original idempotency key "
                    "and a fresh confirmation"
                )

    @staticmethod
    def _owned_by(checkpoint: AgentSessionCheckpoint, context: RunContext) -> bool:
        return (
            checkpoint.tenant_id == context.identity.tenant_id
            and checkpoint.user_id == context.identity.user_id
        )

    @staticmethod
    def _idempotency_digest(context: RunContext) -> str | None:
        if context.idempotency_key is None:
            return None
        return hashlib.sha256(context.idempotency_key.encode("utf-8")).hexdigest()

    @classmethod
    def _safe_steps(cls, steps: tuple[AgentStep, ...]) -> list[AgentStep]:
        safe: list[AgentStep] = []
        for step in steps[:256]:
            safe.append(
                AgentStep(
                    n=step.n,
                    thought=cls._safe_text(step.thought, 4_000),
                    action=cls._safe_text(step.action, 128),
                    actionInput=cls._safe_text(step.action_input, 16_000),
                    observation=cls._safe_text(step.observation, 32_000),
                )
            )
        return safe

    @staticmethod
    def _safe_text(value: str, limit: int) -> str:
        redacted = redact_pii(value)
        assert isinstance(redacted, str)
        return redacted[:limit]
