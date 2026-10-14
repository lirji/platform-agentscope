"""本地旧模式/优化模式对照不替代运行中 Java/Python 的真实双跑。"""

from pathlib import Path

import httpx

from agentscope_platform.api.app import create_app
from agentscope_platform.evaluation.dag_shadow import evaluate_dag_shadow, load_dag_cases
from agentscope_platform.evaluation.shadow import Target
from test_api import FakeRunner, internal_token, settings
from test_dag_optimization import Synthesis


async def test_actual_http_modes_pass_same_readonly_shadow_contract():
    cases = load_dag_cases(Path("eval/baseline/dag-optimization-cases.jsonl"))
    legacy = create_app(settings(), FakeRunner())
    optimized = create_app(
        settings(agent_dag_optimization_enabled=True), FakeRunner(), text_generator=Synthesis()
    )
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=legacy), base_url="http://legacy.localhost"
        ) as old_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=optimized), base_url="http://candidate.localhost"
        ) as new_client,
    ):

        async def route(request):
            client = old_client if request.url.host == "legacy.localhost" else new_client
            return await client.post(
                request.url.path, content=request.content, headers=request.headers
            )

        report = await evaluate_dag_shadow(
            cases,
            Target("legacy", "http://legacy.localhost", auth_token=internal_token()),
            Target("candidate", "http://candidate.localhost", auth_token=internal_token()),
            transport=httpx.MockTransport(route),
            suite_name="dag-optimization-offline",
        )
    assert report.passed
    assert len(report.samples) == 6
