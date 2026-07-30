"""Black-box baseline checks for the localhost Phase 3 QA topology."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import jwt

PYTHON_URL = "http://127.0.0.1:18085"
CENTRAL_URL = "http://127.0.0.1:18086"
SECRET = "dev-only-internal-secret-change-me-please-32b"
OUT = Path(__file__).with_name("baseline-results.json")
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


def token(tenant: str, user: str, *, expired: bool = False) -> str:
    expires = datetime.now(UTC) + (timedelta(seconds=-5) if expired else timedelta(minutes=20))
    return jwt.encode(
        {
            "sub": tenant,
            "uid": user,
            "scopes": ["agent", "approve"],
            "dept": f"{tenant}-qa",
            "exp": expires,
        },
        SECRET,
        algorithm="HS256",
    )


def headers(raw_token: str) -> dict[str, str]:
    return {
        "X-Internal-Token": raw_token,
        "X-Trace-Id": f"qa-{uuid4().hex}",
    }


async def wait_terminal(
    client: httpx.AsyncClient,
    task_id: str,
    auth: dict[str, str],
    *,
    timeout_seconds: float = 25,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(
            f"{PYTHON_URL}/agent/tasks/{task_id}",
            headers=auth,
        )
        response.raise_for_status()
        task = response.json()
        if task["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return task
        await asyncio.sleep(0.15)
    raise AssertionError(f"task {task_id} did not reach a terminal state")


async def capture_sse(
    client: httpx.AsyncClient,
    task_id: str,
    auth: dict[str, str],
    last_event_id: str | None = None,
) -> list[str]:
    params = {"lastEventId": last_event_id} if last_event_id else None
    lines: list[str] = []
    try:
        async with client.stream(
            "GET",
            f"{PYTHON_URL}/agent/tasks/{task_id}/stream",
            headers=auth,
            params=params,
            timeout=3,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 60:
                    break
    except httpx.ReadTimeout:
        pass
    return lines


async def main() -> None:
    evidence: dict[str, Any] = {"checks": {}, "tasks": {}, "manual": {}}
    run_suffix = uuid4().hex[:10]
    acme_alice = token("qa-acme", "alice")
    acme_bob = token("qa-acme", "bob")
    globex_eve = token("qa-globex", "eve")
    alice_headers = headers(acme_alice)
    bob_headers = headers(acme_bob)
    eve_headers = headers(globex_eve)

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{PYTHON_URL}/agent/tasks")
        evidence["checks"]["noToken"] = response.status_code
        assert response.status_code == 401

        response = await client.get(
            f"{PYTHON_URL}/agent/tasks",
            headers=headers("not-a-jwt"),
        )
        evidence["checks"]["invalidToken"] = response.status_code
        assert response.status_code == 401

        response = await client.get(
            f"{PYTHON_URL}/agent/tasks",
            headers=headers(token("qa-acme", "alice", expired=True)),
        )
        evidence["checks"]["expiredToken"] = response.status_code
        assert response.status_code == 401

        cases = {
            "agent.run": (
                "/agent/run/async",
                {"goal": "Return the deterministic Phase 3 QA marker."},
            ),
            "agent.dag": (
                "/agent/dag/run/async",
                {
                    "goal": "Complete one deterministic QA DAG task.",
                    "tasks": [
                        {
                            "id": "t1",
                            "description": "Return the QA marker",
                            "dependsOn": [],
                        }
                    ],
                },
            ),
            "agent.dag-plan": (
                "/agent/dag/plan-run/async",
                {"goal": "Plan and return the deterministic QA marker."},
            ),
            "agent.analyst": (
                "/agent/analyst/run/async",
                {"goal": "Give a synthetic read-only QA analysis."},
            ),
            "agent.process": (
                "/agent/process/run/async",
                {"goal": "Explain the read-only process capability boundary."},
            ),
        }
        for kind, (path, body) in cases.items():
            response = await client.post(
                f"{PYTHON_URL}{path}",
                headers=alice_headers,
                json=body,
            )
            assert response.status_code == 202, (kind, response.text)
            submitted = response.json()
            assert set(submitted) == LEGACY_FIELDS
            assert submitted["tenantId"] == "qa-acme"
            assert submitted["userId"] == "alice"
            terminal = await wait_terminal(
                client,
                submitted["taskId"],
                alice_headers,
            )
            assert terminal["status"] == "SUCCEEDED", (kind, terminal)
            evidence["tasks"][kind] = {
                "taskId": submitted["taskId"],
                "submittedStatus": submitted["status"],
                "terminalStatus": terminal["status"],
                "legacyFieldCount": len(submitted),
                "hasResult": terminal["result"] is not None,
            }

        run_task_id = evidence["tasks"]["agent.run"]["taskId"]
        response = await client.get(
            f"{PYTHON_URL}/agent/tasks/{run_task_id}",
            headers=eve_headers,
        )
        evidence["checks"]["crossTenantGet"] = response.status_code
        assert response.status_code == 404

        response = await client.get(
            f"{PYTHON_URL}/agent/tasks",
            headers=eve_headers,
        )
        assert response.status_code == 200
        evidence["checks"]["crossTenantListCount"] = len(response.json())
        assert response.json() == []

        response = await client.get(
            f"{PYTHON_URL}/agent/tasks",
            headers=bob_headers,
        )
        assert response.status_code == 200
        bob_ids = {task["taskId"] for task in response.json()}
        evidence["checks"]["sameTenantBobSeesAlice"] = run_task_id in bob_ids
        assert run_task_id in bob_ids

        response = await client.post(
            f"{CENTRAL_URL}/async/tasks",
            headers=alice_headers,
            json={
                "taskId": f"qa-hidden-kind-{run_suffix}",
                "kind": "qa.non-agent",
                "input": {"marker": "synthetic"},
            },
        )
        assert response.status_code == 202
        hidden_id = f"qa-hidden-kind-{run_suffix}"
        response = await client.get(
            f"{PYTHON_URL}/agent/tasks/{hidden_id}",
            headers=alice_headers,
        )
        evidence["checks"]["hiddenKindGet"] = response.status_code
        assert response.status_code == 404
        response = await client.get(
            f"{PYTHON_URL}/agent/tasks",
            headers=alice_headers,
        )
        assert all(item["taskId"] != hidden_id for item in response.json())

        manual_id = f"qa-manual-lifecycle-{run_suffix}"
        create_body = {
            "taskId": manual_id,
            "kind": "agent.run",
            "input": {"goal": "manual lifecycle"},
        }
        first = await client.post(
            f"{CENTRAL_URL}/async/tasks",
            headers=alice_headers,
            json=create_body,
        )
        assert first.status_code == 202
        duplicate = await client.post(
            f"{CENTRAL_URL}/async/tasks",
            headers=alice_headers,
            json=create_body,
        )
        assert duplicate.status_code == 409
        lease = await client.post(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/lease",
            headers=alice_headers,
            json={"workerId": "qa-worker-a", "leaseSeconds": 60},
        )
        assert lease.status_code == 200
        append_body = {
            "eventKey": "qa-event-1",
            "event": "dag-level-start",
            "data": {"marker": "first"},
            "workerId": "qa-worker-a",
        }
        appended = await client.post(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/events",
            headers=alice_headers,
            json=append_body,
        )
        assert appended.status_code == 200
        duplicate_event = await client.post(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/events",
            headers=alice_headers,
            json=append_body,
        )
        assert duplicate_event.status_code == 200
        assert duplicate_event.json()["sequence"] == appended.json()["sequence"]
        wrong_worker = await client.post(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/events",
            headers=alice_headers,
            json={
                "eventKey": "qa-event-wrong",
                "event": "dag-level-complete",
                "data": {},
                "workerId": "qa-worker-b",
            },
        )
        assert wrong_worker.status_code == 409
        wrong_status = await client.patch(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/status",
            headers=alice_headers,
            json={
                "status": "SUCCEEDED",
                "result": {},
                "workerId": "qa-worker-b",
            },
        )
        assert wrong_status.status_code == 409
        terminal = await client.patch(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/status",
            headers=alice_headers,
            json={
                "status": "SUCCEEDED",
                "result": {"marker": "done"},
                "workerId": "qa-worker-a",
            },
        )
        assert terminal.status_code == 200
        after_terminal = await client.post(
            f"{CENTRAL_URL}/async/tasks/{manual_id}/events",
            headers=alice_headers,
            json={
                "eventKey": "qa-event-terminal",
                "event": "dag-level-complete",
                "data": {},
                "workerId": "qa-worker-a",
            },
        )
        assert after_terminal.status_code == 409
        evidence["manual"] = {
            "duplicateCreate": duplicate.status_code,
            "duplicateEventSameSequence": True,
            "wrongWorkerEvent": wrong_worker.status_code,
            "wrongWorkerStatus": wrong_status.status_code,
            "terminalEventRejected": after_terminal.status_code,
        }

        slow = await client.post(
            f"{PYTHON_URL}/agent/run/async",
            headers=alice_headers,
            json={"goal": "QA_SLOW cancellation target"},
        )
        assert slow.status_code == 202
        slow_id = slow.json()["taskId"]
        await asyncio.sleep(0.4)
        cancelled = await client.delete(
            f"{PYTHON_URL}/agent/tasks/{slow_id}",
            headers=alice_headers,
        )
        assert cancelled.status_code == 200, cancelled.text
        await asyncio.sleep(0.5)
        cancelled_task = await wait_terminal(client, slow_id, alice_headers)
        assert cancelled_task["status"] == "CANCELLED"
        evidence["checks"]["cancelledStatus"] = cancelled_task["status"]

        dag_id = evidence["tasks"]["agent.dag"]["taskId"]
        sse_lines = await capture_sse(client, dag_id, alice_headers)
        ids = [
            int(line.removeprefix("id:").strip()) for line in sse_lines if line.startswith("id:")
        ]
        assert ids == sorted(set(ids))
        assert ids
        resumed = await capture_sse(
            client,
            dag_id,
            alice_headers,
            last_event_id=str(ids[0]),
        )
        resumed_ids = [
            int(line.removeprefix("id:").strip()) for line in resumed if line.startswith("id:")
        ]
        assert all(item > ids[0] for item in resumed_ids)
        evidence["checks"]["sse"] = {
            "eventIds": ids,
            "resumedAfter": ids[0],
            "resumedEventIds": resumed_ids,
            "monotonic": True,
        }

    OUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "checks": len(evidence["checks"]),
                "tasks": len(evidence["tasks"]),
                "evidence": OUT.name,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
