"""Local black-box metrics, deterministic dual-run, and bounded soak checks."""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import jwt

PYTHON_URL = "http://127.0.0.1:18085"
CENTRAL_URL = "http://127.0.0.1:18086"
SECRET = "dev-only-internal-secret-change-me-please-32b"
RESULTS = Path(__file__).with_name("results.json")
SOAK_SECONDS = 30
SOAK_BATCH_SIZE = 8


def token() -> str:
    return jwt.encode(
        {
            "sub": "qa-observability",
            "uid": "metrics-scraper",
            "scopes": ["agent", "metrics"],
            "dept": "qa",
            "exp": datetime.now(UTC) + timedelta(minutes=20),
        },
        SECRET,
        algorithm="HS256",
    )


def headers() -> dict[str, str]:
    return {
        "X-Internal-Token": token(),
        "X-Trace-Id": f"qa-metrics-{uuid4().hex}",
    }


async def wait_terminal(
    client: httpx.AsyncClient,
    task_id: str,
    *,
    timeout_seconds: float = 20,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = await client.get(
            f"{PYTHON_URL}/agent/tasks/{task_id}",
            headers=headers(),
        )
        response.raise_for_status()
        task = response.json()
        if task["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return task
        await asyncio.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish within {timeout_seconds}s")


async def submit_and_wait(
    client: httpx.AsyncClient,
    goal: str,
) -> tuple[dict[str, Any], float, float]:
    started = time.perf_counter()
    response = await client.post(
        f"{PYTHON_URL}/agent/run/async",
        headers=headers(),
        json={"goal": goal},
    )
    submitted_at = time.perf_counter()
    assert response.status_code == 202, response.text
    task = await wait_terminal(client, response.json()["taskId"])
    finished_at = time.perf_counter()
    assert task["status"] == "SUCCEEDED", task
    return task, submitted_at - started, finished_at - started


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


async def main() -> None:
    evidence: dict[str, Any] = {
        "topology": {
            "python": PYTHON_URL,
            "central": CENTRAL_URL,
            "model": "localhost deterministic stub",
            "storage": "central in-memory",
        },
        "security": {},
        "metrics": {},
        "dualRun": {},
        "soak": {},
    }
    timeout = httpx.Timeout(20)
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=32)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        python_unauth = await client.get(f"{PYTHON_URL}/metrics")
        java_unauth = await client.get(f"{CENTRAL_URL}/actuator/prometheus")
        evidence["security"] = {
            "pythonMetricsWithoutToken": python_unauth.status_code,
            "javaMetricsWithoutToken": java_unauth.status_code,
        }
        assert python_unauth.status_code == 401
        assert java_unauth.status_code == 401

        orphan_id = f"qa-orphan-{uuid4().hex}"
        created = await client.post(
            f"{CENTRAL_URL}/async/tasks",
            headers=headers(),
            json={
                "taskId": orphan_id,
                "kind": "agent.run",
                "input": {"goal": "intentionally unleased metrics probe"},
            },
        )
        assert created.status_code == 202, created.text
        await asyncio.sleep(4.5)
        orphan = await client.get(
            f"{CENTRAL_URL}/async/tasks/{orphan_id}",
            headers=headers(),
        )
        orphan.raise_for_status()
        assert orphan.json()["status"] == "FAILED", orphan.text

        matches = []
        for index in range(12):
            goal = f"deterministic observability dual-run {index}"
            sync_response = await client.post(
                f"{PYTHON_URL}/agent/run",
                headers=headers(),
                json={"goal": goal},
            )
            sync_response.raise_for_status()
            async_task, _, _ = await submit_and_wait(client, goal)
            sync_result = sync_response.json()
            async_result = async_task["result"]
            matched = {
                "finalAnswer": sync_result["finalAnswer"] == async_result["finalAnswer"],
                "stopReason": sync_result["stopReason"] == async_result["stopReason"],
            }
            assert all(matched.values()), (sync_result, async_result)
            matches.append(matched)
        evidence["dualRun"] = {
            "cases": len(matches),
            "matched": sum(all(case.values()) for case in matches),
            "fields": ["finalAnswer", "stopReason"],
        }

        submit_latencies: list[float] = []
        end_to_end_latencies: list[float] = []
        completed = 0
        soak_started = time.monotonic()
        batch = 0
        while time.monotonic() - soak_started < SOAK_SECONDS:
            batch_started = time.monotonic()
            results = await asyncio.gather(
                *(
                    submit_and_wait(client, f"bounded soak batch={batch} item={item}")
                    for item in range(SOAK_BATCH_SIZE)
                )
            )
            for _, submit_latency, end_to_end_latency in results:
                submit_latencies.append(submit_latency)
                end_to_end_latencies.append(end_to_end_latency)
            completed += len(results)
            batch += 1
            remaining = 1 - (time.monotonic() - batch_started)
            if remaining > 0:
                await asyncio.sleep(remaining)
        soak_duration = time.monotonic() - soak_started
        evidence["soak"] = {
            "durationSeconds": round(soak_duration, 3),
            "batchSize": SOAK_BATCH_SIZE,
            "submitted": completed,
            "succeeded": completed,
            "failed": 0,
            "throughputPerSecond": round(completed / soak_duration, 3),
            "submitLatencyMs": {
                "p50": round(percentile(submit_latencies, 0.50) * 1000, 3),
                "p95": round(percentile(submit_latencies, 0.95) * 1000, 3),
                "max": round(max(submit_latencies) * 1000, 3),
            },
            "endToEndLatencyMs": {
                "p50": round(percentile(end_to_end_latencies, 0.50) * 1000, 3),
                "p95": round(percentile(end_to_end_latencies, 0.95) * 1000, 3),
                "max": round(max(end_to_end_latencies) * 1000, 3),
            },
        }

        python_metrics = await client.get(f"{PYTHON_URL}/metrics", headers=headers())
        java_metrics = await client.get(
            f"{CENTRAL_URL}/actuator/prometheus",
            headers=headers(),
        )
        python_metrics.raise_for_status()
        java_metrics.raise_for_status()
        required_python = [
            'agent_async_task_submissions_total{kind="agent.run"}',
            'agent_async_task_completions_total{kind="agent.run",status="SUCCEEDED"}',
            'agent_async_task_running{kind="agent.run"}',
        ]
        required_java = [
            "async_task_orphan_failed_total",
            'kind="agent.run"',
        ]
        for marker in required_python:
            assert marker in python_metrics.text, marker
        for marker in required_java:
            assert marker in java_metrics.text, marker
        forbidden = ("task_id=", "tenant_id=", "user_id=", "prompt=", "result=", "token=")
        python_async_series = "\n".join(
            line
            for line in python_metrics.text.splitlines()
            if line.startswith("agent_async_task_")
        )
        java_async_series = "\n".join(
            line for line in java_metrics.text.splitlines() if line.startswith("async_task_")
        )
        for label in forbidden:
            assert label not in python_async_series
            assert label not in java_async_series
        evidence["metrics"] = {
            "pythonStatus": python_metrics.status_code,
            "javaStatus": java_metrics.status_code,
            "pythonContentType": python_metrics.headers["content-type"],
            "javaContentType": java_metrics.headers["content-type"],
            "pythonRequiredSeries": required_python,
            "javaRequiredMarkers": required_java,
            "forbiddenLabelsAbsent": list(forbidden),
            "pythonSampleLineCount": len(python_metrics.text.splitlines()),
            "javaSampleLineCount": len(java_metrics.text.splitlines()),
        }

    RESULTS.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
