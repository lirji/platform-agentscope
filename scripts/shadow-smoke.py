#!/usr/bin/env python3
import asyncio
import json
from pathlib import Path

import httpx

from agentscope_platform.evaluation.shadow import (
    Target,
    evaluate_shadow,
    load_cases,
)

ROOT = Path(__file__).resolve().parents[1]


def handler(request: httpx.Request) -> httpx.Response:
    goal = json.loads(request.content)["goal"]
    if "退款审批规则" in goal:
        tools = ["rag_search"]
    elif "订单 101" in goal:
        tools = ["order_query"]
    elif "退款金额趋势" in goal:
        tools = ["schema_explore", "analytics_sql"]
    else:
        tools = ["current_time"]
    return httpx.Response(
        200,
        json={
            "goal": goal,
            "steps": [
                {
                    "n": index,
                    "thought": "",
                    "action": tool,
                    "actionInput": "",
                    "observation": "offline smoke",
                }
                for index, tool in enumerate(tools, start=1)
            ],
            "finalAnswer": "offline smoke",
            "stopReason": "DONE",
            "depth": 0,
            "tenantId": "smoke",
        },
    )


async def run() -> None:
    cases = load_cases(ROOT / "eval" / "baseline" / "readonly-cases.jsonl")
    report = await evaluate_shadow(
        cases,
        Target("legacy", "http://legacy.localhost"),
        Target("candidate", "http://candidate.localhost"),
        transport=httpx.MockTransport(handler),
        suite_name="readonly-offline-smoke",
    )
    if not report.gate.passed:
        raise SystemExit("\n".join(report.gate.regressions))
    print(f"shadow smoke passed: {len(report.samples)} samples")


if __name__ == "__main__":
    asyncio.run(run())
