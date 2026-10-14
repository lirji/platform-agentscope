# Codex Progress

## 任务目标
节点级持久恢复已完成；本轮 S4 按用户要求默认启用并正常提交、合入推送 Python origin/main，不部署。

## 已完成
- S1：中央V5检查点、专用JWT、父任务行锁/租约epoch/CAS、同事务事件和逻辑删除；v1/v2领取隔离。
- S2：计划（含安全回退）、节点、汇总、评审/重规划持久化；输入身份版本绑定；跨重启预算和deadline；最初交付默认关闭，现由 S4 调整为 API/worker 默认开启。
- S3：Python584项/89.71%，Ruff/format/Mypy/契约/Shadow/离线构建/Compose通过；Java全量1524项/0失败/22条件跳过；隔离MySQL通过。
- 真实跨进程SIGKILL恢复通过：首节点不重做，未知次节点重做，累计4次模型预留，旧epoch被拒；本地恢复16.00秒，不承诺生产RTO。
- 计划、报告、验证和问答同步在docs/delivery/dag-recovery/及docs/dag-recovery.md；之前进度保留PREVIOUS_PROGRESS.md。

- Python源码c5b6cef、Java源码555c1d2及门禁修复8f50ad6已正常合入推送两仓main，未强推；并发ETL提交完整保留。
- Python CI38538810884、Java Cutover38540055512及Tax AI通过；Java供应链38540055244在依赖SBOM扫描失败。详情见DELIVERY_RESULT.md。

- S4：API/worker 默认恢复和优化开启，inline 保持关闭，显式配置优先；Compose/模板/指南已同步。589项测试、89.71%覆盖率、Ruff/format/Mypy/契约/Compose通过。证据见 DEFAULT_ENABLEMENT.md。

## 已修改文件
- Python application/dag_recovery及dag/planning/async_task、domain检查点协议、worker/HTTP/模型预算适配、配置和契约。
- 对应行为/契约测试、跨进程演练脚本、README/指南/问答/交付文档。
- Java改动位于独立工作树：~/.local/share/git-worktrees/langchain4j-platform/dag-node-recovery；原目录知识ETL改动未触碰。

## 未完成
- S4 实现与验证完成，待提交合入推送；未执行生产启用/部署。Java依赖SBOM扫描未通过，后续依赖整改单独处理，不宣称生产发布就绪。

## 当前问题
- 无实现阻塞。PyPI临时超时后离线构建成功；Code Hygiene仅有formatter自动发现限制，无阻断。
- 工具节点及依赖链跨接管重做；写节点恢复、真实付费模型双跑、生产启用和灾备承诺不在本次交付。
- 保留历史工作树、私有配置、测试缓存/日志；未清理用户数据或部署。

## 下一步建议
1. 提交 S4，正常合入推送 origin/main 并记录实际提交；生产发布前仍须单独处理 Java 依赖安全扫描。

## 恢复 Prompt
读取 docs/delivery/dag-recovery/DEFAULT_ENABLEMENT.md，从 S4 Git 交付继续。API/worker 默认开启恢复，inline 默认关闭；不要重复实现、部署或清理历史工作树/忽略文件。Java依赖安全扫描仍未通过。
