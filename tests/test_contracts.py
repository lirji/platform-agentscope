import json
import subprocess
import sys
from pathlib import Path

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
        (ROOT / "contracts" / "evaluation" / "shadow-case.schema.json").read_text(
            encoding="utf-8"
        )
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
    assert {"tenantId", "userId", "databaseUrl", "credentials"}.isdisjoint(
        request["properties"]
    )
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
        (
            ROOT
            / "contracts"
            / "boundaries"
            / "conversation-stream-event.schema.json"
        ).read_text(encoding="utf-8")
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
