# Codex Progress

## 任务目标
实现节点级持久恢复：中央契约、Python DAG接管、隔离演练及正常合入推送两仓main；不部署。

## 已完成
- S1：中央V5检查点、专用JWT、父任务行锁/租约epoch/CAS、同事务事件和逻辑删除；v1/v2领取隔离。
- S2：计划（含安全回退）、节点、汇总、评审/重规划持久化；输入身份版本绑定；跨重启预算和deadline；默认关闭。
- S3：Python584项/89.71%，Ruff/format/Mypy/契约/Shadow/离线构建/Compose通过；Java全量1524项/0失败/22条件跳过；隔离MySQL通过。
- 真实跨进程SIGKILL恢复通过：首节点不重做，未知次节点重做，累计4次模型预留，旧epoch被拒；本地恢复16.00秒，不承诺生产RTO。
- 计划、报告、验证和问答同步在docs/delivery/dag-recovery/及docs/dag-recovery.md；之前进度保留PREVIOUS_PROGRESS.md。

## 已修改文件
- Python application/dag_recovery及dag/planning/async_task、domain检查点协议、worker/HTTP/模型预算适配、配置和契约。
- 对应行为/契约测试、跨进程演练脚本、README/指南/问答/交付文档。
- Java改动位于独立工作树：~/.local/share/git-worktrees/langchain4j-platform/dag-node-recovery；原目录知识ETL改动未触碰。

## 未完成
- S4：两仓逻辑提交、Java契约固定到Python不可变commit、合入推送main及远程CI核对。

## 当前问题
- 无实现阻塞。PyPI临时超时后离线构建成功；Code Hygiene仅有formatter自动发现限制，无阻断。
- 工具节点及依赖链跨接管重做；写节点恢复、真实付费模型双跑、生产启用和灾备承诺不在本次交付。
- 保留历史工作树、私有配置、测试缓存/日志；未清理用户数据或部署。

## 下一步建议
1. 完成S4 Git与契约pin，更新DELIVERY_RESULT和当前进度。

## 恢复 Prompt
读取docs/delivery/dag-recovery/和本文件，从S4交付继续；不要重做已通过功能，不要部署，不要触碰Java原目录知识ETL改动；保护历史工作树和忽略文件。
