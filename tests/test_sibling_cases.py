from pathlib import Path

import pytest

from agentscope_platform.evaluation.shadow import ShadowEvaluationError
from agentscope_platform.evaluation.sibling_cases import load_sibling_cases

ROOT = Path(__file__).resolve().parents[1]


def test_sibling_baseline_is_read_only_and_covers_all_sync_routes() -> None:
    cases = load_sibling_cases(ROOT / "eval" / "baseline" / "sibling-cases.jsonl")

    assert {case.endpoint for case in cases} == {
        "/agent/chain",
        "/agent/vote",
        "/agent/reflexive",
    }
    assert all(case.read_only for case in cases)
    assert all("steps" not in case.request for case in cases)


def test_sibling_case_loader_rejects_caller_defined_chain_steps(
    tmp_path: Path,
) -> None:
    suite = tmp_path / "cases.jsonl"
    suite.write_text(
        '{"id":"unsafe","endpoint":"/agent/chain","request":'
        '{"input":"x","steps":[]},"readOnly":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(ShadowEvaluationError, match="caller-defined steps"):
        load_sibling_cases(suite)
