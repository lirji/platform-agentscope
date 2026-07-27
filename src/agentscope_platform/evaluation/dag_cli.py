import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

from agentscope_platform.evaluation.dag_shadow import (
    evaluate_dag_shadow,
    load_dag_cases,
)
from agentscope_platform.evaluation.shadow import (
    ShadowEvaluationError,
    Target,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Compare legacy and candidate read-only DAG structure.",
    )
    value.add_argument("--legacy-url", required=True)
    value.add_argument("--candidate-url", required=True)
    value.add_argument(
        "--suite",
        type=Path,
        default=Path("eval/baseline/dag-cases.jsonl"),
    )
    value.add_argument(
        "--output",
        type=Path,
        default=Path("reports/dag-shadow-evaluation.json"),
    )
    value.add_argument("--timeout-seconds", type=float, default=120)
    value.add_argument("--legacy-auth-header", default="X-Internal-Token")
    value.add_argument("--candidate-auth-header", default="X-Internal-Token")
    value.add_argument("--allow-remote-targets", action="store_true")
    return value


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    common_token = os.environ.get("SHADOW_INTERNAL_TOKEN", "")
    try:
        report = await evaluate_dag_shadow(
            load_dag_cases(args.suite),
            Target(
                "legacy",
                args.legacy_url,
                args.legacy_auth_header,
                os.environ.get("SHADOW_LEGACY_TOKEN", common_token),
            ),
            Target(
                "candidate",
                args.candidate_url,
                args.candidate_auth_header,
                os.environ.get("SHADOW_CANDIDATE_TOKEN", common_token),
            ),
            timeout_seconds=args.timeout_seconds,
            allow_remote_targets=args.allow_remote_targets,
            suite_name=args.suite.stem,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                report.model_dump(by_alias=True, mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ShadowEvaluationError, ValueError) as exc:
        print(f"DAG shadow evaluation error: {exc}")
        return 2

    verdict = "PASS" if report.passed else "FAIL"
    print(f"DAG shadow evaluation {verdict}: {args.output}")
    return 0 if report.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))
