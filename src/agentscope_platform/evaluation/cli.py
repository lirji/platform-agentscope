import argparse
import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

from agentscope_platform.evaluation.models import ShadowThresholds
from agentscope_platform.evaluation.shadow import (
    ShadowEvaluationError,
    Target,
    evaluate_shadow,
    load_cases,
    write_report,
)

DEFAULT_SUITE = Path("eval/baseline/readonly-cases.jsonl")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Compare legacy and candidate read-only Agent behavior.",
    )
    value.add_argument("--legacy-url", required=True)
    value.add_argument("--candidate-url", required=True)
    value.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    value.add_argument("--output", type=Path, default=Path("reports/shadow-evaluation.json"))
    value.add_argument("--runs", type=int, default=3)
    value.add_argument("--timeout-seconds", type=float, default=120)
    value.add_argument("--legacy-auth-header", default="X-Internal-Token")
    value.add_argument("--candidate-auth-header", default="X-Internal-Token")
    value.add_argument("--min-pass-rate", type=float, default=0.8)
    value.add_argument("--min-completion-rate", type=float, default=0.8)
    value.add_argument("--min-tool-accuracy", type=float, default=0.8)
    value.add_argument("--pass-rate-tolerance", type=float, default=0.05)
    value.add_argument("--completion-rate-tolerance", type=float, default=0.05)
    value.add_argument("--tool-accuracy-tolerance", type=float, default=0.05)
    value.add_argument("--p95-latency-ratio", type=float, default=1.5)
    value.add_argument("--p95-latency-slack-ms", type=int, default=250)
    value.add_argument(
        "--allow-remote-targets",
        action="store_true",
        help="Explicitly allow non-local test targets. Never use this for production traffic.",
    )
    return value


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    common_token = os.environ.get("SHADOW_INTERNAL_TOKEN", "")
    legacy_token = os.environ.get("SHADOW_LEGACY_TOKEN", common_token)
    candidate_token = os.environ.get("SHADOW_CANDIDATE_TOKEN", common_token)
    try:
        thresholds = ShadowThresholds(
            min_pass_rate=args.min_pass_rate,
            min_completion_rate=args.min_completion_rate,
            min_tool_accuracy=args.min_tool_accuracy,
            pass_rate_tolerance=args.pass_rate_tolerance,
            completion_rate_tolerance=args.completion_rate_tolerance,
            tool_accuracy_tolerance=args.tool_accuracy_tolerance,
            p95_latency_ratio=args.p95_latency_ratio,
            p95_latency_slack_ms=args.p95_latency_slack_ms,
        )
        cases = load_cases(args.suite)
        report = await evaluate_shadow(
            cases,
            Target(
                name="legacy",
                base_url=args.legacy_url,
                auth_header=args.legacy_auth_header,
                auth_token=legacy_token,
            ),
            Target(
                name="candidate",
                base_url=args.candidate_url,
                auth_header=args.candidate_auth_header,
                auth_token=candidate_token,
            ),
            runs=args.runs,
            timeout_seconds=args.timeout_seconds,
            thresholds=thresholds,
            allow_remote_targets=args.allow_remote_targets,
            suite_name=args.suite.stem,
        )
        write_report(report, args.output)
    except (ShadowEvaluationError, ValueError) as exc:
        print(f"shadow evaluation error: {exc}")
        return 2

    verdict = "PASS" if report.gate.passed else "FAIL"
    print(f"shadow evaluation {verdict}: {args.output}")
    return 0 if report.gate.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))
