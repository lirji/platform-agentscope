import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agentscope_platform.evaluation import cli
from agentscope_platform.evaluation.models import (
    GateResult,
    ShadowReport,
    ShadowThresholds,
    TargetSummary,
)


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
