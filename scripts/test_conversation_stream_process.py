#!/usr/bin/env python3
"""独立candidate进程+本地假OpenAI HTTP/SSE, 验证Java观察、错误及取消传播."""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-repo", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidate_port, provider_port = port(), port()
    secret = uuid4().hex + uuid4().hex
    provider_cancelled = threading.Event()
    provider_started = threading.Event()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            self.send_response(200 if provider_started.is_set() else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            message = str(payload["messages"][-1]["content"])
            if "error" in message:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if "disconnect" in message:
                provider_started.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _n in range(100 if "disconnect" in message else 1):
                    delta = {
                        "id": "fake",
                        "object": "chat.completion.chunk",
                        "model": "fake",
                        "created": 1,
                        "choices": [
                            {"index": 0, "delta": {"content": "fake answer"}, "finish_reason": None}
                        ],
                    }
                    self.wfile.write(("data: " + json.dumps(delta) + "\n\n").encode())
                    self.wfile.flush()
                    if "disconnect" in message:
                        time.sleep(0.05)
                final = {
                    "id": "fake",
                    "model": "fake",
                    "created": 1,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                }
                self.wfile.write(("data: " + json.dumps(final) + "\n\ndata: [DONE]\n\n").encode())
            except (BrokenPipeError, ConnectionResetError):
                if "disconnect" in message:
                    provider_cancelled.set()

    server = ThreadingHTTPServer(("127.0.0.1", provider_port), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "local",
            "INTERNAL_JWT_SECRET": secret,
            "INTERNAL_JWT_ALGORITHM": "HS256",
            "ASYNC_TASK_ENABLED": "false",
            "ASYNC_TASK_ROLE": "inline",
            "TOKEN_BUDGET_ENABLED": "false",
            "GATEWAY_API_KEY": "fake-only",
            "GATEWAY_MODEL": "fake",
            "GATEWAY_BASE_URL": f"http://127.0.0.1:{provider_port}/v1",
            "AGENT_MODEL_MAX_RETRIES": "0",
            "AGENT_REFUND_START_ENABLED": "false",
            "AGENT_MCP_ENABLED": "false",
            "AGENT_BROWSER_ENABLED": "false",
            "AGENT_CODE_EXEC_ENABLED": "false",
            "INTERNAL_AUTH_REQUIRED": "true",
            "OTEL_ENABLED": "false",
            "PYTHONPATH": str(root / "src"),
            "STREAM_SHADOW_PROCESS_URL": f"http://127.0.0.1:{candidate_port}",
            "STREAM_SHADOW_INTERNAL_SECRET": secret,
            "STREAM_SHADOW_PROVIDER_URL": f"http://127.0.0.1:{provider_port}/started",
        }
    )
    log_dir = root / ".git" / "codex-cross-runtime-reliability-baseline"
    with (log_dir / "conversation-candidate-process.log").open("w") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agentscope_platform.conversation_candidate:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(candidate_port),
            ],
            cwd=root,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            with httpx.Client(trust_env=False, timeout=1) as http:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("candidate exited; inspect local candidate process log")
                    try:
                        if http.get(f"http://127.0.0.1:{candidate_port}/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise TimeoutError("candidate did not start")
                assert (
                    http.post(f"http://127.0.0.1:{candidate_port}/agent/run", json={}).status_code
                    == 404
                )
            with (log_dir / "conversation-stream-cross-language.log").open("w") as evidence:
                result = subprocess.run(
                    [
                        "mvn",
                        "-o",
                        "-B",
                        "-pl",
                        "conversation-service",
                        "-am",
                        "-Dtest=ConversationStreamCandidateProcessTest",
                        "-Dsurefire.failIfNoSpecifiedTests=false",
                        "test",
                    ],
                    cwd=args.java_repo.resolve(),
                    env=env,
                    stdout=evidence,
                    stderr=subprocess.STDOUT,
                )
            if result.returncode != 0:
                return result.returncode
            assert provider_cancelled.wait(timeout=5), (
                "candidate did not close the fake provider after cancellation"
            )
            print("PASS: stateless process, signed Java SSE, terminal/error, TCP cancellation")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
