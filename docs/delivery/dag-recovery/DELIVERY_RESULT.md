# Git 与交付结果

## 源码与验证

- Python实现：`c5b6cef01a58730813f940da8da43e5678e833b5`，独立任务分支已正常快进合入并推送main；[源码CI 38538810884](https://github.com/lirji/platform-agentscope/actions/runs/38538810884) SUCCESS，含镜像扫描。
- Java实现：`555c1d2`；并发知识ETL提交正常合并保留（`2929f0a`、`ae20849`），源码已推送main。新增检查点契约固定到Python不可变c5b6cef，27项契约及4项pin防漂移测试通过。
- Java门禁清单修复：`8f50ad6`，MyBatis Mapper按现存25项校验，不放宽JDBC/动态SQL/逻辑删除规则；已正常推送main。
- 本地Python584项/89.71%，Java全量1524项/0失败/22条件跳过；合入并发任务后async-task及上游重验通过。见[TEST_RESULT](TEST_RESULT.md)。
- 真实MySQL、API退出、worker SIGKILL接管、旧epoch拒绝均通过；v1旧模式及v2节点模式分别演练成功，假模型输出一致。v2已完成节点不重跑，累计预算4次。

## 远程门禁

- Python源码CI：[38538810884](https://github.com/lirji/platform-agentscope/actions/runs/38538810884) SUCCESS，含质量、构建及镜像扫描。
- Java修复后源码8f50ad6：[Cutover 38540055512](https://github.com/lirji/langchain4j-platform/actions/runs/38540055512) SUCCESS（完整reactor、契约pin、MyBatis、Flowable、Compose和部署配置）；[Tax AI 38540055307](https://github.com/lirji/langchain4j-platform/actions/runs/38540055307) SUCCESS。ae20849的Edge检查也通过。
- [Java供应链 38540055244](https://github.com/lirji/langchain4j-platform/actions/runs/38540055244) FAILURE，失败步骤为 Scan aggregate dependency SBOM。Mapper清单问题已经修复；本轮没有新增/升级依赖，依赖安全扫描未通过事实保留。不宣称生产发布就绪，未绕过门禁部署。
- 后续提交仅同步文档；以上CI绑定不可变源码版本，不把文档提交冒充重新完成源码验证。

## 工作区与范围

Python原目录工作；Java因原目录有知识ETL开发，在 `~/.local/share/git-worktrees/langchain4j-platform/dag-node-recovery` 实施。没有stash、reset、强推或删除用户文件。没有生产部署、真实付费模型或切换AGENT_URI；恢复默认关闭。

本任务Java工作树含构建/验证日志，可在交付核查后按需清理；本次未获工作树清理授权，保留。Java原目录在知识ETL任务完成且工作树干净后已正常快进至本次main。历史cross-runtime-verification、persistent-profile-memory及既有临时工作树均保留，未判断为可删。Python `.env`、`.venv`、.workflow、.engineering、dist、reports、测试缓存/coverage片段保留并不纳入提交。脚本仅清理自身随机测试库和进程。

后续启用须按[节点恢复指南](../../dag-recovery.md)先完成中央升级，再启用worker和API；本轮Git推送不代表已经部署或开启。
