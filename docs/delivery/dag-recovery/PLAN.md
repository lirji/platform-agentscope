# 节点持久恢复执行计划

用户于 2026-10-14 授权出计划后连续实施。Python 基线 64c86da；Java 基线 4e65539。

## 目标与验收

中央任务服务为唯一权威，新增语言中立检查点；worker 崩溃后可复用兼容的已完成节点。预算、截止时间不因接管重置；旧 epoch、取消后写入及跨租户访问必须拒绝。默认关闭，不部署、不切换生产流量。

## 技术未知项与选择

- 中央持久化已是 MySQL + MyBatis + Spring 事务，已有 leaseEpoch；复用，不引入 Python DB、Redis 或新框架。
- 新 kind 为 agent.readonly.{dag,dag-plan,analyst,process}.v2；claim 增加 checkpointVersion，旧请求只领 v1，支持版本 1 的新 worker 可领 v1/v2。
- 增量 V5 表按 taskId 存有界 JSON 快照、CAS revision；父任务行锁串行校验租户、actor、owner、epoch、未过期租约和非终态。写入与 checkpoint 事件同事务。
- 快照包含 schemaVersion、输入/身份/执行版本摘要、固定 deadline、累计模型预留、操作记录。每个操作记录 RUNNING/DONE、fingerprint、结果版本、结果与可复用性。不存 JWT、确认凭据或 AgentScope 状态。
- 规划、节点、汇总、评审及重规划按稳定操作键记录。接管重新遍历已保存计划，成功且安全的检查点直接使用。RUNNING 可重做，但只读且预算保留；不是 exactly-once 模型调用。
- 工具权限/数据版本无法跨服务快照：凡节点有工具步骤或依赖不可复用节点，接管时重跑及下游失效。纯计算节点在任务固定期限内复用。未取得结果的调用可能重复计费。
- 中央最多三次领取与既有队列配额继续生效；单快照最多 2 MiB、256 操作。保留策略沿用任务逻辑删除，不宣称物理删除。

## 分阶段实施

1. S1：契约、安全测试、V5、Mapper、原子检查点服务/API、版本化领取。验证 H2 与真实隔离 MySQL。
2. S2：Python 契约客户端、恢复会话、规划/DAG/模型预算接入、开关和 v2 分发。验证重启复用、失败、权限/版本、取消与预算。
3. S3：真实中央服务 + 独立 Python 进程恢复演练，SIGKILL、接管、防旧 epoch；全套静态检查/回归/契约/离线双跑、文档与问答同步。
4. S4：两仓分别逻辑提交，Java 先合入、Python 后合入推送 main，核对 CI；不部署。Java 原目录有知识 ETL 开发，使用标准目录内独立工作树保护它。

## 影响分析与 Gate

technology_selection=PASS：复用现有稳定依赖。feature_architecture=PASS：中央唯一写入权威，应用只依赖协议，不泄露适配器状态。impact_analysis=PASS：新表/新接口/新 kind，旧 API 字段不变；默认关闭，先扩展后启用。

## 回滚

先停止 v2 入队并排空/取消 v2，再关闭 worker 恢复；v1 继续运行。旧 worker 不可领取 v2。保留 V5 与检查点记录，不能把回滚镜像视为撤销已执行效果。无需新增生产容量承诺；恢复时间仅报告实测，不外推 RTO/RPO。
