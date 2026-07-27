# Phase 2 Sibling Orchestrators 同步切片

## 授权与范围

用户要求持续迁移 Phase 2。本切片迁移三个无业务写副作用的同步编排器：

- `POST /agent/chain`
- `POST /agent/vote`
- `POST /agent/reflexive`

保留预定义 Prompt Chain、Voting 同题并行和 Reflexion 纵向改进三种不同语义。同步文本模型
通过应用端口隔离，不开放工具；Reflexion 复用已迁 Critic。

暂不迁移 `/agent/reflexive/stream`、异步任务和 Process。

## 实现结果

- 新增共享纯文本生成端口与 AgentScope 适配器，普通生成和确定性聚合使用独立 temperature。
- Chain 固化服务端步骤，完整实现长度、包含和正则 gate。
- Voting 实现进程级有界并发、稳定 majority 和确定性 synthesis。
- Reflexion 复用结构化 Critic 与共享加权评分函数，保留旧最大改进次数语义。
- 新增 JSON Schema/OpenAPI 快照、只读 baseline、服务/API/适配器测试和部署配置。

## 验收标准

1. Chain 使用服务端预定义步骤，按顺序传递输出，确定性 gate 失败立即短路。
2. Voting 在调用模型前校验候选数，同一问题有界并发 N 次且上下文不串租户。
3. majority 保留 trim + 大小写无关计票、首个胜出票原文和 agreement 阈值。
4. synthesis 使用确定性聚合；非适用的 agreement 返回 JSON `null`，避免 NaN。
5. Reflexion 首答达标即停，低分最多改进配置次数，并返回逐轮评分。
6. 三个端点强制内部 JWT；模型错误统一脱敏 502，取消继续传播。
7. 不允许请求方自定义 Chain 指令或注入 tenant/token。

## 回滚

新端点仍不接 edge，旧服务保持生产权威。Chain 可通过清空服务端步骤禁用；其他端点停止
测试路由即可回滚。

## 验证证据

- Ruff lint/format 与 strict mypy 通过。
- 174 个测试通过，总代码覆盖率 92.37%。
- JSON Schema/OpenAPI `--check` 通过。
- Shadow smoke 8 个样本通过。
- wheel/sdist 构建与 `docker compose config` 通过。
