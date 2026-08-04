from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import jwt

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext
from agentscope_platform.domain.security import AsyncTaskWorkerTokenClaims

AsyncTaskWorkerAction = Literal["lease", "status", "event"]


class AsyncTaskWorkerTokenError(RuntimeError):
    """A request-scoped async worker credential cannot be issued safely."""


class AsyncTaskWorkerTokenIssuer:
    """Mint a short-lived credential bound to one worker operation and task."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.async_task_worker_jwt_secret.get_secret_value()
        self._issuer = settings.async_task_worker_jwt_issuer
        self._audience = settings.async_task_worker_jwt_audience
        self._worker_id = settings.async_task_worker_id.strip()
        self._key_id = settings.async_task_worker_jwt_key_id
        self._ttl = timedelta(seconds=settings.async_task_worker_jwt_ttl_seconds)

    def issue(
        self,
        context: RunContext,
        *,
        worker_id: str,
        action: AsyncTaskWorkerAction,
        task_id: str,
    ) -> str:
        if len(self._secret.encode("utf-8")) < 32:
            raise AsyncTaskWorkerTokenError("async worker signing key is unavailable")
        owner_prefix = f"{self._worker_id}."
        if (
            not self._worker_id
            or len(worker_id) > 128
            or (worker_id != self._worker_id and not worker_id.startswith(owner_prefix))
        ):
            raise AsyncTaskWorkerTokenError("async worker identity does not match service identity")
        if action not in {"lease", "status", "event"}:
            raise AsyncTaskWorkerTokenError("async worker action is invalid")
        if not task_id or len(task_id) > 256:
            raise AsyncTaskWorkerTokenError("async worker task id is invalid")

        now = datetime.now(UTC)
        try:
            claims = AsyncTaskWorkerTokenClaims(
                iss=self._issuer,
                aud=self._audience,
                sub=self._worker_id,
                tenant=context.identity.tenant_id,
                actor_uid=context.identity.user_id,
                worker_id=worker_id,
                scopes=("async.task.worker",),
                token_use="async_task_worker",
                act=action,
                task_id=task_id,
                jti=str(uuid4()),
                iat=int(now.timestamp()),
                exp=int((now + self._ttl).timestamp()),
            )
            return jwt.encode(
                claims.model_dump(mode="json"),
                self._secret,
                algorithm="HS256",
                headers={"kid": self._key_id, "typ": "JWT"},
            )
        except Exception as exc:
            raise AsyncTaskWorkerTokenError("async worker token signing failed") from exc
