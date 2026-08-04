import argparse
from collections.abc import Sequence
from pathlib import Path

from agentscope_platform.evaluation.dataset import (
    EvaluationDatasetError,
    build_dataset,
    import_feedback,
    load_dataset,
    write_dataset,
)
from agentscope_platform.evaluation.shadow import ShadowEvaluationError, load_cases


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Build and validate versioned Agent evaluation datasets.",
    )
    commands = value.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="Validate schema and content digest.")
    validate.add_argument("path", type=Path)

    migrate = commands.add_parser("migrate", help="Migrate a legacy read-only JSONL suite.")
    migrate.add_argument("--input", type=Path, required=True)
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--dataset-id", required=True)
    migrate.add_argument("--kind", choices=("baseline", "adversarial"), required=True)

    feedback = commands.add_parser(
        "import-feedback",
        help="Import consented read-only feedback and redact common PII.",
    )
    feedback.add_argument("--input", type=Path, required=True)
    feedback.add_argument("--output", type=Path, required=True)
    feedback.add_argument("--dataset-id", required=True)
    return value


def run(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            dataset = load_dataset(args.path)
            print(f"dataset valid: {dataset.dataset_id}@{dataset.version}")
            return 0
        if args.command == "migrate":
            dataset = build_dataset(
                args.dataset_id,
                args.kind,
                load_cases(args.input),
            )
        else:
            dataset = import_feedback(args.input, dataset_id=args.dataset_id)
        write_dataset(dataset, args.output)
    except (EvaluationDatasetError, ShadowEvaluationError, ValueError) as exc:
        print(f"evaluation dataset error: {exc}")
        return 2
    print(f"dataset written: {args.output}")
    return 0


def main() -> None:
    raise SystemExit(run())
