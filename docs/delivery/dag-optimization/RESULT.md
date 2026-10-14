# DAG 优化实施证据

## S1：失败传播与汇总隔离

- 新模式开关默认 false，旧请求/响应字段不变；未知依赖新模式拒绝，旧模式保留兼容。
- 服务端能力允许列表不可由模型扩大，ToolPolicy 同时检查节点能力和既有 scope/确认/幂等。
- 下游失败传播为 SKIPPED，综合为 PARTIAL，acceptedByThreshold=false；异步 PARTIAL/ERROR 写 FAILED。
- 结构化证据包含状态，失败节点不传递残余回答；汇总使用无工具 TextGenerator。
- 红灯：4 项新增行为测试在旧实现失败。绿灯：新增 7 项，聚焦 25 项，全量 537 passed。
- Ruff/format/Mypy/contract snapshots/git diff --check PASS。
- S2 红灯：就绪子节点不等慢根节点、槽位前不发开始事件，均按预期失败，尚未实现。

## 边界

不执行真实付费模型或生产部署，未声称真实双跑/性能/恢复演练通过。

## S2：依赖就绪与并发隔离

- 新模式取消层屏障，按直接依赖就绪执行；响应仍按稳定拓扑顺序。
- 通用/Process DAG 共享总槽位，租户先获取自身槽位；最后一个等待者退出时清理租户状态。
- worker queued/start/result 反映真实等待与完成；取消和基础设施异常收敛全部子协程。
- 5 项调度测试覆盖就绪释放、事件、跨服务租户隔离、取消和异常；相关 40 项 PASS。
- Ruff/format/Mypy/diff check PASS。修复 S1 测试末尾额外空行，未改变业务行为。

## S3：整次运行预算

- 规划、排队、执行、汇总、评审和重规划共享 deadline；不晚于调用者 token 过期前 2 秒。
- 实际模型边界统一计数，先检查 DAG 准入，再检查既有 Java 租户配额，不重复计数。
- UTF-8 输入字节、输出上限和保守协议/媒体预留累积限制；这不是精确计费 token。失败和未知 usage 不返还本次预算。
- 优化模式拒绝 SDK 自动重试配置；预算异常不被 Planner fallback 或 runner ERROR 吞掉。
- 超限 HTTP 429/AGENT_DAG_BUDGET_EXCEEDED；截止 HTTP 504/AGENT_DAG_DEADLINE_EXCEEDED。异步沿用中央 FAILED 映射。
- 红灯 4 项；绿灯 8 项新测试，包含真实适配器配合本地 stub provider，未连接真实模型。全量 553 passed。
- Ruff/format/Mypy/contract snapshots/diff check PASS。
