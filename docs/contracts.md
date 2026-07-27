# 兼容契约

## 1. 原则

迁移阶段优先保持旧客户端可用。兼容对象由本项目定义，不能直接序列化 AgentScope 类型。

## 2. `/agent/run`

请求：

```json
{
  "goal": "查询知识库中的退款规则",
  "webhookUrl": null
}
```

同步响应：

```json
{
  "goal": "查询知识库中的退款规则",
  "steps": [],
  "finalAnswer": "……",
  "stopReason": "DONE",
  "depth": 0,
  "tenantId": "acme"
}
```

Phase 0 已保持字段名和基本形状，但 `steps` 尚未采集完整 AgentScope Event 轨迹。完成
Phase 1 前不能宣称与旧接口完全等价。

## 3. 停止原因

兼容值：

- `DONE`
- `MAX_STEPS`
- `LOOP`
- `TIMEOUT`
- `BUDGET`
- `CANCELLED`
- `ERROR`

AgentScope 的 finished reason 和异常必须在应用层映射，不把框架枚举直接暴露出去。

## 4. 认证

- Header：`X-Internal-Token`
- 算法：HS256 或 RS256
- `sub`：tenantId
- `uid`：userId
- `scopes`：字符串数组
- `dept`：可选部门
- `exp`：必需

无效或缺失 token 在认证开启时返回 401。`/health`、`/readiness`、`/info` 不要求业务身份。

Phase 0 的出站工具沿用经过验证的入口内部 token。后续如必须延长多跳调用窗口，应新增与
`platform-security` 一致的内部 token 签发端口，而不是静默使用 master secret。

## 5. Trace

- 接受 `X-Trace-Id`；缺失时生成。
- 响应回传 `X-Trace-Id`。
- 所有 HTTP/MCP 工具继续传播。
- 接入 OTel 后仍保留该兼容头，直至旧平台完成 W3C Trace Context 统一。

## 6. SSE 与异步契约

尚未实现。迁移时必须保持：

- 原任务 ID 和租户可见性规则。
- `PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED`。
- DAG 的 `dag-*` 事件名与事件顺序约束。
- Last-Event-ID/断点恢复能力。
- 取消后不得被迟到 worker 覆盖为成功。
- webhook 至少一次投递语义及幂等消费说明。

## 7. 契约资产计划

1. 从旧平台导出 OpenAPI。
2. 为旧 DTO 生成 JSON Schema 快照。
3. 增加旧服务 provider contract 和新服务 consumer/compatibility tests。
4. 每次变更比较 OpenAPI breaking changes。
5. 最终将语言中立契约发布为独立版本化制品。
