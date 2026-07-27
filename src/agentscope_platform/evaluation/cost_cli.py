import argparse
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from agentscope_platform.evaluation.cost import (
    CostAttributionError,
    CostThresholds,
    join_costs,
    load_cost_ledger,
    load_shadow_report,
    write_cost_report,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Join a sanitized Shadow report with trace-attributed cost rows.",
    )
    value.add_argument("--shadow-report", type=Path, required=True)
    value.add_argument("--ledger", type=Path, required=True)
    value.add_argument("--output", type=Path, default=Path("reports/shadow-cost.json"))
    value.add_argument("--max-candidate-cost-ratio", type=Decimal, default=Decimal("1.25"))
    value.add_argument("--candidate-cost-slack-usd", type=Decimal, default=Decimal("0.001"))
    return value


def run(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        _validate_distinct_paths(args.shadow_report, args.ledger, args.output)
        thresholds = CostThresholds(
            max_candidate_cost_ratio=args.max_candidate_cost_ratio,
            candidate_cost_slack_usd=args.candidate_cost_slack_usd,
        )
        report = join_costs(
            load_shadow_report(args.shadow_report),
            load_cost_ledger(args.ledger),
            thresholds,
        )
        write_cost_report(report, args.output)
    except (CostAttributionError, ValidationError, ValueError) as exc:
        print(f"shadow cost attribution error: {exc}")
        return 2

    verdict = "PASS" if report.gate.passed else "FAIL"
    print(f"shadow cost attribution {verdict}: {args.output}")
    return 0 if report.gate.passed else 1


def _validate_distinct_paths(shadow_report: Path, ledger: Path, output: Path) -> None:
    resolved_inputs = {shadow_report.resolve(), ledger.resolve()}
    if output.resolve() in resolved_inputs:
        raise CostAttributionError("output must differ from input files")


def main() -> None:
    raise SystemExit(run())
