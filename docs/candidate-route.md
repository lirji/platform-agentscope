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

旧平台 edge 当前支持的第一条透明切片是：

- 客户端仍请求 `POST /agent/run`；
- edge 只使用已经验签/换发的内部 JWT tenant，不接受客户端 tenant header 决策；
- `EDGE_AGENT_CANARY_ENABLED=true`、`EDGE_AGENT_CANARY_TENANTS` 精确命中时，把下游
  改写为候选 `POST /agent/v2/run`；
- 其他方法、Agent 路径和租户继续使用 Java `AGENT_URI`。

本地 Compose 中候选运行在宿主机时可配置：

```bash
export EDGE_AGENT_CANARY_ENABLED=true
export EDGE_AGENT_CANARY_URI=http://host.docker.internal:18085
export EDGE_AGENT_CANARY_TENANTS=acme
```

完整配置、安全边界、监控与回滚手册位于旧平台仓库
`docs/Agent编排/agentscope-edge-canary.md`。

## 回滚顺序

1. 在 edge/facade 将测试租户路由恢复到旧 `agent-service`。
2. 确认旧服务健康且测试请求成功。
3. 设置 `AGENT_V2_ENABLED=false`，重启候选服务。
4. 确认 readiness 中 `candidateRoute=DISABLED`。
5. 确认 `POST /agent/v2/run` 返回 404，旧服务请求仍成功。

先恢复 edge 再关闭候选入口，可避免在重启窗口内产生 404。该开关是启动时配置，变更后
必须重启服务。

## 2026-07-29 本地 edge 演练结果

- Chrome 使用 `alice/acme` Casdoor Bearer，经旧平台 edge 原路径 `POST /agent/run`；
- 灰度开启时返回 HTTP 200、`DONE`、`tenantId=acme`，候选日志确认实际收到
  `POST /agent/v2/run` 并执行 `current_time`；
- 关闭 edge 灰度并重启后，同一页面/身份/请求继续返回 HTTP 200，Java
  `agent-service` 审计日志确认接管新 trace；
- 临时候选随后关闭，常驻候选保持 `candidateRoute=DISABLED`。

这证明本地测试租户可逆切换，不代表生产扩量或全量切流获批。

## 本地无模型路由演练

API 测试使用内存 Runner 验证默认关闭、开启后的认证/契约/租户传播以及关闭后的 404：

```bash
uv run pytest tests/test_api.py
```

这只证明候选服务侧可逆，不替代测试环境 edge 的按租户切流和回滚演练。
