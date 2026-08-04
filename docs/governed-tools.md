# 受治理工具运行手册

## 当前范围

Phase 4 当前包含 `refund_start`、allowlist-only MCP、远端 Browser 和远端 Code Sandbox。
退款工具只负责调用 Java `workflow-service` 发起退款流程，不会认领、批准、驳回、完成或
删除工作流。Java 继续拥有 Flowable、事务、人工审批和 outbox。

所有受治理工具默认关闭。`refund_start` 的启用开关是：

```bash
AGENT_REFUND_START_ENABLED=true
```

仅打开开关不会授权执行。每次请求还必须同时满足：

1. 已验证内部 JWT 包含 `agent` scope；
2. `Idempotency-Key` 是 1～128 字符的安全业务键；
3. 客户端先调用 `/agent/tool-confirmations`，对精确工具名和规范化 JSON 参数申请短时签名 grant；
4. 执行请求通过 `X-Agent-Confirmation-Grants` 携带该 grant。

grant 同时绑定 tenant、user、tool、参数 SHA-256、幂等键、`iat/exp` 和 `jti`，默认 120 秒过期。
真正调用 provider 前原子消费 `jti`；参数变化、跨租户、跨用户、错误幂等键、过期、篡改或重放
都会 fail-closed。旧 `X-Agent-Confirmed-Tools` 只绑定工具名，现已明确返回 400，不再兼容。

任何写工具启用时必须设置与内部 JWT 分离的 `AGENT_CONFIRMATION_SECRET`（至少 32 bytes）。
本地测试可使用 `AGENT_CONFIRMATION_REPLAY_STORE=memory`；生产开启写工具时配置校验强制使用：

```bash
AGENT_CONFIRMATION_REPLAY_STORE=redis
AGENT_CONFIRMATION_REDIS_URL=rediss://redis.example.test:6379/0
```

MCP、Browser 或 Code 任一外部 provider 开启时，还必须配置第三把独立密钥：

```bash
AGENT_DOWNSTREAM_JWT_SECRET=<at-least-32-bytes-and-not-reused>
```

orchestrator 不转发入口 `X-Internal-Token`。它为每次 provider 调用签发最长 60 秒的
`X-Agent-Service-Token`，只带受限 `agent.tool.invoke` scope，并绑定 provider audience、tenant、
actor、具体 action、`token_use=agent_downstream` 和 `jti/iat/exp`。MCP、Browser、Code provider
必须分别校验 `mcp-provider`、`browser-sandbox`、`code-sandbox` audience 及 JOSE `kid`；错 audience
或把该 token 送回平台业务 API 都必须拒绝。完整语言中立 claims 契约见
`contracts/boundaries/downstream-service-token-claims.schema.json`。

示例仅适用于本地或明确命名的测试环境：

```bash
curl -X POST http://localhost:8085/agent/tool-confirmations \
  -H "X-Internal-Token: ${INTERNAL_TOKEN}" \
  -H 'Idempotency-Key: refund-order-101-request-1' \
  -H 'Content-Type: application/json' \
  -d '{"toolName":"refund_start","arguments":{"message":"为订单 101 发起退款审批流程"}}'

# 从上一步 201 响应读取 grant；展示并确认的参数必须与执行时工具参数完全一致。
curl -X POST http://localhost:8085/agent/process/run \
  -H "X-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-Agent-Confirmation-Grants: ${CONFIRMATION_GRANT}" \
  -H 'Idempotency-Key: refund-order-101-request-1' \
  -H 'Content-Type: application/json' \
  -d '{"goal":"为订单 101 发起退款审批流程"}'
```

签名 grant 和幂等键来自 HTTP 请求上下文，不是 Agent 工具参数；模型不能自行设置或覆盖。
Python 调 Java 时只发送 `message/chatId/dedupeId`，租户、用户和 trace 继续通过已验证内部
token 与 trace header 传播。

## 状态语义

- `COMPLETED`：Java 工作流判定低风险并自动受理。
- `WAITING_APPROVAL`：只表示已经创建人工审批任务，不表示退款已批准。
- `deduplicated=true`：Java 返回同一业务键对应的既有流程，没有再次发起。

AgentScope 客户端不自动重试 `refund_start`。Java 将 `dedupeId` 写入 `WF_IDEMPOTENCY` 权威账本，
由数据库唯一约束串行化并发请求，并让 claim、Flowable 实例创建和实例绑定参加同一事务：同键同参数
返回原实例，同键改参数返回 409，创建失败不占用键，跨租户键空间独立。这里保证的是 workflow-service
接收边界的强幂等；不把后续外部支付系统描述成 exactly-once，真正退款执行仍需支付方自己的幂等键。

## MCP 配置与边界

MCP 只支持远端 Streamable HTTP，禁止 stdio、本地子进程和未经配置的动态工具。启用时 URL
和非空工具 allowlist 缺一不可：

```bash
AGENT_MCP_ENABLED=true
AGENT_MCP_URL=https://mcp.test.example/mcp
AGENT_MCP_TOOLS_JSON='[{"serverId":"weather","remoteName":"get_weather","description":"读取天气","metadata":{"name":"mcp_weather_get_weather","readOnly":true,"sideEffect":"none","idempotency":"none","requiresConfirmation":"never","requiredScopes":["agent"],"timeoutSeconds":5,"retryPolicy":"none"}}]'
```

本地工具名必须以 `mcp_<serverId>_` 开头。远端名、描述和完整 Tool Policy 都由运维配置固定；
不会把远端 discovery 结果自动交给模型。`platform.agent.*` 会在配置加载时拒绝，避免经 Java
interop 再调用 AgentScope 形成递归。

只读 MCP 工具可按 scope 自动执行；有副作用的 MCP 工具必须声明副作用等级、确认要求和
幂等策略，并通过签名 grant 确认本地工具名及完整 FunctionTool 参数（MCP 形态为
`{"arguments": {...}}`）。调用只发送配置中的远端
工具名和模型参数，可信身份、trace、确认和幂等键由请求上下文控制；模型参数若包含
tenant/user/token/trace/confirmation/idempotency 覆盖字段会在本地拒绝。

出站时专用服务令牌与 trace 使用 HTTP header；幂等键仅放入实际 `tools/call` 的 MCP `_meta`，
不会附着到 `initialize` 握手。确认只在本地策略中消费，不会作为可伪造参数发送给 provider。

默认参数上限 65536 bytes、文本结果上限 32768 字符；每项工具独立声明最长 300 秒超时。
当前实现每次只执行一次 `tools/call`，不会自动重试写工具。服务端错误统一脱敏为稳定错误。

## 远端 Browser 与 Code Sandbox

两类能力都默认关闭，且 URL 为空时即使误开开关也会启动失败：

```bash
AGENT_BROWSER_ENABLED=true
AGENT_BROWSER_SANDBOX_URL=https://browser-sandbox.test.example
AGENT_BROWSER_ALLOWED_HOSTS_JSON='["docs.example.com"]'

AGENT_CODE_EXEC_ENABLED=true
AGENT_CODE_SANDBOX_URL=https://code-sandbox.test.example
```

Browser 暴露 `browser_open/click/click_xy/type/screenshot/see`。open/click/type 等可能触发网络
或页面副作用的工具都要求显式确认与幂等键；screenshot/see 只读。URL 只允许 HTTP(S)、禁止
内嵌凭据并必须精确命中 host allowlist。allowlist 会随每个动作传给 sandbox，provider 必须对
导航、重定向和子资源继续执行 DNS/egress 策略；返回 URL 越界会被 orchestrator 拒绝。

每次 Agent run 使用由 tenant/user/幂等键哈希得到的不透明 session ID，不把原始身份放进
JSON；只读请求没有幂等键时才使用 trace。每个动作使用跨重试稳定的不透明 operation ID；run
结束后调用远端 session DELETE，清理失败只记录低敏错误，不改变 Agent 主结果。provider 还必须
配置 TTL，处理客户端异常退出。

`code_exec` 保持旧能力的 Java 片段语义，但只调用 `/v1/code/execute`。请求强制
`networkEnabled=false`、`workspace=ephemeral`，并传入 wall-clock timeout、源码/输出、内存和
进程上限。sandbox provider 必须拒绝不能满足这些约束的请求。orchestrator 不包含 subprocess、
JShell、Docker、Playwright 或 Selenium 执行路径，也不会在远端失败时本地重试。

Browser/Code provider 的语言中立契约位于 `contracts/boundaries/browser-*.schema.json` 和
`code-execution-*.schema.json`。当前仓库只交付 client contract 与离线 stub；在一个明确命名、
可弃的 sandbox 环境通过逃逸、DNS rebinding、重定向、资源耗尽和 TTL 测试前，不得生产启用。

## 灰度与监控

1. 先保持开关关闭发布策略代码，确认只读回归无变化。
2. 在本地 stub 验证缺 scope、缺确认、缺幂等键、provider 4xx/5xx、超时和重复键。
3. MCP 先只配置一个只读工具，核对远端审计中的 tenant、trace、工具名和参数上限。
4. 仅为测试租户开启，执行旧/新评测用例并检查 workflow 实例数或 MCP provider 调用数。
5. 观察工具调用、policy denied、provider 失败、P95 延迟、重复实例率和 MCP 超时率。
6. Browser/Code 先做 provider 隔离与逃逸测试，再为单一测试租户、单一 host/language 开 canary。
7. 生产启用仍需要独立 canary、监控阈值、值班人与变更批准。

低基数计数器为 `agent_tool_policy_denials_total{tool,reason}` 与
`agent_tool_provider_failures_total{tool,provider}`。标签中不放 tenant、user、URL、参数、源码或
token；具体租户排障通过已有 trace 和结构化 run 日志关联。

## 回滚

能力级回滚：设置 `AGENT_REFUND_START_ENABLED=false` 并滚动重启 orchestrator。已创建的 Java
流程继续由 workflow-service 正常处理，不能通过关闭 Agent 工具撤销。

MCP 能力级回滚：设置 `AGENT_MCP_ENABLED=false` 并滚动重启；也可从
`AGENT_MCP_TOOLS_JSON` 移除单个工具后重启。已完成的远端副作用不会因移除工具而撤销，
不得在回滚时重放请求。

Browser/Code 分别通过 `AGENT_BROWSER_ENABLED=false`、`AGENT_CODE_EXEC_ENABLED=false`
回滚并滚动重启。Browser provider 中残留 session 由 DELETE/TTL 清理；已发生的页面外部副作用
不能撤销。Code job 关闭入口后不得自动转到本地执行。

如果 Agent 主链出现广泛回归，按整服务回滚手册把路由切回保留的 Java `agent-service`。
已经成功发起的流程不得通过静默重试或路由回切再次执行。
