#!/usr/bin/env python3
import asyncio
import json
from pathlib import Path

import httpx

from agentscope_platform.evaluation.judge import JudgeRequest, JudgeResult
from agentscope_platform.evaluation.shadow import (
    Target,
    evaluate_shadow,
    load_cases,
)

ROOT = Path(__file__).resolve().parents[1]


class OfflineJudge:
    async def score(self, request: JudgeRequest) -> JudgeResult:
        if not request.criteria or not request.answer:
            raise AssertionError("judge received an empty contract")
        return JudgeResult(score=1)


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
    final_answer = (
        "订单 101, 金额 1200.00, 状态已支付, 客户张三, 下单日期 2026-05-03"
        if "订单 101" in goal
        else "offline smoke"
    )
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
            "finalAnswer": final_answer,
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
        judge=OfflineJudge(),
    )
    if not report.gate.passed:
        raise SystemExit("\n".join(report.gate.regressions))
    print(f"shadow smoke passed: {len(report.samples)} samples")


if __name__ == "__main__":
    asyncio.run(run())
