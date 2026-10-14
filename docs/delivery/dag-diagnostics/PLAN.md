# DAG 运行诊断与成本归因

用户已确认范围；engineering-baseline/v1、skill-contract/v1。Python 实现诊断，Java 中央服务仅扩展三个事件名的允许列表，复用中央任务事件，不新增数据库、中间件或前端。

## 需求与技术未知项

| 问题 | 源码证据 | 决策 |
|---|---|---|
| Runner 观测不覆盖 Planner/Reviewer/TextGenerator | infrastructure/agentscope/{runner,model_factory,closing_model}.py | 在共同真实模型边界记录 usage；用应用层作用域绑定角色、轮次、节点，不改变预算结算 |
| SDK 流式 usage 可能累计、缺失或中断 | budget_model.py、closing_model.py | 只认完成终帧，不累加流式快照；未知记 null，取消保留未知状态 |
| 配置费率默认为零 | core/config.py | 新增显式价格已配置标志；默认不把零当免费，金额 Decimal，费率快照随事件记录 |
| 进程崩溃可能已计费但尚未记录 | dag_recovery.py | 按 executionId 标记本次执行片段；接管时历史不完整，不声称完整账单，不扩展 checkpoint 格式 |
| 当前 SSE 契约必须兼容 | application/async_task.py | 新事件采用独立版本化诊断 DTO，旧事件/HTTP 响应不变；诊断失败独立告警且不改变业务结论 |
| 中央服务有事件名允许列表 | Java AsyncTaskController.PROGRESS_EVENTS | 增加三个明确诊断事件名；沿用原身份/租约/终态/幂等/大小校验；禁止放开任意事件 |

## 架构与影响分析

- domain：语言中立的模型调用、操作、片段摘要事件 Schema，不含提示词、答案、工具输入输出或凭据。
- application：请求内诊断会话、协程局部操作上下文；按轮次计算节点执行耗时加权最长依赖路径。排队时间独立记录，关键路径不是整次请求耗时。
- infrastructure：模型适配器读取提供商 usage；观测适配器写结构化日志、低基数指标。异步复用已授权的中央任务 progress/SSE 查询链路。
- 单进程只保留有界操作摘要，不缓存业务输出；跨租户上下文由入口显式绑定，ContextVar 只在当前协程树内传播。
- 诊断 IO 使用有界后台队列与超时，结束有界排空并回收发布协程；普通观测故障不掩盖业务失败或取消；不重试模型、不修改持久恢复和预算准入语义。
- 旧执行模式也支持诊断，但 SDK 隐藏重试不计为独立调用，费用仅为已观测 usage 估算，不是供应商账单。
- 数据库/事务/MQ：复用已有中央事件权限、租约、脱敏和保留策略；本次无 DDL。
- 性能：没有新增 SLA 承诺；检查观测故障的有界性和并发行为，不虚构容量结果。

候选方案：复用现有事件+日志+OTel（选定）；新建诊断计费数据库（拒绝，重复权威且需额外对账）。technology_selection、feature_architecture、impact_analysis：PASS，基于当前锁定依赖源码和现有接口。

## 实施切片与验收

1. S1：诊断契约、会话与模型边界。先补行为测试；未知用量/价格、流式完成、异常/取消、跨租户隔离、观测故障可验证。
2. S2：全 DAG 角色、节点排队/执行、复用/恢复原因、关键路径、日志/指标/SSE 接入。复用不新增调用；旧 JSON/事件保持不变；恢复摘要明确片段范围。
3. S3：契约导出、全量 Ruff/format/Mypy/Pytest、离线 shadow、文档与自审，按授权提交并合入推送 main。真实付费模型与生产部署不在本轮验证范围。

中央兼容扩展是 S2 的必要依赖；Java 原目录存在其他任务部署上下文，使用 `~/.local/share/git-worktrees/langchain4j-platform/dag-diagnostics` 隔离，仅提交本功能文件。发布顺序为 Java 兼容扩展先于 Python 新事件；本任务不执行服务部署。

## 回滚

关闭 DAG 诊断开关可停止新增事件/指标；保留既有任务事件。无数据库回退。旧客户端可忽略新诊断事件，不以本次估算数据改变中央额度或业务状态。
