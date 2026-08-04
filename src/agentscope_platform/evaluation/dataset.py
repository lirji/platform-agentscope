import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError

from agentscope_platform.application.privacy import redact_pii
from agentscope_platform.evaluation.models import (
    EvaluationDataset,
    OnlineFeedbackRecord,
    ReplayReference,
    ShadowCase,
    ShadowReport,
    computed_dataset_version,
)

MAX_DATASET_BYTES = 10_000_000


class EvaluationDatasetError(RuntimeError):
    pass


def build_dataset(
    dataset_id: str,
    kind: str,
    cases: tuple[ShadowCase, ...],
    *,
    source_sha256: str | None = None,
    created_at: datetime | None = None,
) -> EvaluationDataset:
    if kind not in {"baseline", "adversarial", "feedback"}:
        raise ValueError("unsupported evaluation dataset kind")
    typed_kind = cast(Literal["baseline", "adversarial", "feedback"], kind)
    return EvaluationDataset.model_validate(
        {
            "datasetId": dataset_id,
            "version": computed_dataset_version(dataset_id, typed_kind, cases),
            "kind": kind,
            "createdAt": created_at or datetime.now(UTC),
            "cases": cases,
            "sourceSha256": source_sha256,
        }
    )


def load_dataset(path: Path) -> EvaluationDataset:
    raw = _read_bounded(path, "dataset")
    try:
        return EvaluationDataset.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise EvaluationDatasetError("invalid evaluation dataset or version") from exc


def write_dataset(dataset: EvaluationDataset, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                dataset.model_dump(by_alias=True, mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise EvaluationDatasetError(f"unable to write evaluation dataset: {path}") from exc


def import_feedback(path: Path, *, dataset_id: str) -> EvaluationDataset:
    raw = _read_bounded(path, "feedback export")
    records: list[OnlineFeedbackRecord] = []
    seen: set[str] = set()
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = OnlineFeedbackRecord.model_validate_json(line)
        except ValidationError as exc:
            raise EvaluationDatasetError(f"invalid online feedback at line {line_number}") from exc
        if not record.consent_for_evaluation:
            raise EvaluationDatasetError("online feedback requires evaluation consent")
        if not record.read_only:
            raise EvaluationDatasetError("online feedback import is read-only only")
        digest = hashlib.sha256(record.feedback_id.encode("utf-8")).hexdigest()
        if digest in seen:
            raise EvaluationDatasetError("duplicate online feedback record")
        seen.add(digest)
        records.append(record)
    if not records:
        raise EvaluationDatasetError("feedback export contains no records")

    cases = tuple(
        ShadowCase(
            id=f"feedback-{hashlib.sha256(record.feedback_id.encode('utf-8')).hexdigest()[:20]}",
            goal=cast(str, redact_pii(record.goal)),
            expectedTools=record.expected_tools,
            forbiddenTools=record.forbidden_tools,
            readOnly=True,
        )
        for record in records
    )
    return build_dataset(
        dataset_id,
        "feedback",
        cases,
        source_sha256=_sha256(raw.encode("utf-8")),
    )


def replay_reference(path: Path, dataset: EvaluationDataset) -> ReplayReference:
    raw = _read_bounded(path, "shadow report")
    try:
        report = ShadowReport.model_validate_json(raw)
    except ValidationError as exc:
        raise EvaluationDatasetError("invalid replay shadow report") from exc
    if report.dataset.version != dataset.version:
        raise EvaluationDatasetError("replay report dataset version does not match")
    if report.dataset.dataset_id != dataset.dataset_id:
        raise EvaluationDatasetError("replay report dataset id does not match")
    return ReplayReference(
        reportSha256=_sha256(raw.encode("utf-8")),
        originalGeneratedAt=report.generated_at,
    )


def _read_bounded(path: Path, label: str) -> str:
    try:
        if path.stat().st_size > MAX_DATASET_BYTES:
            raise EvaluationDatasetError(f"{label} exceeds size limit")
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationDatasetError(f"unable to read {label}: {path}") from exc


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
