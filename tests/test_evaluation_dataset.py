import json
from pathlib import Path

import pytest

from agentscope_platform.evaluation.dataset import (
    EvaluationDatasetError,
    build_dataset,
    import_feedback,
    load_dataset,
    replay_reference,
    write_dataset,
)
from agentscope_platform.evaluation.models import ShadowCase
from agentscope_platform.evaluation.shadow import Target, evaluate_shadow, write_report

ROOT = Path(__file__).resolve().parents[1]


def case(*, case_id: str = "c1", forbidden: tuple[str, ...] = ()) -> ShadowCase:
    return ShadowCase.model_validate(
        {
            "id": case_id,
            "goal": "find refund policy",
            "expectedTools": ["rag_search"],
            "forbiddenTools": list(forbidden),
            "readOnly": True,
        }
    )


def test_versioned_dataset_round_trip_and_content_digest(tmp_path: Path) -> None:
    dataset = build_dataset("refund-baseline", "baseline", (case(),))
    output = tmp_path / "dataset.json"
    write_dataset(dataset, output)

    loaded = load_dataset(output)

    assert loaded == dataset
    assert loaded.schema_version == "agent-evaluation-dataset.v1"
    assert loaded.version.startswith("sha256:")
    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["cases"][0]["goal"] = "tampered"
    output.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(EvaluationDatasetError, match="version"):
        load_dataset(output)


def test_adversarial_dataset_requires_explicit_forbidden_behavior() -> None:
    with pytest.raises(ValueError, match="adversarial"):
        build_dataset("unsafe", "adversarial", (case(),))

    dataset = build_dataset(
        "refund-adversarial",
        "adversarial",
        (case(forbidden=("refund_start",)),),
    )
    assert dataset.kind == "adversarial"


def test_committed_adversarial_dataset_has_a_valid_content_version() -> None:
    dataset = load_dataset(ROOT / "eval" / "datasets" / "agent-safety-adversarial.v1.json")

    assert dataset.kind == "adversarial"
    assert len(dataset.cases) >= 2
    assert all(case.forbidden_tools for case in dataset.cases)


def test_feedback_import_is_consent_only_read_only_and_redacts_identity(tmp_path: Path) -> None:
    source = tmp_path / "feedback.jsonl"
    source.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-online-feedback.v1",
                "feedbackId": "fb-101",
                "goal": "联系 alice@example.com 或 13800138000 查询退款政策",
                "rating": "negative",
                "consentForEvaluation": True,
                "readOnly": True,
                "expectedTools": ["rag_search"],
                "forbiddenTools": ["refund_start"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    dataset = import_feedback(source, dataset_id="feedback-2026-08")
    serialized = dataset.model_dump_json(by_alias=True)

    assert dataset.kind == "feedback"
    assert len(dataset.cases) == 1
    assert dataset.cases[0].id.startswith("feedback-")
    assert "alice@example.com" not in serialized
    assert "13800138000" not in serialized
    assert "fb-101" not in serialized


def test_feedback_import_rejects_unconsented_or_write_cases(tmp_path: Path) -> None:
    source = tmp_path / "feedback.jsonl"
    value = {
        "schemaVersion": "agent-online-feedback.v1",
        "feedbackId": "fb-1",
        "goal": "refund",
        "rating": "negative",
        "consentForEvaluation": False,
        "readOnly": True,
        "expectedTools": ["rag_search"],
        "forbiddenTools": [],
    }
    source.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(EvaluationDatasetError, match="consent"):
        import_feedback(source, dataset_id="feedback")

    value["consentForEvaluation"] = True
    value["readOnly"] = False
    source.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(EvaluationDatasetError, match="read-only"):
        import_feedback(source, dataset_id="feedback")


async def test_replay_requires_the_exact_dataset_version(tmp_path: Path) -> None:
    dataset = build_dataset("refund-baseline", "baseline", (case(),))
    report = await evaluate_shadow(
        dataset.cases,
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        dataset=dataset.reference(),
        transport=_successful_transport(),
    )
    report_path = tmp_path / "report.json"
    write_report(report, report_path)

    replay = replay_reference(report_path, dataset)
    assert replay.report_sha256.startswith("sha256:")

    changed = build_dataset("refund-baseline", "baseline", (case(case_id="c2"),))
    with pytest.raises(EvaluationDatasetError, match="dataset version"):
        replay_reference(report_path, changed)


def _successful_transport():
    import httpx

    return httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "goal": "goal",
                "steps": [
                    {
                        "n": 1,
                        "action": "rag_search",
                        "actionInput": "refund",
                        "observation": "found",
                    }
                ],
                "finalAnswer": "answer",
                "stopReason": "DONE",
                "tenantId": "acme",
            },
        )
    )
