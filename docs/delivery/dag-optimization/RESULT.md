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

## S4：证据评审和只读节点复用

- Critic/Replanner 接收结构化状态/工具观察；必需节点失败由代码生成零分，不浪费模型评审且不能被高分覆盖。
- 每请求新建结果复用容器，默认 TTL 30 秒，可设 0 禁用；仅成功且无工具或只调用 rag_search/schema_explore 的节点可复用。
- 时钟、订单、流程状态、analytics_sql、未知工具和所有写操作不复用；带写能力的优化 DAG 禁止开启 replan。
- 指纹绑定目标、任务描述、依赖执行版本；上游重跑即使得到同样文本也使下游失效。复用返回深拷贝。
- 红灯：重复根节点调用和失败被模型评分两项暴露旧行为；绿灯覆盖 TTL、禁用、跨请求/租户、工具扩大拒绝及依赖失效。
- 相关 50 项 PASS；全量 566 passed；Ruff/format/Mypy/contract snapshots/diff check PASS。

## S5：最终验证与独立交付范围

- 审查补充等待队列全局/租户上限，超过容量立即拒绝并收敛同一 DAG 的在途工作；红灯后验证通过。
- 真实 GovernedFunctionTool 适配器测试证明能力不匹配时工具函数不被调用。
- 新只读双跑 suite 3 个场景；本地两个实际 ASGI 应用分别启用旧/优化模式，Shadow 共 6 样本 PASS。没有把 Python 旧模式当作运行中 Java 服务。
- 最终 `uv run pytest --cov=agentscope_platform --cov-report=term --cov-fail-under=80`：569 passed，覆盖率 89.66%。
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src` PASS。
- 契约快照 check PASS，HTTP/JSON/OpenAPI 快照未变；离线通用 Shadow 8 样本 PASS。
- 静态供应链、生产运行手册、对抗评测数据集校验、`uv build`、基础和 readonly-worker Compose config PASS。
- Code Hygiene Gate：IMPLEMENTATION_COMPLETE_WITH_LIMITATIONS。工具没有自动识别 Ruff formatter（FORMAT_TOOL_NOT_AVAILABLE），实际仓库 `uv run ruff format --check .` 已独立运行通过；未伪造自动发现结果。
- 架构复核：AgentScope 类型仍仅在基础设施；domain 新字段为语言中立能力集合；无数据库/消息/依赖变更。
- S6 条件设计已写 `RECOVERY_DESIGN.md`，没有实现或声称节点持久恢复。

## Git 交付

任务分支 `refactor/dag-orchestration`，基线 `4c5f673`。已验证逻辑提交：8545684、49a251d、36db8d6、4b506f8、82651a7，已正常快进合入并推送 origin/main。

源码提交 `82651a79ec603d22e3cec30a05f763684769f0c5` 对应远程 [CI 38529981435](https://github.com/lirji/platform-agentscope/actions/runs/38529981435) SUCCESS，含依赖审计、测试、镜像构建与漏洞扫描。后续收尾文档不改变已验证源码。无生产部署。

原目录无未提交产品改动；保留任务分支与既有 detached `cross-runtime-verification` 工作树。本轮没有新建工作树。`.workflow/`、`.engineering/remediation/` 按当前忽略规则保留；私有配置、`.venv`、缓存、dist/reports 不删除。构建缓存/本轮 dist 可按需清理，但没有执行清理；旧工作树是否可删除需先核对其私有文件和其他任务用途。
