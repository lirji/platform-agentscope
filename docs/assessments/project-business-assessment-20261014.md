# AgentScope 项目优势、不足与业务接入评估

## 1. 评估范围与结论

- 日期：2026-10-14；源码基线：`ead0013ce1741822ae57a289f6fa7a79e36a7208`。
- 对象：本仓库的 AgentScope 编排服务及 Java 接入边界，不是对上游 AgentScope 框架的通用排名。
- 方法：源码、配置、测试、部署和发布记录交叉核对；139 项聚焦测试；两项本地替身复现。未调用付费模型、未操作真实业务数据、未重新部署。
- 本文记录现有能力、发现的问题及建设建议，不表示建议已经修复、实现或获准实施。

**总体判断：项目已具备较扎实的 Agent 执行治理能力，业务闭环和生产验收仍是主要短板。** Python 负责规划、推理和工具编排，Java 保留权威业务数据与领域规则，职责划分合理。当前更适合作为受治理的企业 AI 执行层，完整业务产品仍需围绕具体场景建设。

必须区分“源码已实现”“部署已启用”“真实业务已验收”。节点恢复已有实现，但最新本机部署记录的恢复开关仍为 false；生产发布声明仍是 NO-GO。依据：[恢复指南](../dag-recovery.md)、[部署记录](../delivery/docker-dag-diagnostics-20261014/DEPLOYMENT_RESULT.md)、[生产发布手册](../operations/production-release-runbook.md)。

## 2. 项目优势

| 优势 | 源码或验证证据 | 实际价值与边界 |
| --- | --- | --- |
| Python/Java 边界清晰 | [领域边界 ADR](../adr/0002-ai-runtime-domain-boundaries.md)、[架构边界测试](../../tests/test_architecture_boundaries.py) | AgentScope 类型隔离在适配器，业务通过中立契约调用 Java，避免双重维护订单、知识和流程规则。 |
| DAG 执行可靠性已有实现 | [依赖调度](../../src/agentscope_platform/application/dag_scheduler.py)、[预算](../../src/agentscope_platform/application/dag_budget.py)、[检查点恢复](../../src/agentscope_platform/application/dag_recovery.py) | 具备并发上限、整体预算、失败传播、身份/版本绑定和租约校验；恢复时工具节点重新执行，以重新授权和读取当前数据。 |
| 内置退款发起治理较完整 | [受治理工具](../../src/agentscope_platform/infrastructure/agentscope/governed_tools.py)、[确认服务](../../src/agentscope_platform/application/confirmation.py) | 精确参数确认、幂等键和防重放；响应丢失后查询原回执。发起退款流程不等于实际退款完成。 |
| 诊断与质量工程较完整 | [DAG 诊断](../dag-diagnostics.md)、[CI 配置](../../.github/workflows/ci.yml)、[评测版本化](../evaluation-versioning.md) | 能观察模型角色、排队/执行耗时、Token 和估算费用；具有契约、边界、影子评测及供应链检查。诊断不充当业务审计或财务账本。 |

评估基线的 [CI 38579017606](https://github.com/lirji/platform-agentscope/actions/runs/38579017606) 已通过。这证明该提交通过既有 CI，不能替代生产环境和真实业务质量验收。

## 3. 不足与风险

### R01：MCP 写工具安全约束可被配置弱化，优先处理

`ToolMetadata` 只要求写工具声明非 none 的副作用等级，未强制要求确认和幂等；`ToolPolicy` 按声明决定是否检查。因此，`readOnly=false`、`sideEffect=high` 的工具可同时配置 `requiresConfirmation=never`、`idempotency=none`，通过配置校验并被调用。

本地替身复现中，调用方具有 agent scope，但没有确认 grant 和幂等键，替身仍被调用一次。证据：[工具策略](../../src/agentscope_platform/domain/tool.py)、[MCP 绑定](../../src/agentscope_platform/domain/mcp.py)、[工具入口](../../src/agentscope_platform/infrastructure/agentscope/tools.py)。

这是启用 MCP 后的管理员误配风险，不表示模型能修改服务端配置，也不表示默认关闭 MCP 时已暴露外部写操作。建议为有副作用 MCP 工具落实必要的服务端确认和幂等约束；若业务确需自动写入，应明确允许的风险等级和独立授权策略。

### R02：可恢复长任务与业务写操作尚未打通

持久化 api/worker 模式拒绝启用退款发起、MCP、浏览器或代码执行。该限制保持了现有恢复语义的安全边界，但“具备 DAG 恢复”不能推导为“能恢复跨系统业务办理”。证据：[配置校验](../../src/agentscope_platform/core/config.py)、[只读 Worker](../../src/agentscope_platform/infrastructure/async_worker.py)、[部署覆盖配置](../../compose.readonly-worker.yml)。

若确有长时间写任务，应定义操作意图、确认有效期、业务幂等、未知结果查询、恢复时权限复核、补偿与人工处置，不应直接放开开关。

### R03：执行完成与业务成功需要更明确地区分

- Critic 的主要输入是问题、答案和评估时间，评分并不独立核验权威业务事实。`acceptedByThreshold` 是模型评审结果，不是业务正确性证明。证据：[Reviewer](../../src/agentscope_platform/infrastructure/agentscope/reviewer.py)、[DAG 接受条件](../../src/agentscope_platform/application/dag.py)。
- `analytics_sql` 在 Java 返回 `guardBlocked=true` 时仍使用普通文本 ToolChunk，未表达为 ERROR；复现状态为 `running`，文本会如实告知被拦截。问题是缺少机器可判定的业务结果，不是已绕过护栏或伪造查询数据。证据：[只读工具](../../src/agentscope_platform/infrastructure/agentscope/readonly_tools.py)。
- 历史本地语义/成本评测的候选 12 次运行通过，但只对订单样例有确定性事实断言；历史开放回答评测的候选 6 次运行虽然完成，Judge 通过数为 0。两份均为 2026-07-27 本地模型证据，不能当作当前版本质量分数。依据：[语义/成本记录](../delivery/phase-1-semantic-cost-gate/LIVE_VALIDATION.md)、[开放回答记录](../delivery/phase-1-open-answer-judge/LIVE_VALIDATION.md)。

建议明确区分查询成功、无数据、被拦截、依赖失败、待审批和实际办结；为目标业务建立有权威事实的案例集，分别统计执行完成率与业务成功率。

### R04：配额与费用治理存在范围和启用限制

DAG 并发控制通过进程内 semaphore 实现，不是跨副本全局租户配额；共享 Token 预算默认关闭。诊断费用依赖明确配置的价格，是估算而非提供商账单。证据：[调度容量](../../src/agentscope_platform/application/dag_scheduler.py)、[配置默认值](../../src/agentscope_platform/core/config.py)、[费用口径](../dag-diagnostics.md)。

多副本、多租户运营前，应核对共享预算启用状态，验证整体资源公平性和成本上限，并明确嵌入、重排和外部工具等费用的计量归属。没有规模需求时不预先引入一套新平台。

### R05：Session 定位是同一目标的断点续跑

恢复时校验目标摘要一致，持久化的是有界、脱敏的已完成步骤和执行状态。它不能直接替代客服跨会话记忆、客户画像或持续业务跟进。证据：[Session 服务](../../src/agentscope_platform/application/session.py)、[会话说明](../agent-sessions-and-capabilities.md)。

长期上下文应明确权威系统、授权、有效期、更新和删除机制，优先引用现有 Java 业务事实，避免复制第二份客户数据。

### R06：生产验收尚未闭环

最新本机部署验证包含真实中央任务库与 SSE，但诊断 usage 为合成数据，模型调用数为 0；节点恢复 false、价格确认 false。生产证据模板仍有 IAM、恢复、容量、峰值周期、业务评测和灰度等待完成项，项目声明维持 NO-GO。

依据：[部署结果](../delivery/docker-dag-diagnostics-20261014/DEPLOYMENT_RESULT.md)、[脱敏运行证据](../delivery/docker-dag-diagnostics-20261014/RUNTIME_EVIDENCE.json)、[生产证据模板](../operations/production-evidence-template.json)。这些是已有记录，本次未重新核验运行实例或生产环境。

## 4. 现有业务接入与候选建设方向

| 方向 | 已有基础 | 主要缺口与建议 | 建议验收指标 |
| --- | --- | --- | --- |
| 订单售后助手，优先 | 订单查询、政策检索、流程状态、受治理退款发起 | 补客户与订单归属校验、售后资格规则、物流查询、审批和实际退款结果回执；规则与实际写入仍由 Java/业务系统承担。 | 事实正确率、重复办理数、人工接管率、结果可追踪率。 |
| 企业知识/IT 服务台，优先 | RAG、规划、流程查询 | 补员工身份映射、文档权限、真实工单创建、转人工和结果回流；先做查询、诊断及工单草稿。 | 有出处回答比例、权限误放行数、工单有效率、解决率。 |
| 经营分析助手，有前置条件 | Schema 探索、NL2SQL、Analyst DAG | 先修复 Java SQL 护栏，再明确指标口径、数据时点、可核验结果和业务评测集。 | 租户隔离用例、指标一致率、查询成功率、耗时和单次成本。 |
| 采购/招投标材料助手 | 多任务 DAG、检索、综合与评审 | 接材料库，输出带出处的条款对照、缺项清单和风险提示；补版本、权限和人工复核。 | 条款召回率、引用准确率、漏项率、人工修订量。 |
| 销售/客户成功助手 | 只读工具与 MCP 扩展入口 | 接 CRM、服务记录、订单和产品知识；先做会前准备、客户摘要和跟进草稿，再考虑受治理写回。 | 摘要事实正确率、数据新鲜度、草稿采纳率、越权读取数。 |

以上是根据现有代码提出的候选方向，不表示 CRM、工单、物流或采购系统已经接入。指标是建议采集项，不是实测结果或达标承诺。

Java 侧 SQL 护栏和业务授权问题见关联仓库的[项目评估报告](https://github.com/lirji/langchain4j-platform/blob/348c13e0012fc36e40c9ad87942fb519b27311e6/docs/平台工程/项目优势不足与业务接入评估-20261014.md)。Python 适配器不能消除下游领域服务的安全缺口。

## 5. 建议演进顺序

1. **先补接入底线**：落实 MCP 写工具约束、明确业务结果状态、修复下游 SQL 护栏；以误配、未确认、缺幂等、被拦截和跨租户场景验收。
2. **再完成一个业务闭环**：优先订单售后或企业服务台，接入权威数据，建立可重复案例集，衡量办理成功率、人工接管率和单次成本。
3. **按真实需求扩展运行能力**：需要时再补可恢复写操作、跨副本配额和长期上下文治理，并完成生产门禁证据。

暂不建议仅增加 Agent 模式数量、继续拆服务，或在上述边界未补齐时开展自主资金操作。优先证明一个端到端场景的收益和失败恢复能力。

## 6. 可复现证据与验证边界

### 聚焦测试

评估时以下命令退出码 0，共 139 项通过，覆盖工具策略、确认、只读工具、恢复、调度、租约、JWT、执行限制、Session 和诊断。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_tools.py tests/test_governed_tools.py tests/test_tool_confirmation.py \
  tests/test_readonly_tools.py tests/test_dag_recovery.py tests/test_dag_optimization.py \
  tests/test_dag_scheduling.py tests/test_durable_worker.py tests/test_config.py \
  tests/test_internal_jwt.py tests/test_execution_limits.py \
  tests/test_agent_session_service.py tests/test_dag_diagnostics.py
```

### R01/R03 本地替身复现

在仓库根目录使用已有 `.venv` 执行。配置不读取 `.env`，MCP 使用内存替身，HTTP 使用 MockTransport，不访问外部服务；重复字符只是本地测试凭据。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import asyncio
import json
import httpx
from agentscope_platform.core.config import Settings
from agentscope_platform.core.context import bind_run_context, reset_run_context
from agentscope_platform.domain.agent import RunContext, TenantIdentity
from agentscope_platform.infrastructure.agentscope.governed_tools import GovernedToolset
from agentscope_platform.infrastructure.agentscope.readonly_tools import ReadonlyToolset
from agentscope_platform.infrastructure.http.platform_client import PlatformClient

class FakeGateway:
    calls = 0
    async def call(self, **kwargs):
        self.calls += 1
        return 'stub result; no external action'

async def main():
    binding = {'serverId': 'review', 'remoteName': 'record_update', 'description': 'Local policy assessment stub', 'metadata': {'name': 'mcp_review_record_update', 'readOnly': False, 'sideEffect': 'high', 'idempotency': 'none', 'requiresConfirmation': 'never', 'requiredScopes': ['agent'], 'timeoutSeconds': 4, 'retryPolicy': 'none'}}
    settings = Settings(_env_file=None, agent_mcp_enabled=True, agent_mcp_url='https://assessment.invalid/mcp', agent_mcp_tools_json=json.dumps([binding]), agent_confirmation_secret='c'*32, agent_downstream_jwt_secret='d'*32)
    gateway = FakeGateway()
    client = PlatformClient(settings, httpx.MockTransport(lambda request: httpx.Response(200, json={'guardBlocked': True, 'rows': [], 'rowCount': 0})))
    context = RunContext(TenantIdentity('assessment', 'reviewer', frozenset({'agent'})), None, 'local-policy-assessment')
    token = bind_run_context(context)
    try:
        tool = GovernedToolset(settings, client, mcp_gateway=gateway).tools()[0]
        result = await tool.call(arguments={'value': 'test'})
        print(json.dumps({'case': 'high_risk_mcp_write_without_grant_or_idempotency', 'configurationAccepted': True, 'providerStubCalls': gateway.calls, 'toolState': str(result.state)}, ensure_ascii=False))
        sql = await ReadonlyToolset(settings, client).analytics_sql('test query')
        print(json.dumps({'case': 'analytics_guard_blocked', 'toolState': str(sql.state), 'message': sql.content[0].text}, ensure_ascii=False))
    finally:
        reset_run_context(token)
        await client.close()

asyncio.run(main())
PY
```

实际输出：

```json
{"case": "high_risk_mcp_write_without_grant_or_idempotency", "configurationAccepted": true, "providerStubCalls": 1, "toolState": "running"}
{"case": "analytics_guard_blocked", "toolState": "running", "message": "查询被安全护栏拦截，未执行。请换一个只读、限定本租户数据的问法。"}
```

这两项复现确认本地配置与适配器行为，不证明真实 provider 已发生副作用，不构成数据库泄漏或生产事故证据。本文不包含吞吐压测、提供商账单核对或最新模型业务质量实测。

### 文档落盘验证

本次仅修改本文、README 和根进度文档，产品源码仍为上述评估基线。按仓库提交要求完成：

- 本文与 README 的 62 个本地文档链接均有效，入口及进度引用有效。
- 直接提取本文复现代码执行，两项 JSON 输出与记录一致。
- `uv run --frozen --offline ruff check .`：通过。
- `uv run --frozen --offline mypy src`：107 个源文件通过。
- `uv run --frozen --offline pytest -o addopts='' -q -p no:cacheprovider`：616 项通过，1 条既有 Starlette/httpx 弃用警告；未做依赖升级。
- `git diff --check`：通过。

上述测试通过不表示 R01–R06 已修复；风险复现与既有测试同时通过，说明现有验收范围仍有需要补充之处。
