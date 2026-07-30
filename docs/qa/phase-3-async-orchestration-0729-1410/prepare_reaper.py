"""Create scoped black-box fixtures for the orphan reaper race."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt

BASE = "http://127.0.0.1:18086"
OUT = Path(__file__).with_name("reaper-targets.json")
token = jwt.encode(
    {
        "sub": "qa-acme",
        "uid": "alice",
        "scopes": ["agent"],
        "exp": datetime.now(UTC) + timedelta(minutes=10),
    },
    "dev-only-internal-secret-change-me-please-32b",
    algorithm="HS256",
)
headers = {"X-Internal-Token": token, "X-Trace-Id": f"qa-reaper-{uuid4().hex}"}
suffix = uuid4().hex[:10]
targets = {
    "race": f"qa-reaper-race-{suffix}",
    "fresh": f"qa-reaper-fresh-{suffix}",
    "unsupported": f"qa-reaper-unsupported-{suffix}",
    "crash": "28cd226c-5780-4ed5-9dd4-342ee1b3f518",
}

with httpx.Client() as client:
    for key, kind in (
        ("race", "agent.run"),
        ("fresh", "agent.dag"),
        ("unsupported", "qa.unsupported"),
    ):
        response = client.post(
            f"{BASE}/async/tasks",
            headers=headers,
            json={
                "taskId": targets[key],
                "kind": kind,
                "input": {"fixture": key},
            },
        )
        response.raise_for_status()
    response = client.post(
        f"{BASE}/async/tasks/{targets['race']}/lease",
        headers=headers,
        json={"workerId": "qa-dead-worker", "leaseSeconds": 1},
    )
    response.raise_for_status()
    response = client.post(
        f"{BASE}/async/tasks/{targets['fresh']}/lease",
        headers=headers,
        json={"workerId": "qa-live-worker", "leaseSeconds": 60},
    )
    response.raise_for_status()

OUT.write_text(json.dumps(targets, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "READY", "targets": targets}))
