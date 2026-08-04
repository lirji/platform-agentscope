import argparse
import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

from agentscope_platform.evaluation.dataset import (
    EvaluationDatasetError,
    load_dataset,
    replay_reference,
)
from agentscope_platform.evaluation.judge import JudgeError, LiteLLMAnswerJudge
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
    value.add_argument(
        "--dataset",
        type=Path,
        help="Versioned dataset JSON. Takes precedence over the legacy --suite JSONL.",
    )
    value.add_argument(
        "--replay-report",
        type=Path,
        help="Prior v4 report whose exact dataset version must match this replay.",
    )
    value.add_argument(
        "--require-version-metadata",
        action="store_true",
        help="Fail closed unless both targets return prompt/model/toolset version headers.",
    )
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
    value.add_argument("--min-answer-pass-rate", type=float, default=0.8)
    value.add_argument("--answer-pass-rate-tolerance", type=float, default=0.05)
    value.add_argument("--judge-enabled", action="store_true")
    value.add_argument("--judge-base-url", default="http://localhost:4000/v1")
    value.add_argument("--judge-model", default="chat-default")
    value.add_argument("--judge-timeout-seconds", type=float, default=60)
    value.add_argument("--min-judge-pass-rate", type=float, default=0.8)
    value.add_argument("--judge-pass-rate-tolerance", type=float, default=0.05)
    value.add_argument("--judge-score-tolerance", type=float, default=0.05)
    value.add_argument(
        "--allow-remote-judge",
        action="store_true",
        help="Explicitly allow a non-local judge endpoint. Never point this at production.",
    )
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
            min_answer_pass_rate=args.min_answer_pass_rate,
            answer_pass_rate_tolerance=args.answer_pass_rate_tolerance,
            min_judge_pass_rate=args.min_judge_pass_rate,
            judge_pass_rate_tolerance=args.judge_pass_rate_tolerance,
            judge_score_tolerance=args.judge_score_tolerance,
            p95_latency_ratio=args.p95_latency_ratio,
            p95_latency_slack_ms=args.p95_latency_slack_ms,
        )
        dataset = load_dataset(args.dataset) if args.dataset is not None else None
        cases = dataset.cases if dataset is not None else load_cases(args.suite)
        if args.replay_report is not None and dataset is None:
            raise EvaluationDatasetError("--replay-report requires --dataset")
        replay = (
            replay_reference(args.replay_report, dataset)
            if args.replay_report is not None and dataset is not None
            else None
        )
        dataset_reference = dataset.reference() if dataset is not None else None
        suite_name = dataset.dataset_id if dataset is not None else args.suite.stem
        judge = (
            LiteLLMAnswerJudge(
                base_url=args.judge_base_url,
                api_key=os.environ.get("SHADOW_JUDGE_API_KEY", ""),
                model=args.judge_model,
                timeout_seconds=args.judge_timeout_seconds,
                allow_remote=args.allow_remote_judge,
            )
            if args.judge_enabled
            else None
        )
        if judge is None:
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
                suite_name=suite_name,
                dataset=dataset_reference,
                replay=replay,
                require_version_metadata=args.require_version_metadata,
            )
        else:
            async with judge:
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
                    suite_name=suite_name,
                    judge=judge,
                    dataset=dataset_reference,
                    replay=replay,
                    require_version_metadata=args.require_version_metadata,
                )
        write_report(report, args.output)
    except (EvaluationDatasetError, JudgeError, ShadowEvaluationError, ValueError) as exc:
        print(f"shadow evaluation error: {exc}")
        return 2

    verdict = "PASS" if report.gate.passed else "FAIL"
    print(f"shadow evaluation {verdict}: {args.output}")
    return 0 if report.gate.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))
