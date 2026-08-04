# Agent 会话检查点与能力注册

## 稳定契约

`POST /agent/sessions/{sessionId}/run` 创建或恢复一次可续跑执行；`GET
/agent/sessions/{sessionId}` 读取检查点。两者均要求有效 `X-Internal-Token`，且记录按
`tenantId + userId` 授权，越权访问统一返回 404。`sessionId` 必须匹配
`sess-[a-f0-9]{32}`。

检查点使用 `agent-session-checkpoint.v1`，只保存目标 SHA-256、脱敏且有界的已完成工具步骤、
最终文本、状态、revision、TTL 与租约。不会保存原始 goal、caller token、confirmation grant、
模型上下文或 AgentScope state。AgentScope 的 `AgentState` 只在
`infrastructure/agentscope/` 内由稳定步骤摘要重建。

生产必须配置：

```text
AGENT_SESSION_STORE=redis
AGENT_SESSION_REDIS_URL=rediss://redis.example.test/0
```

Redis 写入以 revision CAS 和短租约防止多副本丢更新；每个完整工具结果边界都会续租并保存。
进程崩溃后，租约过期即可由另一副本恢复。目标文本必须由调用方重传且摘要相同。

发生过副作用的暂停会话，只能用原幂等键和新签发的一次性 confirmation grant 恢复；旧 grant
不会持久化或复用。终态会话重复提交只读取既有结果，不重新执行。

## 能力注册

`GET /agent/capabilities/registry` 返回 `agent-capability-registry.v1`、能力描述符和规范 JSON 的
SHA-256 revision，并用相同 revision 作为 ETag。提交快照位于
`contracts/capabilities/agent-capabilities.v1.json`。

旧 `GET /agent/capabilities` 继续逐字返回原四项 descriptor；session run/get 只加入版本化
registry，避免破坏旧消费者。Java interop 读取版本化 registry，并把校验通过的 LKG 持久化到
Redis。

## 回滚

回滚 API 时先让 Java interop 停止消费新 registry，再切回旧 AgentScope 镜像。不要删除 Redis
记录；旧版本会忽略命名空间，新版本恢复后仍可读取未过期检查点。若必须停止恢复，保留 GET，
先拒绝新的 session run，等待运行租约和任务终止后再缩容。
