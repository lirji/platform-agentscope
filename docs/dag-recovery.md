# 只读 DAG 节点持久恢复

节点恢复已实现，默认关闭。中央 Java async-task-service 持久化检查点，Python worker 读取并继续执行；inline 和 `agent.readonly.*.v1` 保持原行为。

## 启用顺序

1. 先应用中央 `V5__dag_checkpoint.sql`，升级所有参与分发的 Java 实例。保留既有V1–V4迁移，不改历史校验和。
2. API 与 worker 使用相同不可变运行版本和配置。设置 `ASYNC_TASK_DAG_RECOVERY_ENABLED=true`、`AGENT_DAG_OPTIMIZATION_ENABLED=true`、`AGENT_MODEL_MAX_RETRIES=0`、`AGENT_PLANNER_MAX_RETRIES=0`。只用于 `ASYNC_TASK_ROLE=api/worker`。
3. 先上线支持 checkpointVersion=1 的 worker，再启用 API v2 入队。`compose.readonly-worker.yml` 已传递恢复开关，其他凭据/readonly限制沿用异步编排说明。

DAG、dag-plan、Analyst、Process 入队为 `.v2`；单 Agent run 仍为 `.v1`。所有 v2 都只读，没有确认grant或写工具恢复。

## 恢复行为

每个模型调用前保存预算；每个操作先存RUNNING，再保存DONE及结果。进程崩溃后中央租约过期，下一worker接管。已提交且兼容的纯计算节点不重跑；工具节点及其下游重新执行，以重新校验权限和读取数据。规划、回退计划、评审、重规划与汇总均有检查点。

结果绑定输入、租户、用户、部门、scope和执行版本。改变版本或配置不会静默沿用旧状态。总deadline和累计预留不会刷新；过期或耗尽时失败。检查点请求暂不可用或CAS冲突时停止worker续租和继续执行，等待后续领取；中央既有最多3次领取上限不变。

节点重做可能重复模型计费；只读能力不等于外部数据永久不变。工具结果不跨接管直接复用。任务取消不撤销已执行效果，终态/旧epoch/其他actor均不能更新检查点。

## 验证与回滚

```bash
uv run python scripts/test_durable_worker_process.py --dag-recovery --java-repo /path/to/langchain4j-platform
```

脚本使用 dev_infra 的 MySQL、随机隔离库、本地假模型、独立API与worker进程；不会调用真实模型。已有 v1 演练可不传 `--dag-recovery`。

关闭API恢复开关只影响新任务。回滚worker前应排空或取消v2；保留V5数据，不让旧worker接管v2。详细计划、事务/故障证据见 [实施报告](delivery/dag-recovery/ENTERPRISE_FEATURE_REPORT.md)。未执行生产启用或生产RTO/RPO验收。
