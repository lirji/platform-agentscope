# DAG 诊断交付结果

## Git

- Python：`feat/dag-diagnostics`，源码`63db408`（诊断与成本归因）、`e6c378a`（v1接管历史及执行配置摘要兼容），均已正常合入推送`origin/main`。
- Java：独立工作树`~/.local/share/git-worktrees/langchain4j-platform/dag-diagnostics`，同名任务分支；源码`e7410ed`（三个诊断事件允许列表）已正常合入推送`origin/main`。后续交付文档提交`5cdb6f3`。
- 无强推、无历史重写、无部署。Java原目录main保留原部署任务状态；Python原目录保留任务分支，远程main已包含源码。

## 验证与远程 CI

- Python：616项测试，0失败，覆盖率90.23%；Ruff/format/Mypy107源码文件/契约快照通过。离线shadow8样本、离线包构建、两种Compose静态检查通过。
- Java：`mvn -q -pl async-task-service -am test`，199项测试，0失败/错误/跳过。仅事件允许列表与安全约束验证，无SQL变化。
- Python最终源码e6c378a的[CI and trusted release](https://github.com/lirji/platform-agentscope/actions/runs/38577390963)通过；首批63db408的[CI](https://github.com/lirji/platform-agentscope/actions/runs/38576775738)也通过。
- Java源码e7410ed的[AgentScope Cutover CI](https://github.com/lirji/langchain4j-platform/actions/runs/38576737391)通过。
- 同一Java源码的[供应链CI](https://github.com/lirji/langchain4j-platform/actions/runs/38576737341)在`Scan aggregate dependency SBOM`失败，基线a23cc6c的[供应链](https://github.com/lirji/langchain4j-platform/actions/runs/38575411792)同一步骤也失败。此处只确认失败步骤相同，不将本次功能通过表述为生产发布门禁通过。
- 后续纯交付文档提交可能另触发CI，以上通过证据绑定明确的产品源码SHA，不宣称尚未核验的文档CI通过。

## 保留与限制

- 任务源码/契约/测试均已提交；无用户未提交修改被夹带。
- Python `.env`、`.venv`、缓存、reports、dist、既有忽略目录和历史工作树保留；Java工作树含本次target构建目录。构建缓存/产物可在后续清理授权后处理，私有配置与历史任务资料需保留。
- 没有请求或执行清理授权，未删除工作树/缓存/用户数据。
- 未部署新镜像、未切换生产流量、未调用真实付费模型；现有运行中Docker仍使用此前部署版本。
- 诊断默认开启；费用需显式确认费率。中央服务先升级允许列表，Python随后升级。完整使用与回滚说明见[运行手册](../../dag-diagnostics.md)。

功能开发与Git发布完成；后续依赖安全整改、运行环境部署分别按独立任务处理。
