#!/usr/bin/env python3
"""隔离MySQL与本地假OpenAI提供方的跨进程恢复验证. 不调用真实模型或业务库."""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import jwt

from agentscope_platform.core.config import Settings
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.security.async_task_worker_jwt import (
    AsyncTaskWorkerTokenIssuer,
)


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-repo", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    java = args.java_repo.resolve()
    container = "dev-infra-mysql84-1"
    inspected = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    config = dict(v.split("=", 1) for v in inspected["Config"]["Env"] if "=" in v)
    password = config["MYSQL_ROOT_PASSWORD"]
    database = "lc4j_dispatch_it_" + uuid4().hex
    mysql = [
        "docker",
        "exec",
        "-i",
        container,
        "sh",
        "-c",
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot',
    ]
    subprocess.run(
        mysql, input=f"CREATE DATABASE {database};", text=True, check=True, capture_output=True
    )
    java_port, management_port, api_port, model_port = (port() for _ in range(4))
    internal, worker_secret = uuid4().hex + uuid4().hex, uuid4().hex + uuid4().hex
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "local",
            "INTERNAL_AUTH_REQUIRED": "true",
            "INTERNAL_JWT_SECRET": internal,
            "INTERNAL_JWT_ALGORITHM": "HS256",
            "ASYNC_TASK_ENABLED": "true",
            "ASYNC_TASK_WORKER_ID": "agentscope-platform",
            "ASYNC_TASK_WORKER_JWT_SECRET": worker_secret,
            "ASYNC_TASK_BASE_URL": f"http://127.0.0.1:{java_port}",
            "TOKEN_BUDGET_ENABLED": "false",
            "ASYNC_TASK_LEASE_SECONDS": "15",
            "ASYNC_TASK_HEARTBEAT_SECONDS": "3",
            "ASYNC_TASK_DRAIN_TIMEOUT_SECONDS": "1",
            "ASYNC_TASK_POLL_SECONDS": "0.1",
            "GATEWAY_BASE_URL": f"http://127.0.0.1:{model_port}/v1",
            "GATEWAY_API_KEY": "fake-only",
            "GATEWAY_MODEL": "fake",
            "AGENT_MODEL_MAX_RETRIES": "0",
            "AGENT_REFUND_START_ENABLED": "false",
            "AGENT_MCP_ENABLED": "false",
            "AGENT_BROWSER_ENABLED": "false",
            "AGENT_CODE_EXEC_ENABLED": "false",
            "AGENT_CONFIRMATION_REPLAY_STORE": "memory",
            "AGENT_SESSION_STORE": "memory",
            "OTEL_ENABLED": "false",
            "PYTHONPATH": str(root / "src"),
            "ASYNC_TASK_DISPATCH_ENABLED": "true",
            "ASYNC_TASK_STORE": "jdbc",
            "ASYNC_TASK_DB_URL": f"jdbc:mysql://127.0.0.1:43306/{database}?useSSL=false&allowPublicKeyRetrieval=true&nullCatalogMeansCurrent=true",
            "ASYNC_TASK_DB_USER": "root",
            "ASYNC_TASK_DB_PASSWORD": password,
            "ASYNC_TASK_WEBHOOK_ENABLED": "false",
            "ASYNC_TASK_ORPHAN_ENABLED": "false",
            "SPRING_CLOUD_CONFIG_ENABLED": "false",
            "MANAGEMENT_HEALTH_REDIS_ENABLED": "false",
            "MANAGEMENT_PORT": str(management_port),
            "MIGRATION_DB_USER": "root",
            "MIGRATION_DB_PASSWORD": password,
            "MIGRATION_SCHEMA": "async-task",
        }
    )
    env["MIGRATION_DB_URL"] = env["ASYNC_TASK_DB_URL"]
    log_dir = root / ".git" / "codex-cross-runtime-reliability-baseline"
    logs: list[object] = []
    processes: list[subprocess.Popen[bytes]] = []
    first_call = threading.Event()
    calls = [0]

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls[0] += 1
            if calls[0] == 1:
                first_call.set()
                time.sleep(25)
            response = {
                "id": "fake",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "fake",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "fake recovery answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            }
            if payload.get("response_format"):
                response["choices"][0]["message"]["content"] = json.dumps(
                    {
                        "correctness": 1,
                        "completeness": 1,
                        "clarity": 1,
                        "mainIssue": "n/a",
                    }
                )
            try:
                if payload.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    chunk = dict(response)
                    chunk["choices"] = [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "fake recovery answer"},
                            "finish_reason": "stop",
                        }
                    ]
                    self.wfile.write(
                        ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
                    )
                else:
                    data = json.dumps(response).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", model_port), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def launch(name: str, command: list[str], role: str = "inline") -> subprocess.Popen[bytes]:
        file = (log_dir / f"worker-process-{name}.log").open("wb")
        logs.append(file)
        process = subprocess.Popen(
            command,
            cwd=root,
            env={**env, "ASYNC_TASK_ROLE": role},
            stdout=file,
            stderr=subprocess.STDOUT,
        )
        processes.append(process)
        return process

    def wait_health(url: str, process: subprocess.Popen[bytes]) -> None:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("local process exited; inspect durable process logs")
            try:
                if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise TimeoutError("local process did not become healthy")

    try:
        with (log_dir / "worker-process-build.log").open("w") as output:
            subprocess.run(
                ["mvn", "-o", "-B", "-pl", "async-task-service", "-am", "-DskipTests", "package"],
                cwd=java,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
        migration = launch(
            "migration",
            [
                "java",
                "-jar",
                str(
                    java / "database-migrations/target/database-migrations-0.1.0-SNAPSHOT-exec.jar"
                ),
            ],
        )
        if migration.wait(timeout=40) != 0:
            raise RuntimeError("isolated migration failed")
        central = launch(
            "central",
            [
                "java",
                "-jar",
                str(java / "async-task-service/target/async-task-service-0.1.0-SNAPSHOT.jar"),
                f"--server.port={java_port}",
            ],
        )
        wait_health(f"http://127.0.0.1:{management_port}/actuator/health", central)
        api = launch(
            "api",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agentscope_platform.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            "api",
        )
        wait_health(f"http://127.0.0.1:{api_port}/health", api)
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": "langchain4j-platform",
                "aud": "platform-internal",
                "sub": "acme",
                "uid": "alice",
                "scopes": ["agent"],
                "token_use": "internal_access",
                "jti": str(uuid4()),
                "iat": now,
                "exp": now + timedelta(seconds=300),
            },
            internal,
            algorithm="HS256",
            headers={"kid": "platform-internal-v1", "typ": "JWT"},
        )
        with httpx.Client(trust_env=False, timeout=10, headers={"X-Internal-Token": token}) as http:
            accepted = http.post(
                f"http://127.0.0.1:{api_port}/agent/run/async",
                json={"goal": "answer without tools"},
            )
            assert accepted.status_code == 202, "API submission was rejected"
            task_id = accepted.json()["taskId"]
            dag = http.post(
                f"http://127.0.0.1:{api_port}/agent/dag/run/async",
                json={
                    "goal": "readonly DAG",
                    "tasks": [{"id": "one", "description": "answer without tools"}],
                },
            )
            assert dag.status_code == 202, "DAG submission was rejected"
            dag_id = dag.json()["taskId"]
            api.terminate()
            api.wait(timeout=15)
            first = launch(
                "worker-one", [sys.executable, "-m", "agentscope_platform.worker"], "worker"
            )
            assert first_call.wait(timeout=20), "worker did not call the local fake provider"
            url = f"http://127.0.0.1:{java_port}/async/tasks/{task_id}"
            old = http.get(url).json()
            first.kill()
            first.wait(timeout=10)
            expiry = datetime.fromisoformat(old["leaseExpiresAt"].replace("Z", "+00:00"))
            while datetime.now(UTC) <= expiry:
                time.sleep(0.2)
            launch("worker-two", [sys.executable, "-m", "agentscope_platform.worker"], "worker")
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                result = http.get(url).json()
                if result["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    break
                time.sleep(0.2)
            assert result["status"] == "SUCCEEDED", "recovered worker did not complete"
            assert result["result"]["finalAnswer"] == "fake recovery answer"
            assert result["leaseEpoch"] > old["leaseEpoch"]
            dag_url = f"http://127.0.0.1:{java_port}/async/tasks/{dag_id}"
            while time.monotonic() < deadline:
                dag_result = http.get(dag_url).json()
                if dag_result["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    break
                time.sleep(0.2)
            assert dag_result["status"] == "SUCCEEDED", "durable DAG progress failed"
            # 对已终态status接口允许幂等返回当前结果; 事件追加始终检查旧epoch并拒绝.
            proof = AsyncTaskWorkerTokenIssuer(
                Settings(
                    _env_file=None,
                    async_task_worker_id="agentscope-platform",
                    async_task_worker_jwt_secret=worker_secret,
                )
            ).issue(
                RunContext(TenantIdentity("acme", "alice"), None, "trace"),
                worker_id=old["leaseOwnerId"],
                action="event",
                task_id=task_id,
            )
            stale = http.post(
                url + "/events",
                headers={"X-Async-Worker-Token": proof},
                json={
                    "eventKey": "stale",
                    "event": "progress",
                    "data": {},
                    "workerId": old["leaseOwnerId"],
                    "leaseEpoch": old["leaseEpoch"],
                },
            )
            assert stale.status_code == 409, "old process fencing failed"
            print(
                "PASS: API exit, worker crash, second process recovery, "
                "epoch fencing, fake provider only"
            )
            return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        server.shutdown()
        for file in logs:
            file.close()
        subprocess.run(
            mysql, input=f"DROP DATABASE {database};", text=True, check=True, capture_output=True
        )


if __name__ == "__main__":
    raise SystemExit(main())
