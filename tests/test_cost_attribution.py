import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from agentscope_platform.evaluation import cost_cli
from agentscope_platform.evaluation.cost import (
    CostAttributionError,
    CostLedgerEntry,
    CostThresholds,
    join_costs,
    load_cost_ledger,
    write_cost_report,
)
from agentscope_platform.evaluation.models import (
    GateResult,
    RunSample,
    ShadowReport,
    ShadowThresholds,
    TargetSummary,
)


def shadow_report() -> ShadowReport:
    summary = TargetSummary(
        name="legacy",
        total_runs=2,
        passed_runs=2,
        pass_rate=1,
        completion_rate=1,
        tool_accuracy=1,
        forbidden_violations=0,
        contract_errors=0,
        p95_latency_ms=1,
        stop_reasons={"DONE": 2},
    )
    samples = tuple(
        RunSample(
            case_id=case_id,
            target=target,
            run=1,
            trace_id=trace_id,
            status_code=200,
            latency_ms=1,
            contract_valid=True,
            completed=True,
            passed=True,
        )
        for case_id, target, trace_id in (
            ("order", "legacy", "legacy-order"),
            ("order", "candidate", "candidate-order"),
            ("time", "legacy", "legacy-time"),
            ("time", "candidate", "candidate-time"),
        )
    )
    return ShadowReport(
        suite="readonly",
        generated_at=datetime.now(UTC),
        runs_per_case=1,
        gate=GateResult(
            passed=True,
            regressions=(),
            thresholds=ShadowThresholds(),
            legacy=summary,
            candidate=summary.model_copy(update={"name": "candidate"}),
        ),
        samples=samples,
    )


def ledger() -> tuple[CostLedgerEntry, ...]:
    values = (
        {
            "traceId": "legacy-order",
            "inputTokens": 100,
            "outputTokens": 20,
            "costUsd": "0.010",
        },
        {
            "traceId": "legacy-order",
            "inputTokens": 50,
            "outputTokens": 5,
            "costUsd": "0.002",
        },
        {
            "traceId": "legacy-time",
            "inputTokens": 50,
            "outputTokens": 10,
            "costUsd": "0.008",
        },
        {
            "traceId": "candidate-order",
            "inputTokens": 80,
            "outputTokens": 15,
            "costUsd": "0.009",
        },
        {
            "traceId": "candidate-time",
            "inputTokens": 40,
            "outputTokens": 8,
            "costUsd": "0.006",
        },
    )
    return tuple(
        CostLedgerEntry.model_validate(
            {**value, "requestId": f"request-{request_id}"},
        )
        for request_id, value in enumerate(values, start=1)
    )


def test_cost_join_aggregates_model_calls_by_trace_and_target(tmp_path: Path) -> None:
    report = join_costs(
        shadow_report(),
        ledger(),
        CostThresholds(
            max_candidate_cost_ratio=Decimal("1"),
            candidate_cost_slack_usd=Decimal("0"),
        ),
    )

    assert report.gate.passed
    assert report.gate.legacy.model_calls == 3
    assert report.gate.legacy.input_tokens == 200
    assert report.gate.legacy.output_tokens == 35
    assert report.gate.legacy.cost_usd == Decimal("0.020")
    assert report.gate.candidate.model_calls == 2
    assert report.gate.candidate.cost_usd == Decimal("0.015")
    assert report.gate.candidate_cost_limit_usd == Decimal("0.020")

    output = tmp_path / "cost.json"
    write_cost_report(report, output)
    serialized = output.read_text(encoding="utf-8")
    parsed = json.loads(serialized)
    assert parsed["gate"]["legacy"]["cost_usd"] == "0.020"
    assert "messages" not in serialized
    assert "api_key" not in serialized


def test_cost_gate_fails_missing_rows_and_candidate_regression() -> None:
    missing = join_costs(shadow_report(), ledger()[:-1])

    assert not missing.gate.passed
    assert missing.gate.candidate.missing_runs == 1
    assert missing.gate.candidate_cost_limit_usd is None
    assert missing.gate.regressions == ("candidate_cost_missing: 1 run(s)",)

    expensive = list(ledger())
    expensive[-1] = expensive[-1].model_copy(update={"cost_usd": Decimal("1")})
    regressed = join_costs(
        shadow_report(),
        tuple(expensive),
        CostThresholds(
            max_candidate_cost_ratio=Decimal("1"),
            candidate_cost_slack_usd=Decimal("0"),
        ),
    )

    assert not regressed.gate.passed
    assert any("candidate_cost regression" in item for item in regressed.gate.regressions)


def test_cost_join_rejects_duplicate_shadow_traces() -> None:
    shadow = shadow_report()
    shadow.samples[1].trace_id = shadow.samples[0].trace_id

    with pytest.raises(CostAttributionError, match="duplicate trace"):
        join_costs(shadow, ledger())


def test_cost_join_rejects_duplicate_request_ids() -> None:
    duplicated = (
        *ledger(),
        ledger()[0].model_copy(update={"trace_id": "candidate-time"}),
    )

    with pytest.raises(CostAttributionError, match="duplicate request"):
        join_costs(shadow_report(), duplicated)


def test_cost_ledger_validation_is_safe(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        '{"traceId":"trace","inputTokens":-1,"providerPayload":"secret"}\n',
        encoding="utf-8",
    )

    with pytest.raises(CostAttributionError, match="line 1") as captured:
        load_cost_ledger(path)

    assert "secret" not in str(captured.value)


def test_cost_cli_exit_codes_and_sanitized_report(tmp_path: Path) -> None:
    shadow_path = tmp_path / "shadow.json"
    shadow_path.write_text(
        shadow_report().model_dump_json(),
        encoding="utf-8",
    )
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text(
        "\n".join(entry.model_dump_json(by_alias=True) for entry in ledger()) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "cost.json"

    assert (
        cost_cli.run(
            [
                "--shadow-report",
                str(shadow_path),
                "--ledger",
                str(ledger_path),
                "--output",
                str(output),
            ],
        )
        == 0
    )
    assert output.exists()

    assert (
        cost_cli.run(
            [
                "--shadow-report",
                str(shadow_path),
                "--ledger",
                str(ledger_path),
                "--output",
                str(output),
                "--max-candidate-cost-ratio",
                "0",
                "--candidate-cost-slack-usd",
                "0",
            ],
        )
        == 1
    )

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("{}\n", encoding="utf-8")
    assert (
        cost_cli.run(
            [
                "--shadow-report",
                str(shadow_path),
                "--ledger",
                str(invalid),
                "--output",
                str(output),
            ],
        )
        == 2
    )

    assert (
        cost_cli.run(
            [
                "--shadow-report",
                str(shadow_path),
                "--ledger",
                str(ledger_path),
                "--output",
                str(shadow_path),
            ],
        )
        == 2
    )
