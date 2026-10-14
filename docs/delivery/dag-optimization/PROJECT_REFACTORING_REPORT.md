# ProjectRefactoringReport：DAG 多步骤编排优化

## 结果与范围

在原有 DAG 服务内加入默认关闭的优化路径，解决失败传播、无工具汇总、依赖就绪调度、请求预算与只读结果复用。保留旧行为供双跑与回退；不引入新的基础设施、模型或依赖。计划/结果分别见 PLAN.md、RESULT.md。

## 基线与问题

基线 4c5f673：530 tests / Ruff / Mypy PASS。问题证据为 application/dag.py 的整层 gather、纯 final_answer 输入、runner 汇总及整图重跑；api/app.py 为通用/Process 分别实例化并发槽；model_factory 已有中央租户配额，故本次在它之前加请求级准入而非替代权威。

## 目标架构与改动

- application/dag.py 继续编排，scheduler 独立承担就绪队列、容量与取消收敛。
- domain/RunContext 携带服务端能力集合；ToolPolicy 与既有 scope/确认/幂等并行校验。
- dag_budget 传播请求预算和总截止时间；基础设施模型适配器实际调用前准入，未开启优化时保持既有行为。
- dag_reuse 仅持有当前请求重规划轮次结果；依赖执行版本和 TTL 控制失效，不成为持久权威。
- 独立 TextGenerator 汇总，Critic 使用证据，确定性执行失败门禁先行。

## 测试保护与验证

各批先补行为测试并观察失败，随后实现并运行聚焦回归；最终 569 tests，89.66% 覆盖率。验证包含 HTTP 契约/身份隔离、真实工具适配器拒绝、部分结果异步失败、非屏障调度、排队/运行事件、并发公平、取消/异常、模型边界预算、过期与跨请求复用拒绝。详细命令与限制见 RESULT.md。

## 行为兼容

| 面向 | 判定 | 说明 |
|---|---|---|
| HTTP/JSON schema | UNCHANGED | 未增加或移除字段，快照检查通过 |
| 旧同步执行 | UNCHANGED | 默认优化开关 false |
| 优化执行语义 | CHANGED | 明确 opt-in；失败依赖跳过、未知依赖拒绝、无工具汇总、能力限制、预算与新进度事件 |
| 异步终态 | CHANGED | 非 DONE 综合结果不再记录 SUCCEEDED；独立正确性修复 |
| DB/MQ | NOT_APPLICABLE | 无表、迁移、队列或消息结构变更 |
| 外部业务调用 | CHANGED | 优化通用 DAG 只允许内置只读工具；Process 保留受治理退款能力且不重规划 |

## 剩余风险与边界

- 真实模型质量、提供商费用、运行中 Java/Python 双跑及 p95/p99 未实测；不开生产流量。
- 预算是保守预留上限而非精确计费，网关内部重试不可由本地 SDK 调用数完整计量。
- 限流是单进程 DAG worker 范围；多副本与其他端点仍依赖既有中央配额和部署容量治理。
- 工具观察仍是文本证据，节点 DONE 不能证明每项业务事实正确；保留模型/业务评测。
- 只复用无工具或 rag_search/schema_explore 结果，默认最多 30 秒；需要每轮重读可设 TTL=0。
- S6 依赖中央检查点契约与隔离环境恢复演练，保持 CONDITIONAL；没有新建本地替代存储。
- Code Hygiene 自动 formatter 发现存在限制，但项目 Ruff format 检查实际通过。

## 回滚与下一阶段

关闭 AGENT_DAG_OPTIMIZATION_ENABLED 回到兼容模式，或按完整逻辑提交正常回退代码；不删除任务/事件，不撤销已经发生的业务副作用。异步终态修复完整回退需要应用版本回退。下一阶段仅在获得真实只读评测环境后灰度验证；节点持久恢复按 RECOVERY_DESIGN.md 条件另行启动。
