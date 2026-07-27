import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentscope_platform.evaluation.models import ShadowReport


class CostAttributionError(RuntimeError):
    pass


class CostLedgerEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    trace_id: str = Field(alias="traceId", min_length=1)
    request_id: str = Field(alias="requestId", min_length=1)
    input_tokens: int = Field(default=0, alias="inputTokens", ge=0)
    output_tokens: int = Field(default=0, alias="outputTokens", ge=0)
    cost_usd: Decimal = Field(default=Decimal(0), alias="costUsd", ge=0)


class CostRunSample(BaseModel):
    case_id: str
    target: str
    run: int
    trace_id: str
    measured: bool
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class CostTargetSummary(BaseModel):
    name: str
    total_runs: int
    measured_runs: int
    missing_runs: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    average_cost_usd: Decimal | None


class CostThresholds(BaseModel):
    max_candidate_cost_ratio: Decimal = Field(default=Decimal("1.25"), ge=0)
    candidate_cost_slack_usd: Decimal = Field(default=Decimal("0.001"), ge=0)


class CostGateResult(BaseModel):
    passed: bool
    regressions: tuple[str, ...]
    thresholds: CostThresholds
    legacy: CostTargetSummary
    candidate: CostTargetSummary
    candidate_cost_limit_usd: Decimal | None


class CostReport(BaseModel):
    schema_version: str = "1"
    suite: str
    source_generated_at: datetime
    generated_at: datetime
    gate: CostGateResult
    samples: tuple[CostRunSample, ...]


def load_shadow_report(path: Path) -> ShadowReport:
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CostAttributionError(f"unable to read Shadow report: {path}") from exc
    try:
        return ShadowReport.model_validate_json(value)
    except (ValidationError, ValueError) as exc:
        raise CostAttributionError("invalid Shadow report") from exc


def load_cost_ledger(path: Path) -> tuple[CostLedgerEntry, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CostAttributionError(f"unable to read cost ledger: {path}") from exc

    entries: list[CostLedgerEntry] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(CostLedgerEntry.model_validate_json(line))
        except (ValidationError, ValueError) as exc:
            raise CostAttributionError(
                f"invalid cost ledger entry at line {line_number}",
            ) from exc
    if not entries:
        raise CostAttributionError("cost ledger contains no entries")
    return tuple(entries)


def join_costs(
    shadow: ShadowReport,
    ledger: tuple[CostLedgerEntry, ...],
    thresholds: CostThresholds | None = None,
) -> CostReport:
    entries_by_trace: dict[str, list[CostLedgerEntry]] = defaultdict(list)
    request_ids: set[str] = set()
    for entry in ledger:
        if entry.request_id in request_ids:
            raise CostAttributionError("cost ledger contains duplicate request IDs")
        request_ids.add(entry.request_id)
        entries_by_trace[entry.trace_id].append(entry)

    non_empty_traces = [sample.trace_id for sample in shadow.samples if sample.trace_id]
    if len(non_empty_traces) != len(set(non_empty_traces)):
        raise CostAttributionError("Shadow report contains duplicate trace IDs")

    samples: list[CostRunSample] = []
    for sample in shadow.samples:
        matched = entries_by_trace.get(sample.trace_id, []) if sample.trace_id else []
        samples.append(
            CostRunSample(
                case_id=sample.case_id,
                target=sample.target,
                run=sample.run,
                trace_id=sample.trace_id,
                measured=bool(matched),
                model_calls=len(matched),
                input_tokens=sum(entry.input_tokens for entry in matched),
                output_tokens=sum(entry.output_tokens for entry in matched),
                cost_usd=sum(
                    (entry.cost_usd for entry in matched),
                    start=Decimal(0),
                ),
            ),
        )

    legacy = _summarize_cost("legacy", samples)
    candidate = _summarize_cost("candidate", samples)
    resolved_thresholds = thresholds or CostThresholds()
    regressions: list[str] = []
    if legacy.missing_runs:
        regressions.append(f"legacy_cost_missing: {legacy.missing_runs} run(s)")
    if candidate.missing_runs:
        regressions.append(f"candidate_cost_missing: {candidate.missing_runs} run(s)")

    candidate_limit: Decimal | None = None
    if not legacy.missing_runs and not candidate.missing_runs:
        candidate_limit = (
            legacy.cost_usd * resolved_thresholds.max_candidate_cost_ratio
            + resolved_thresholds.candidate_cost_slack_usd
        )
        if candidate.cost_usd > candidate_limit:
            regressions.append(
                "candidate_cost regression: "
                f"{candidate.cost_usd} USD > limit {candidate_limit} USD",
            )

    return CostReport(
        suite=shadow.suite,
        source_generated_at=shadow.generated_at,
        generated_at=datetime.now(UTC),
        gate=CostGateResult(
            passed=not regressions,
            regressions=tuple(regressions),
            thresholds=resolved_thresholds,
            legacy=legacy,
            candidate=candidate,
            candidate_cost_limit_usd=candidate_limit,
        ),
        samples=tuple(samples),
    )


def _summarize_cost(
    name: str,
    samples: list[CostRunSample],
) -> CostTargetSummary:
    selected = [sample for sample in samples if sample.target == name]
    if not selected:
        raise CostAttributionError(f"Shadow report has no target samples: {name}")
    measured = [sample for sample in selected if sample.measured]
    cost = sum((sample.cost_usd for sample in measured), start=Decimal(0))
    return CostTargetSummary(
        name=name,
        total_runs=len(selected),
        measured_runs=len(measured),
        missing_runs=len(selected) - len(measured),
        model_calls=sum(sample.model_calls for sample in measured),
        input_tokens=sum(sample.input_tokens for sample in measured),
        output_tokens=sum(sample.output_tokens for sample in measured),
        cost_usd=cost,
        average_cost_usd=cost / len(measured) if measured else None,
    )


def write_cost_report(report: CostReport, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise CostAttributionError(f"unable to write cost report: {path}") from exc
