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
