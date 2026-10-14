# DAG 诊断本机 Docker 部署

- 用户授权：将最新代码部署到 Docker；目标为本机 `desktop-linux`、Compose 项目 `langchain4j-platform`。
- 结果：PASS（本机运行验证）；完成于 2026-10-14 22:15 +08:00。未执行生产部署。
- 固定源码：Python `3cb39f6e125a17d5be40430d85dc3aea39bad045`，Java `5cdb6f35e266701ef34d11e258dd604739e7bb0e`，均为部署开始时远程 main。
- 通过 `git archive` 从已提交快照构建，镜像 OCI revision 与上述提交一致；未将私有配置装入镜像。

## 更新范围

| 服务 | 新镜像 | 原镜像 |
| --- | --- | --- |
| async-task-service | langchain4j-platform-async-task-service:5cdb6f3 | langchain4j-platform-async-task-service:3f31dfd |
| agentscope-orchestrator | agentscope-platform:3cb39f6 | agentscope-platform:69de7e9 |

先更新中央服务并确认 readiness UP，再更新 Python。Java 从原部署版本到最新 main 的产品改动只有中央事件允许列表及其测试；其他服务、前端和数据库迁移代码相同，因此继续使用已验证的 3f31dfd 镜像。无数据库迁移，无卷删除。两服务 Compose 环境变量与替换前逐键比对一致，保留原鉴权、端口、模型配置和恢复开关。

## 验证证据

- 最新 Java 提交快照离线 Maven package（async-task-service 及依赖）成功，199 项测试，0 失败/错误/跳过。
- 最新 Python 提交 CI [38577841435](https://github.com/lirji/platform-agentscope/actions/runs/38577841435) 成功；此前源码本地 616 项测试通过。Java 产品提交 Cutover CI [38576737391](https://github.com/lirji/langchain4j-platform/actions/runs/38576737391) 成功，后续只有文档变更。
- 14 项 Java readiness 和 Python readiness 均 HTTP 200 / UP；17 个主服务运行，9 个既有迁移任务 exit 0；新容器重启计数为 0。
- 前端、Casdoor OIDC、授权知识源与质量列表 HTTP 200；匿名访问知识源 HTTP 401。
- 在新 Python 容器内运行合成诊断，经真实 HTTP 客户端、中央任务库和 SSE：三类事件接收/回放、eventKey 幂等、跨租户读取隔离、过期 leaseEpoch 拒绝均通过。专用租户 `deployment-diagnostics`；成功烟测任务 ID 见 RUNTIME_EVIDENCE.json，任务已终态。
- 合成 usage 不调用模型；未知价格保持 null。烟测初次因脚本将 monotonic 时间误用于 epoch deadline 而未投递，测试任务已取消；修正烟测后通过，产品代码未修改。
- 当前诊断开关 true，价格确认 false，节点恢复 false。未配置或猜测模型价格；未验证实际提供商账单。

完整脱敏结果见 [RUNTIME_EVIDENCE.json](RUNTIME_EVIDENCE.json)。

## 本机操作与回滚

Java 仓库下保留了忽略目录 `deploy/.dev-infra-state/dag-diagnostics-20261014/`，含提交快照、构建日志、Compose 包装脚本与烟测脚本。包装脚本复用既有配置加载入口，敏感配置未提交。

重复应用当前版本（在 Java 仓库执行）：

```bash
bash deploy/.dev-infra-state/dag-diagnostics-20261014/compose.sh up -d --no-deps --no-build --wait --wait-timeout 120 async-task-service
bash deploy/.dev-infra-state/dag-diagnostics-20261014/compose.sh up -d --no-deps --no-build --wait --wait-timeout 120 agentscope-orchestrator
python3 deploy/.dev-infra-state/dag-diagnostics-20261014/runtime-check.py
```

旧镜像与旧包装脚本保留。需要回退时先回退 Python，避免旧中央拒绝诊断事件，再回退中央：

```bash
bash deploy/.dev-infra-state/latest-3f31dfd/compose.sh up -d --no-deps --no-build --wait --wait-timeout 120 agentscope-orchestrator
bash deploy/.dev-infra-state/latest-3f31dfd/compose.sh up -d --no-deps --no-build --wait --wait-timeout 120 async-task-service
python3 deploy/.dev-infra-state/latest-3f31dfd/runtime-check.py
```

本次未触发回滚。回退镜像不删除已写入的事件。

## 限制与保留内容

Java 最新提交供应链 [38577710290](https://github.com/lirji/langchain4j-platform/actions/runs/38577710290) 仍在依赖 SBOM 扫描失败，与此前基线相同。本次按用户本机部署指令执行，不宣称全部安全门禁通过或达到生产发布要求。

访问入口：[前端](http://localhost:8093)、[网关](http://localhost:18080)、[登录](http://localhost:8000)。DAG 诊断查看及费用配置见 [使用说明](../../dag-diagnostics.md)。

本次未新建工作树。既有工作树、私有配置、旧镜像与两套部署状态目录均保留；状态目录仍供重启/回滚使用，不应整体清理。快照和构建日志可在不再需要重建/审计时另行清理，本次未删除。
