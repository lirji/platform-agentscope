import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agentscope_platform.evaluation import cli
from agentscope_platform.evaluation.dataset import build_dataset, write_dataset
from agentscope_platform.evaluation.models import (
    GateResult,
    ShadowReport,
    ShadowThresholds,
    TargetSummary,
)
from agentscope_platform.evaluation.shadow import load_cases


def report(passed: bool) -> ShadowReport:
    summary = TargetSummary(
        name="legacy",
        total_runs=1,
        passed_runs=1,
        pass_rate=1,
        completion_rate=1,
        tool_accuracy=1,
        forbidden_violations=0,
        contract_errors=0,
        p95_latency_ms=1,
        stop_reasons={"DONE": 1},
    )
    return ShadowReport(
        suite="test",
        generated_at=datetime.now(UTC),
        runs_per_case=1,
        gate=GateResult(
            passed=passed,
            regressions=() if passed else ("regression",),
            thresholds=ShadowThresholds(),
            legacy=summary,
            candidate=summary.model_copy(update={"name": "candidate"}),
        ),
        samples=(),
    )


def suite(tmp_path: Path) -> Path:
    path = tmp_path / "suite.jsonl"
    path.write_text(
        '{"id":"time","goal":"time","expectedTools":["current_time"],'
        '"forbiddenTools":[],"readOnly":true}\n',
        encoding="utf-8",
    )
    return path


class AgentHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        goal = json.loads(self.rfile.read(length))["goal"]
        body = json.dumps(
            {
                "goal": goal,
                "steps": [
                    {
                        "n": 1,
                        "thought": "",
                        "action": "current_time",
                        "actionInput": "UTC",
                        "observation": "now",
                    }
                ],
                "finalAnswer": "now",
                "stopReason": "DONE",
                "depth": 0,
                "tenantId": "test",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


async def test_cli_runs_against_real_local_http_targets(tmp_path: Path) -> None:
    servers = [
        ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler),
        ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler),
    ]
    threads = [threading.Thread(target=server.serve_forever) for server in servers]
    for thread in threads:
        thread.start()
    output = tmp_path / "local-report.json"
    try:
        exit_code = await cli.async_main(
            [
                "--legacy-url",
                f"http://127.0.0.1:{servers[0].server_port}",
                "--candidate-url",
                f"http://127.0.0.1:{servers[1].server_port}",
                "--suite",
                str(suite(tmp_path)),
                "--output",
                str(output),
                "--runs",
                "1",
            ]
        )
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["gate"]["passed"] is True


async def test_cli_exit_codes_and_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result = report(True)

    async def fake_evaluate(*args: object, **kwargs: object) -> ShadowReport:
        del args, kwargs
        return result

    monkeypatch.setattr(cli, "evaluate_shadow", fake_evaluate)
    output = tmp_path / "report.json"
    args = [
        "--legacy-url",
        "http://legacy.localhost",
        "--candidate-url",
        "http://candidate.localhost",
        "--suite",
        str(suite(tmp_path)),
        "--output",
        str(output),
    ]

    assert await cli.async_main(args) == 0
    assert output.exists()

    result.gate.passed = False
    result.gate.regressions = ("regression",)
    assert await cli.async_main(args) == 1


async def test_cli_uses_versioned_dataset_and_replay_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dataset = build_dataset(
        "versioned-suite",
        "baseline",
        load_cases(suite(tmp_path)),
    )
    dataset_path = tmp_path / "dataset.json"
    write_dataset(dataset, dataset_path)
    prior = report(True).model_copy(update={"dataset": dataset.reference()})
    prior_path = tmp_path / "prior.json"
    prior_path.write_text(prior.model_dump_json(), encoding="utf-8")
    captured: dict[str, object] = {}

    async def fake_evaluate(*args: object, **kwargs: object) -> ShadowReport:
        del args
        captured.update(kwargs)
        return prior

    monkeypatch.setattr(cli, "evaluate_shadow", fake_evaluate)
    output = tmp_path / "replay.json"

    exit_code = await cli.async_main(
        [
            "--legacy-url",
            "http://legacy.localhost",
            "--candidate-url",
            "http://candidate.localhost",
            "--dataset",
            str(dataset_path),
            "--replay-report",
            str(prior_path),
            "--require-version-metadata",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert captured["dataset"] == dataset.reference()
    assert captured["replay"] is not None
    assert captured["require_version_metadata"] is True


async def test_cli_returns_configuration_error_for_remote_target(tmp_path: Path) -> None:
    exit_code = await cli.async_main(
        [
            "--legacy-url",
            "http://legacy.example",
            "--candidate-url",
            "http://candidate.localhost",
            "--suite",
            str(suite(tmp_path)),
        ]
    )

    assert exit_code == 2


async def test_cli_requires_environment_key_when_judge_is_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SHADOW_JUDGE_API_KEY", raising=False)
    exit_code = await cli.async_main(
        [
            "--legacy-url",
            "http://legacy.localhost",
            "--candidate-url",
            "http://candidate.localhost",
            "--suite",
            str(suite(tmp_path)),
            "--judge-enabled",
        ]
    )

    assert exit_code == 2


async def test_cli_requires_separate_remote_judge_opt_in(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SHADOW_JUDGE_API_KEY", "test-secret")
    exit_code = await cli.async_main(
        [
            "--legacy-url",
            "http://legacy.localhost",
            "--candidate-url",
            "http://candidate.localhost",
            "--suite",
            str(suite(tmp_path)),
            "--judge-enabled",
            "--judge-base-url",
            "https://judge.test/v1",
        ]
    )

    assert exit_code == 2


async def test_cli_passes_opted_in_judge_without_exposing_environment_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    expected_report = report(True)

    class StubJudge:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

    judge = StubJudge()

    def fake_judge(**kwargs: object) -> StubJudge:
        captured["constructor"] = kwargs
        return judge

    async def fake_evaluate(*args: object, **kwargs: object) -> ShadowReport:
        del args
        captured["evaluate"] = kwargs
        return expected_report

    monkeypatch.setattr(cli, "LiteLLMAnswerJudge", fake_judge)
    monkeypatch.setattr(cli, "evaluate_shadow", fake_evaluate)
    monkeypatch.setenv("SHADOW_JUDGE_API_KEY", "environment-only-secret")
    output = tmp_path / "judge-report.json"

    exit_code = await cli.async_main(
        [
            "--legacy-url",
            "http://legacy.localhost",
            "--candidate-url",
            "http://candidate.localhost",
            "--suite",
            str(suite(tmp_path)),
            "--output",
            str(output),
            "--judge-enabled",
        ]
    )

    assert exit_code == 0
    assert captured["evaluate"]["judge"] is judge  # type: ignore[index]
    assert captured["constructor"]["api_key"] == "environment-only-secret"  # type: ignore[index]
    assert "environment-only-secret" not in output.read_text(encoding="utf-8")
