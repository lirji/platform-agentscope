import json
import subprocess
import sys
from pathlib import Path

from agentscope_platform.evaluation.models import GovernedToolCase

ROOT = Path(__file__).resolve().parents[1]


def test_contract_snapshots_are_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_contracts.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_evaluation_contracts_are_language_neutral() -> None:
    case_schema = json.loads(
        (ROOT / "contracts" / "evaluation" / "shadow-case.schema.json").read_text(encoding="utf-8")
    )
    report_schema = json.loads(
        (ROOT / "contracts" / "evaluation" / "shadow-report.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert {"id", "goal", "expectedTools", "readOnly"}.issubset(case_schema["required"])
    assert {"suite", "generated_at", "runs_per_case", "gate", "samples"}.issubset(
        report_schema["required"]
    )
    assert "dataset" in report_schema["properties"]

    dataset_schema = json.loads(
        (ROOT / "contracts" / "evaluation" / "evaluation-dataset.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert {"datasetId", "version", "kind", "createdAt", "cases"}.issubset(
        dataset_schema["required"]
    )
    assert dataset_schema["additionalProperties"] is False

    trajectory_schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "agent-trajectory.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert {"traceId", "versions", "steps", "stopReason"}.issubset(trajectory_schema["required"])
    assert {"goal", "finalAnswer", "internalToken", "confirmationGrant"}.isdisjoint(
        trajectory_schema["properties"]
    )


def test_analytics_planner_contract_excludes_trusted_identity_and_db_credentials() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "analytics-sql-plan.schema.json").read_text(
            encoding="utf-8"
        )
    )
    request = schema["$defs"]["request"]
    response = schema["$defs"]["response"]

    assert request["required"] == ["question", "sql"]
    assert request["additionalProperties"] is False
    assert {"tenantId", "userId", "databaseUrl", "credentials"}.isdisjoint(request["properties"])
    assert {"executed", "rejectionReason", "rows"}.issubset(response["required"])


def test_workflow_ai_draft_contract_cannot_carry_decisions_or_trusted_identity() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "workflow-ai-draft.schema.json").read_text(
            encoding="utf-8"
        )
    )
    ticket_properties = set(schema["$defs"]["ticketRequest"]["properties"])
    reply_properties = set(schema["$defs"]["replyRequest"]["properties"])
    forbidden = {
        "tenantId",
        "userId",
        "approved",
        "decision",
        "taskId",
        "instanceId",
        "internalToken",
    }

    assert forbidden.isdisjoint(ticket_properties)
    assert forbidden.isdisjoint(reply_properties)


def test_tool_policy_contract_declares_every_safety_dimension() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "tool-policy.schema.json").read_text(encoding="utf-8")
    )

    assert set(schema["required"]) == {
        "name",
        "readOnly",
        "sideEffect",
        "idempotency",
        "requiresConfirmation",
        "requiredScopes",
        "timeoutSeconds",
        "retryPolicy",
    }
    assert schema["additionalProperties"] is False


def test_tool_confirmation_contract_binds_only_tool_arguments() -> None:
    request = json.loads(
        (ROOT / "contracts" / "boundaries" / "tool-confirmation-request.schema.json").read_text(
            encoding="utf-8"
        )
    )
    reply = json.loads(
        (ROOT / "contracts" / "boundaries" / "tool-confirmation-reply.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"toolName", "arguments"}
    assert {"tenantId", "userId", "internalToken", "idempotencyKey"}.isdisjoint(
        request["properties"]
    )
    assert {"grant", "grantId", "toolName", "argumentsSha256", "expiresAt"} == set(
        reply["required"]
    )


def test_governed_tool_evaluation_contract_is_stub_only_and_identity_free() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "evaluation" / "governed-tool-case.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "id",
        "legacyAction",
        "candidateTool",
        "executionMode",
        "readOnly",
        "confirmed",
        "idempotencyKeyPresent",
        "expectedPolicy",
        "expectedProviderCalls",
        "expectedResult",
    }
    assert schema["properties"]["executionMode"]["const"] == "stub_only"
    forbidden = {"tenantId", "userId", "internalToken", "providerUrl", "credentials"}
    assert forbidden.isdisjoint(schema["properties"])


def test_governed_tool_evaluation_fixture_covers_refund_safety_cases() -> None:
    path = ROOT / "eval" / "baseline" / "governed-tool-cases.jsonl"
    cases = [
        GovernedToolCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) >= 5
    assert len({case.id for case in cases}) == len(cases)
    assert {case.candidate_tool for case in cases} == {"refund_start"}
    assert all(case.execution_mode == "stub_only" for case in cases)
    assert any(not case.confirmed and case.expected_provider_calls == 0 for case in cases)
    assert any(
        not case.idempotency_key_present and case.expected_provider_calls == 0 for case in cases
    )
    assert any(case.expected_result == "WAITING_APPROVAL" for case in cases)
    dedupe = [case for case in cases if case.expected_result == "DEDUPLICATED"]
    assert dedupe and all(case.expected_provider_calls == 2 for case in dedupe)


def test_mcp_binding_contract_and_evaluation_fixture_are_allowlist_only() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "mcp-tool-binding.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "serverId",
        "remoteName",
        "description",
        "metadata",
    }

    path = ROOT / "eval" / "baseline" / "mcp-governed-cases.jsonl"
    cases = [
        GovernedToolCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) >= 5
    assert {case.legacy_action for case in cases} == {"mcp_call"}
    assert all(case.execution_mode == "stub_only" for case in cases)
    assert any(case.read_only and case.expected_policy == "allowed" for case in cases)
    assert any(case.expected_policy == "allowlist_denied" for case in cases)
    assert any(case.expected_policy == "arguments_rejected" for case in cases)
    assert any(
        not case.read_only and case.confirmed and case.expected_provider_calls == 1
        for case in cases
    )


def test_remote_sandbox_contracts_are_identity_free_and_require_isolation() -> None:
    browser = json.loads(
        (ROOT / "contracts" / "boundaries" / "browser-action-request.schema.json").read_text(
            encoding="utf-8"
        )
    )
    code = json.loads(
        (ROOT / "contracts" / "boundaries" / "code-execution-request.schema.json").read_text(
            encoding="utf-8"
        )
    )
    forbidden = {"tenantId", "userId", "internalToken", "credentials"}

    assert forbidden.isdisjoint(browser["properties"])
    assert {"sessionId", "operationId", "action", "arguments", "allowedHosts"}.issubset(
        browser["required"]
    )
    assert forbidden.isdisjoint(code["properties"])
    assert code["properties"]["networkEnabled"]["const"] is False
    assert code["properties"]["workspace"]["const"] == "ephemeral"
    assert {"timeoutMs", "maxOutputChars", "maxMemoryMb", "maxProcesses"}.issubset(code["required"])


def test_downstream_service_token_contract_is_bounded_and_cannot_carry_caller_token() -> None:
    schema = json.loads(
        (
            ROOT / "contracts" / "boundaries" / "downstream-service-token-claims.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "iss",
        "aud",
        "sub",
        "tenant",
        "actor_uid",
        "scopes",
        "token_use",
        "act",
        "jti",
        "iat",
        "exp",
    }
    assert schema["properties"]["token_use"]["const"] == "agent_downstream"
    assert schema["properties"]["scopes"]["maxItems"] == 1
    assert {"internalToken", "confirmationGrant", "idempotencyKey"}.isdisjoint(schema["properties"])


def test_async_worker_token_contract_binds_owner_worker_task_and_operation() -> None:
    schema = json.loads(
        (
            ROOT / "contracts" / "boundaries" / "async-task-worker-token-claims.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert schema["additionalProperties"] is False
    assert {"tenant", "actor_uid", "worker_id", "task_id", "act"}.issubset(schema["required"])
    assert schema["properties"]["token_use"]["const"] == "async_task_worker"
    assert set(schema["properties"]["act"]["enum"]) == {"lease", "status", "event"}
    assert schema["properties"]["scopes"]["maxItems"] == 1
    assert {"internalToken", "confirmationGrant"}.isdisjoint(schema["properties"])


def test_remote_sandbox_evaluation_fixture_covers_safety_and_parity() -> None:
    path = ROOT / "eval" / "baseline" / "sandbox-governed-cases.jsonl"
    cases = [
        GovernedToolCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) >= 7
    assert {case.legacy_action for case in cases} >= {
        "browser_open",
        "browser_click",
        "browser_screenshot",
        "code_exec",
    }
    assert all(case.execution_mode == "stub_only" for case in cases)
    assert any(case.expected_policy == "host_denied" for case in cases)
    assert any(case.expected_result == "TIMED_OUT" for case in cases)
    assert all(
        case.expected_provider_calls == 0 for case in cases if case.expected_result == "DENIED"
    )


def test_conversation_generation_contract_is_stateless_and_identity_free() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "conversation-generation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    request = schema["$defs"]["request"]
    response = schema["$defs"]["response"]
    forbidden = {
        "tenantId",
        "tenant_id",
        "userId",
        "user_id",
        "chatId",
        "chat_id",
        "memory",
        "profile",
        "cache",
        "internalToken",
        "internal_token",
    }

    assert request["additionalProperties"] is False
    assert request["required"] == ["schema_version", "message", "context", "style", "history"]
    assert forbidden.isdisjoint(request["properties"])
    assert schema["$defs"]["historyMessage"]["properties"]["role"]["enum"] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert response["required"] == ["reply"]


def test_conversation_candidate_stream_contract_has_terminal_events() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "boundaries" / "conversation-stream-event.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["sequence", "type", "data"]
    assert schema["properties"]["type"]["enum"] == ["token", "done", "error"]


def test_readonly_evaluation_fixture_is_safe_and_well_formed() -> None:
    path = ROOT / "eval" / "baseline" / "readonly-cases.jsonl"
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert len(cases) >= 4
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["goal"].strip() for case in cases)
    assert all(case["readOnly"] is True for case in cases)
    assert all(case["expectedTools"] for case in cases)
    assert all("refund_start" not in case["expectedTools"] for case in cases)


def test_dag_dual_run_fixture_is_safe_and_well_formed() -> None:
    path = ROOT / "eval" / "baseline" / "dag-cases.jsonl"
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert len(cases) >= 3
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["readOnly"] is True for case in cases)
    assert all(case["request"]["goal"].strip() for case in cases)
    assert all(case["request"]["tasks"] for case in cases)
    assert all(case["expectedLevels"] for case in cases)
    for case in cases:
        task_ids = {task["id"] for task in case["request"]["tasks"]}
        flattened_levels = {task_id for level in case["expectedLevels"] for task_id in level}
        assert flattened_levels == task_ids


def test_planner_dual_run_fixture_is_safe_and_well_formed() -> None:
    path = ROOT / "eval" / "baseline" / "planner-cases.jsonl"
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert len(cases) >= 2
    assert {case["endpoint"] for case in cases} == {
        "/agent/dag/plan-run",
        "/agent/analyst/run",
    }
    assert all(case["readOnly"] is True for case in cases)
    assert all(case["request"]["goal"].strip() for case in cases)
    analyst = next(case for case in cases if case["endpoint"] == "/agent/analyst/run")
    assert analyst["requiredDescriptionTerms"] == [
        "schema_explore",
        "analytics_sql",
    ]


def test_critic_dual_run_fixture_requires_review_evidence() -> None:
    path = ROOT / "eval" / "baseline" / "critic-cases.jsonl"
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert cases
    assert all(case["readOnly"] is True for case in cases)
    assert all(case["requireCritique"] is True for case in cases)
    assert all(case["expectedLevels"] for case in cases)


def test_process_fixture_forbids_every_workflow_write_tool() -> None:
    path = ROOT / "eval" / "baseline" / "process-readonly-cases.jsonl"
    cases = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert len(cases) >= 3
    assert all(case["endpoint"] == "/agent/process/run" for case in cases)
    assert all(case["readOnly"] is True for case in cases)
    assert all(
        {"refund_start", "workflow_complete"}.issubset(case["forbiddenTools"]) for case in cases
    )
