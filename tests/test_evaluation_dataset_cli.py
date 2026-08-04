import json
from pathlib import Path

from agentscope_platform.evaluation import dataset_cli
from agentscope_platform.evaluation.dataset import load_dataset


def test_dataset_cli_migrates_legacy_jsonl_and_validates(tmp_path: Path) -> None:
    source = tmp_path / "cases.jsonl"
    source.write_text(
        '{"id":"c1","goal":"refund","expectedTools":["rag_search"],'
        '"forbiddenTools":[],"readOnly":true}\n',
        encoding="utf-8",
    )
    output = tmp_path / "dataset.json"

    assert (
        dataset_cli.run(
            [
                "migrate",
                "--input",
                str(source),
                "--output",
                str(output),
                "--dataset-id",
                "refund-baseline",
                "--kind",
                "baseline",
            ]
        )
        == 0
    )
    assert load_dataset(output).dataset_id == "refund-baseline"
    assert dataset_cli.run(["validate", str(output)]) == 0


def test_dataset_cli_imports_feedback_without_raw_identifier(tmp_path: Path) -> None:
    source = tmp_path / "feedback.jsonl"
    source.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-online-feedback.v1",
                "feedbackId": "raw-feedback-id",
                "goal": "refund policy",
                "rating": "negative",
                "consentForEvaluation": True,
                "readOnly": True,
                "expectedTools": ["rag_search"],
                "forbiddenTools": ["refund_start"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "feedback-dataset.json"

    assert (
        dataset_cli.run(
            [
                "import-feedback",
                "--input",
                str(source),
                "--output",
                str(output),
                "--dataset-id",
                "feedback-nightly",
            ]
        )
        == 0
    )
    assert "raw-feedback-id" not in output.read_text(encoding="utf-8")
