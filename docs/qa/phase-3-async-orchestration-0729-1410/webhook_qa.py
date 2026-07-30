"""Set up or verify local webhook outbox QA fixtures."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt

CENTRAL = "http://127.0.0.1:18086"
STUB = "http://127.0.0.1:14000"
TARGETS = Path(__file__).with_name("webhook-targets.json")
RESULTS = Path(__file__).with_name("webhook-results.json")
LEGACY_FIELDS = {
    "taskId",
    "tenantId",
    "userId",
    "status",
    "input",
    "result",
    "error",
    "createdAt",
    "updatedAt",
    "finishedAt",
}


def auth() -> dict[str, str]:
    raw = jwt.encode(
        {
            "sub": "qa-acme",
            "uid": "alice",
            "scopes": ["agent"],
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        "dev-only-internal-secret-change-me-please-32b",
        algorithm="HS256",
    )
    return {"X-Internal-Token": raw, "X-Trace-Id": f"qa-webhook-{uuid4().hex}"}


def setup() -> None:
    suffix = uuid4().hex[:10]
    targets = {mode: f"qa-webhook-{mode}-{suffix}" for mode in ("success", "retry2", "dead")}
    with httpx.Client() as client:
        response = client.post(f"{STUB}/reset")
        response.raise_for_status()
        for mode, task_id in targets.items():
            response = client.post(
                f"{CENTRAL}/async/tasks",
                headers=auth(),
                json={
                    "taskId": task_id,
                    "kind": "agent.run",
                    "input": {"goal": f"synthetic webhook {mode}"},
                    "webhookUrl": f"{STUB}/webhooks/{mode}",
                },
            )
            response.raise_for_status()
            response = client.post(
                f"{CENTRAL}/async/tasks/{task_id}/lease",
                headers=auth(),
                json={"workerId": "qa-webhook-worker", "leaseSeconds": 60},
            )
            response.raise_for_status()
            response = client.patch(
                f"{CENTRAL}/async/tasks/{task_id}/status",
                headers=auth(),
                json={
                    "status": "SUCCEEDED",
                    "result": {"marker": mode},
                    "workerId": "qa-webhook-worker",
                },
            )
            response.raise_for_status()
    TARGETS.write_text(json.dumps(targets, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "QUEUED", "targets": targets}))


def verify() -> None:
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    with httpx.Client() as client:
        state = client.get(f"{STUB}/state").json()
        dead_rows = client.get(
            f"{CENTRAL}/async/webhook-outbox/dead",
            headers=auth(),
        ).json()
    calls = state["webhookCalls"]
    assert len(calls["success"]) == 1
    assert len(calls["retry2"]) == 3
    assert len(calls["dead"]) == 3
    for mode in ("success", "retry2", "dead"):
        first = calls[mode][0]
        assert set(first["body"]) == LEGACY_FIELDS
        assert first["body"]["taskId"] == targets[mode]
        assert first["body"]["tenantId"] == "qa-acme"
        assert first["body"]["status"] == "SUCCEEDED"
        assert first["headers"]["x-async-task-id"] == targets[mode]
        assert first["headers"]["x-tenant-id"] == "qa-acme"
    matching_dead = [row for row in dead_rows if row["taskId"] == targets["dead"]]
    assert len(matching_dead) == 1
    assert matching_dead[0]["status"] == "DEAD"
    assert matching_dead[0]["attempts"] == 3
    result = {
        "status": "PASS",
        "calls": {mode: len(calls[mode]) for mode in ("success", "retry2", "dead")},
        "legacyFieldCount": len(calls["success"][0]["body"]),
        "deadInspection": {
            "taskId": matching_dead[0]["taskId"],
            "status": matching_dead[0]["status"],
            "attempts": matching_dead[0]["attempts"],
        },
    }
    RESULTS.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    {"setup": setup, "verify": verify}[sys.argv[1]]()
