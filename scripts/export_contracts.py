#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any

from agentscope_platform.api.app import create_app
from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import AgentRunReply, AgentRunRequest, AgentStep
from agentscope_platform.domain.async_task import (
    AgentAsyncTask,
    AgentTaskProgress,
    CentralAsyncTaskEvent,
)
from agentscope_platform.domain.dag import (
    AgentDagRunReply,
    AgentDagRunRequest,
    AgentDagTask,
    AgentPlanRunRequest,
)
from agentscope_platform.domain.sibling import (
    ChainRunReply,
    ChainRunRequest,
    ReflexionReply,
    ReflexionRequest,
    VoteReply,
    VoteRequest,
)
from agentscope_platform.evaluation.models import ShadowCase, ShadowReport

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def artifacts() -> dict[Path, dict[str, Any]]:
    settings = Settings(_env_file=None, internal_auth_required=False)  # type: ignore[call-arg]
    app = create_app(settings)
    return {
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
        CONTRACTS / "openapi.json": app.openapi(),
    }


def render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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

    if stale:
        print("Stale contract artifacts:")
        for path in stale:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
