# 跨运行时可靠性整改

本会话按 Claude Engineering Skill 的测试保护、纵向切片、验证和复审流程执行。
规范计划与聚合状态在同级 langchain4j-platform 的
`docs/delivery/cross-runtime-reliability/DELIVERY_PLAN.md`、`DELIVERY_STATUS.md`。
Java 保持业务/任务/预算数据权威，AgentScope 保持推理与编排，生产部署单独验收。

## S1 RAG 租户边界

Java RAG 回填验签租户。Python 工具只接受与当前运行一致且非空的 tenantId；缺失/null/空值
无法证明片段归属，直接返回工具错误，不将命中内容交给模型。不修改协议或正常匹配行为。
旧代码新增三个用例全部失败；修复后工具 11 项、全量 483 项通过，ruff/format/mypy 通过。

历史 ESS run 的阻塞状态保留；本轮采用用户后续明确授权的交互式实施，不伪造历史 run 成功。

## S3 共用预算

所有模型工厂调用（含 planner/reviewer/analytics/text/stream）经 Java authority 预留与结算。
专用 service JWT 绑定租户、用户、操作和额度，不授予普通用户签名权限。
仅完整且已完成的 usage 结算；中断、取消或缺失 usage 保持预留。
模型调用禁止应用层重试，RPC 仅重试原操作。提供商 token 估算可能超额，实际 usage 仍全量记录。
配置默认关闭，需要与 Java 同时启用并注入独立服务凭据；schema/HTTP 组合固定由后续契约门禁落实。
细节、开启/回滚和本地验证见规范目录 S3_SHARED_BUDGET.md。
聚焦 38 项、全量 492 项、ruff/format/mypy、Compose 静态校验通过；未调用真实模型。

## S5：退款回执

发起请求结果未知时，仅按原用户、租户、幂等键和原诉求读取 `/workflow/refund/receipt`，
不重放写操作。`refund_receipt` 是无确认消费的只读工具；未读到回执显示结果未确认，
新发起仍需新有效确认。聚焦 9 项、全量 494 项通过，Java 真 MySQL Flowable 验证通过。

## S6：独立只读 worker

默认 inline；可选 api/worker 角色由 `compose.readonly-worker.yml` 启用。
先执行 Java async-task V3 迁移并开启 dispatch。`ASYNC_TASK_WORKER_ID` 与
Java `ASYNC_TASK_DISPATCH_SERVICE_ID` 一致；两进程使用相同不可变 runtime revision、配置和版本。
生产要求 `ASYNC_TASK_RUNTIME_REVISION=git:<40hex>` 或 `sha256:<64hex>`。
worker 入口 `python -m agentscope_platform.worker`，不监听HTTP；`--health` 检查成功领取轮询的时效。
API 不执行 request 闭包；新 worker 按持久化输入重建，禁用所有外部/写工具，拒绝旧确认 grant。
崩溃恢复可重复只读调用/模型费用；Java epoch 阻止旧写回，预算仍逐模型调用预留。
完整 507 项、mypy/Ruff、真实 MySQL 和独立进程恢复/DAG/假OpenAI验证通过。
完整设计、队列与租户配额、回滚及外部生产限制见 Java 规范 S6_DURABLE_WORKER.md。
