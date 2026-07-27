# `/agent/v2` 候选路由与回滚

候选服务提供一个默认关闭的 `POST /agent/v2/run` 入口，供 edge gateway 或旧
`agent-service` façade 做按租户、按能力灰度。该入口与 `/agent/run` 复用同一请求响应
契约、内部 JWT 验签、租户上下文和 AgentScope Runner。

## 启用前置条件

- Shadow 多轮结果达到批准阈值；
- 只允许只读工具；
- edge 仍保留旧 `agent-service` 路由和镜像；
- 使用测试租户，并有可观测的 trace 和工具调用记录。

## 启用候选入口

```bash
export AGENT_V2_ENABLED=true
docker compose up -d --build orchestrator
curl http://localhost:8085/readiness
```

`checks.candidateRoute` 必须为 `ENABLED`。随后使用短期
`X-Internal-Token` 请求 `POST /agent/v2/run`，确认响应 `tenantId` 和 `X-Trace-Id`
正确。不要把 token 写入命令历史、报告或仓库。

候选入口开启不等于 edge 已切流。edge/facade 应先只把批准的测试租户和只读能力转发到
该地址；未命中的请求继续使用旧 `agent-service`。

## 回滚顺序

1. 在 edge/facade 将测试租户路由恢复到旧 `agent-service`。
2. 确认旧服务健康且测试请求成功。
3. 设置 `AGENT_V2_ENABLED=false`，重启候选服务。
4. 确认 readiness 中 `candidateRoute=DISABLED`。
5. 确认 `POST /agent/v2/run` 返回 404，旧服务请求仍成功。

先恢复 edge 再关闭候选入口，可避免在重启窗口内产生 404。该开关是启动时配置，变更后
必须重启服务。

## 本地无模型路由演练

API 测试使用内存 Runner 验证默认关闭、开启后的认证/契约/租户传播以及关闭后的 404：

```bash
uv run pytest tests/test_api.py
```

这只证明候选服务侧可逆，不替代测试环境 edge 的按租户切流和回滚演练。
