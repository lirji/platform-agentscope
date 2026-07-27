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
