# 验证记录

日期：2026-10-14。Python 基线64c86da，Java基线4e65539；本次仅新增恢复协议及接入，未部署。

| 检查 | 结果 |
|---|---|
| Python Ruff / format / Mypy | PASS，103 source files |
| Python 全量 pytest + coverage | 584 passed，89.71%，1 warning |
| JSON Schema / OpenAPI 导出检查 | PASS |
| 离线 Shadow | PASS，8 samples；优化旧/新场景包含在pytest中 |
| Python wheel/sdist | PASS，`uv build --offline`；联网构建遇PyPI超时，未改依赖 |
| Compose base + readonly worker | PASS，配置解析；未启动部署 |
| Java 全量 Maven（合入并发ETL前） | 1524 tests，0 failures/errors，22条件跳过 |
| Java async-task及上游（合并后重验） | 196 tests，0 failures/errors/skips |
| 真实隔离 MySQL | ReadOnlyTaskDispatchTest + DagCheckpointTest PASS |
| Java/Python跨进程 v2演练 | PASS，真实Java/MySQL/HTTP，假OpenAI模型 |
| Code Hygiene | 无阻断，IMPLEMENTATION_COMPLETE_WITH_LIMITATIONS：现有工具未发现独立formatter，Python实际Ruff format已通过；Java无额外formatter/静态分析工具 |

跨进程演练：API入队后退出；worker-one完成首节点，在第二节点模型调用中被SIGKILL；15秒测试租约过期后worker-two领取更高epoch，首节点复用、第二节点重做、汇总成功。provider调用4次，数据库modelCalls=4，旧执行器写事件409。从kill到验收实测16.00秒，全演练26.61秒。不是生产容量、付费模型、灾备RTO/RPO验证。

故障矩阵：初次读取空检查点、RUNNING未知输出、已提交结果、节点依赖版本变化、工具结果失效、规划安全回退、评审/重规划恢复、跨重启预算、固定期限、中央不可用、并行保存、CAS竞争、租约过期/接管、旧epoch、取消、跨tenant/actor、错误action/task JWT、事件失败事务回滚、超大状态与逻辑删除。

本地执行日志保留在/tmp/dag-recovery-*、Python `.git/codex-cross-runtime-reliability-baseline/dag-recovery-process-*` 和Java `async-task-service/target/dispatch-mysql.log`，不提交凭据/测试日志。随机测试库由脚本清理，其余数据保留。契约pin与远程CI在DELIVERY_RESULT单独记录。

追加验证：v1跨进程演练PASS（5次假模型调用，恢复16.16秒）；v2最终源码复验PASS（4次调用/预留，恢复15.82秒）。Java Mapper边界25项及Flowable事务profile通过。
