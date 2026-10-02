#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import (
    AgentRunReply,
    AgentRunRequest,
    AgentStep,
    AgentTrajectory,
    ExecutionVersions,
)
from agentscope_platform.domain.async_task import (
    AgentAsyncTask,
    AgentTaskProgress,
    CentralAsyncTaskEvent,
    ReadOnlyTaskClaimReply,
    ReadOnlyTaskClaimRequest,
)
from agentscope_platform.domain.confirmation import (
    ToolConfirmationReply,
    ToolConfirmationRequest,
)
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentDagTask,
    AgentPlanRunRequest,
)
from agentscope_platform.domain.interop import capability_registry
from agentscope_platform.domain.mcp import McpToolBinding
from agentscope_platform.domain.metering import (
    BudgetReservationReply,
    BudgetReservationRequest,
    BudgetSettlementRequest,
)
from agentscope_platform.domain.sandbox import (
    BrowserActionReply,
    BrowserActionRequest,
    CodeExecutionReply,
    CodeExecutionRequest,
)
from agentscope_platform.domain.security import (
    AsyncTaskWorkerTokenClaims,
    DownstreamServiceTokenClaims,
)
from agentscope_platform.domain.session import AgentSessionCheckpoint
from agentscope_platform.domain.sibling import (
    ChainRunReply,
    ChainRunRequest,
    ReflexionReply,
    ReflexionRequest,
    VoteReply,
    VoteRequest,
)
from agentscope_platform.domain.tool import ToolMetadata
from agentscope_platform.domain.workflow import RefundReceiptRequest
from agentscope_platform.evaluation.models import (
    EvaluationDataset,
    GovernedToolCase,
    OnlineFeedbackRecord,
    ShadowCase,
    ShadowReport,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
MANIFEST = CONTRACTS / "manifest.json"
MANIFEST_SCHEMA_VERSION = "1"


def artifacts() -> dict[Path, dict[str, Any]]:
    settings = Settings(_env_file=None, internal_auth_required=False)  # type: ignore[call-arg]
    app = create_app(settings)
    additional = {
        "budget-reservation-request": BudgetReservationRequest,
        "budget-reservation-reply": BudgetReservationReply,
        "budget-settlement-request": BudgetSettlementRequest,
        "refund-receipt-request": RefundReceiptRequest,
        "readonly-task-claim-request": ReadOnlyTaskClaimRequest,
        "readonly-task-claim-reply": ReadOnlyTaskClaimReply,
    }
    return {
        **{
            CONTRACTS / "boundaries" / f"{name}.schema.json": model.model_json_schema(by_alias=True)
            for name, model in additional.items()
        },
        CONTRACTS / "legacy" / "agent-run-request.schema.json": AgentRunRequest.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "legacy" / "agent-step.schema.json": AgentStep.model_json_schema(by_alias=True),
        CONTRACTS / "legacy" / "agent-run-reply.schema.json": AgentRunReply.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "legacy" / "agent-dag-task.schema.json": AgentDagTask.model_json_schema(
            by_alias=True
        ),
        CONTRACTS
        / "legacy"
        / "agent-dag-run-request.schema.json": AgentDagRunRequest.model_json_schema(by_alias=True),
        CONTRACTS
        / "legacy"
        / "agent-dag-run-reply.schema.json": AgentDagRunReply.model_json_schema(by_alias=True),
        CONTRACTS
        / "legacy"
        / "agent-plan-run-request.schema.json": AgentPlanRunRequest.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "legacy" / "chain-run-request.schema.json": (
            ChainRunRequest.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "legacy" / "chain-run-reply.schema.json": (
            ChainRunReply.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "legacy" / "vote-request.schema.json": VoteRequest.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "legacy" / "vote-reply.schema.json": VoteReply.model_json_schema(by_alias=True),
        CONTRACTS / "legacy" / "reflexion-request.schema.json": (
            ReflexionRequest.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "legacy" / "reflexion-reply.schema.json": (
            ReflexionReply.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "legacy" / "agent-async-task.schema.json": (
            AgentAsyncTask.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "legacy" / "agent-task-progress.schema.json": (
            AgentTaskProgress.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "legacy" / "async-task-stream-event.schema.json": (
            CentralAsyncTaskEvent.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "evaluation" / "shadow-case.schema.json": ShadowCase.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "evaluation" / "shadow-report.schema.json": ShadowReport.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "evaluation" / "governed-tool-case.schema.json": (
            GovernedToolCase.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "evaluation" / "evaluation-dataset.schema.json": (
            EvaluationDataset.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "evaluation" / "online-feedback.schema.json": (
            OnlineFeedbackRecord.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "agent-execution-versions.schema.json": (
            ExecutionVersions.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "agent-trajectory.schema.json": (
            AgentTrajectory.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "tool-policy.schema.json": ToolMetadata.model_json_schema(
            by_alias=True
        ),
        CONTRACTS / "boundaries" / "tool-confirmation-request.schema.json": (
            ToolConfirmationRequest.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "tool-confirmation-reply.schema.json": (
            ToolConfirmationReply.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "mcp-tool-binding.schema.json": (
            McpToolBinding.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "browser-action-request.schema.json": (
            BrowserActionRequest.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "browser-action-reply.schema.json": (
            BrowserActionReply.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "code-execution-request.schema.json": (
            CodeExecutionRequest.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "code-execution-reply.schema.json": (
            CodeExecutionReply.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "downstream-service-token-claims.schema.json": (
            DownstreamServiceTokenClaims.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "async-task-worker-token-claims.schema.json": (
            AsyncTaskWorkerTokenClaims.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "boundaries" / "agent-session-checkpoint.schema.json": (
            AgentSessionCheckpoint.model_json_schema(by_alias=True)
        ),
        CONTRACTS / "capabilities" / "agent-capabilities.v1.json": (
            capability_registry().model_dump(by_alias=True, mode="json")
        ),
        CONTRACTS / "openapi.json": app.openapi(),
    }


def render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def contract_files() -> list[Path]:
    # Only the JSON payloads are pinned; editing the README next to them must not
    # report a stale contract.
    return sorted(p for p in CONTRACTS.rglob("*.json") if p.is_file() and p != MANIFEST)


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict[str, Any]:
    # Covers hand-written contracts too, so consumers in other languages can pin any
    # contract file, not only the Pydantic-generated ones.
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "files": {p.relative_to(CONTRACTS).as_posix(): digest(p) for p in contract_files()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed contract artifacts differ from generated output.",
    )
    args = parser.parse_args()

    stale: list[Path] = []
    for path, value in artifacts().items():
        expected = render(value)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")

    # The manifest hashes files on disk, so it must be resolved after the generated
    # artifacts have been written; otherwise it would pin the previous revision.
    expected_manifest = render(manifest())
    if args.check:
        if not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8") != expected_manifest:
            stale.append(MANIFEST.relative_to(ROOT))
    else:
        MANIFEST.write_text(expected_manifest, encoding="utf-8")

    if stale:
        print("Stale contract artifacts:")
        for path in stale:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
