# Agent 平台生产发布与恢复手册

本手册是 AgentScope 与 retained Java 平台的统一生产门禁。localhost、H2、MockTransport、Helm
render 或静态测试只能证明实现可执行，不能代替目标账号 IAM、真实备份恢复、峰值容量、完整业务
高峰 soak、canary、告警和值班证据。证据不完整时结论固定为 NO-GO。

配套机器可读模板为 `production-evidence-template.json`。复制到发布记录后填写，不要把 token、
密码、生产地址、用户正文或反馈原始导出提交到仓库。

## 发布角色与变更记录

每次发布在开始前指定并记录：

- release owner：唯一 GO/NO-GO 主持人；
- AgentScope、Java、数据库、Redis、网络/IAM 和可观测性 owner；
- on-call 与 incident commander；
- candidate 与 rollback 的不可变镜像 digest；
- 变更单、canary 租户清单、扩量窗口、数据集/报告 digest 和回滚负责人；
- 当前 primary backend，禁止在记录不明时同时让 Java/AgentScope 接管新任务。

普通 CI 或本手册不会自动部署。生产变更需要独立授权，release owner 只能在机器门禁和人工审批
均通过后把 evidence `decision` 改为 `GO`。

## RPO / RTO

以下是本次平台发布的最大目标；目标环境必须用真实恢复演练证明不超过这些值：

| 数据/能力 | RPO | RTO | 解释 |
| --- | ---: | ---: | --- |
| Agent 整服务路由 | 0 分钟 | 15 分钟 | 路由切换不丢权威数据；在途请求不自动重放 |
| Agent session/checkpoint Redis | 5 分钟 | 30 分钟 | 从批准的快照/AOF 恢复；缺记录的执行明确失败或由调用方重提 |
| Java 权威 MySQL（任务/流程/业务） | 5 分钟 | 60 分钟 | 备份/PITR 到隔离实例后校验，再恢复流量 |
| 评测与发布证据 | 1440 分钟 | 240 分钟 | 从受控制品存储恢复；缺证据不得发布 |

RPO/RTO 是目标而不是本地测试结论。若业务批准值更严格，证据文件和变更单使用更严格值；不得
放宽模板来让失败演练通过。Redis/MySQL restore 必须记录备份时间、故障时间、数据时间点、开始/
恢复时间和实测 RPO/RTO。

## 发布前门禁

在各自仓库从候选 commit 执行，保存命令、commit、时间和退出码：

```bash
# agentscope-platform
uv sync --frozen --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python scripts/export_contracts.py --check
uv run pytest
uv run python scripts/shadow-smoke.py
uv run python scripts/test_supply_chain_config.py
uv run python scripts/test_production_runbook.py
docker compose -f compose.yml config --quiet

# langchain4j-platform
mvn -q -DskipITs test
bash deploy/test-production-cutover-config.sh
bash deploy/test-runtime-hardening-config.sh
bash deploy/test-database-migration-config.sh
bash deploy/test-supply-chain-config.sh
```

此外必须验证：

1. candidate/rollback digest 的 Cosign signature、provenance、SBOM 与扫描结果；
2. 生产 `secrets.create=false`，workload identity/ESO、NetworkPolicy 和 callback allowlist 已审计；
3. migration Hook 用独立 DDL 身份完成，应用身份没有 DDL 权限；不执行 down migration；
4. AgentScope readiness 所有 required dependency 为 UP，Java actuator readiness 为 UP；
5. Redis/MySQL 最新备份可读，恢复演练在本次发布窗口允许的版本上完成；
6. dashboard、告警通知链、on-call 和变更单已经演练/确认。

## Shadow、对抗与回放

使用批准的 `agent-evaluation-dataset.v1`，保存 v4 报告和运行版本：

```bash
uv run agentscope-shadow-eval \
  --legacy-url REPLACE_WITH_NAMED_TEST_LEGACY_URL \
  --candidate-url REPLACE_WITH_NAMED_TEST_CANDIDATE_URL \
  --dataset REPLACE_WITH_VERSIONED_DATASET \
  --require-version-metadata \
  --runs 3 \
  --output reports/release-shadow-v4.json

uv run agentscope-shadow-eval \
  --legacy-url REPLACE_WITH_NAMED_TEST_LEGACY_URL \
  --candidate-url REPLACE_WITH_NAMED_TEST_CANDIDATE_URL \
  --dataset REPLACE_WITH_VERSIONED_DATASET \
  --replay-report reports/release-shadow-v4.json \
  --require-version-metadata \
  --runs 3 \
  --output reports/release-replay-v4.json
```

再运行 `eval/datasets/agent-safety-adversarial.v1.json`。跨租户读取、禁止工具调用、PII/异常泄漏、
确认绕过、版本漂移或回放 dataset 不一致任一出现即 NO-GO。真实反馈导入还须附 consent、DLP 和
留存审批。报告不得包含 goal、回答、observation、token 或原始 feedback ID。

## Canary 与扩量

固定阶段如下；每阶段需 release owner 和 on-call 共同签字：

1. 只对命名测试租户启用，至少观察 15 分钟并执行同步、异步、session、MCP/A2A 和只读业务 smoke；
2. 扩到首个生产 canary 租户或约 5% 合格流量，至少 30 分钟；
3. 扩到约 25%，至少 60 分钟；
4. 扩到约 50%，跨过一个完整业务高峰周期；
5. 复核所有证据后再切 100%，继续观察一个完整高峰周期。

若租户路由无法安全表达百分比，按预先批准的租户 cohort 等价执行。每次扩量前记录当前版本头、
backend 响应头、任务 PENDING/RUNNING、资源水位、质量/成本、错误和回滚预估时间。不得跳级，
不得对失败请求做单请求 Java fallback。

## 监控与停止条件

至少展示并告警：

- `agent_run_duration_ms_bucket` 的 P50/P95/P99；
- `agent_run_inflight`、`agent_async_task_backlog`、`agent_async_task_running`；
- `agent_run_terminations_total` 按 DONE/TIMEOUT/BUDGET/ERROR/CANCELLED；
- token/cost、HTTP 4xx/5xx、readiness、lease/heartbeat/orphan、outbox dead/oldest age；
- Java 中央任务 backlog/inflight、MySQL/Redis、callback、Qdrant/embedding 和 pod restart/HPA；
- prompt/model/toolset 版本、backend 标签、租户隔离审计和禁止工具事件。

默认停止/回滚条件（变更单只能设得更严格）：

- 任一跨租户访问、鉴权/确认绕过、凭据/PII 泄漏或禁止副作用：立即停流并进入事故；
- candidate 5xx/ERROR/TIMEOUT 超过 2%，或比 baseline 高 1 个百分点持续 5 分钟；
- P95 超过批准 SLO，或超过 baseline 1.25 倍持续 10 分钟；
- backlog 连续增长 15 分钟、readiness 连续 DOWN 2 分钟、heartbeat/orphan/outbox dead 增长；
- 单位成功请求成本超过 baseline 1.25 倍，Shadow v4 门禁失败或运行版本批内漂移；
- 资源达到批准上限、HPA 无法扩出、pod 重启或完整高峰 soak 出现任务丢失。

## 整服务回滚

1. release owner 宣布停止扩量，冻结新 canary，记录触发指标和时间；
2. 停止新 Agent 提交；不要删除任务、session、outbox 或 migration 记录；
3. 查询中央任务表，`PENDING` 和 `RUNNING` 必须为零，或由 owner 明确把遗留任务安全终结；
4. 验证 rollback digest 的签名/provenance，启动并探活 retained Java `agent-service`；
5. 同时把 edge `AGENT_URI` 和 interop `AGENT_BASE_URL` 切到 Java，并更新 backend 标签；
6. 只用新请求验证 `/agent/run`、任务、MCP/A2A 和租户隔离；禁止重放切换前在途请求；
7. 保留 AgentScope、Redis checkpoint、扩展 schema 和审计记录，确认指标稳定后再停止 candidate；
8. 恢复 AgentScope 也遵守同样的排空、探活、整体切换和新请求验证顺序。

精确路由命令以 Java 仓
`docs/Agent编排/agentscope-full-cutover.md` 和
`docs/平台工程/production-cutover-gates.md` 为准。安全特性不得通过恢复普通 JWT、任意 callback、
无限预算、明文 push token 或 down migration 回滚。

## 恢复验证

Redis 演练需在隔离 namespace/实例完成：从批准快照/AOF 恢复，验证 session owner 隔离、revision
CAS、TTL、lease 接管和已发生副作用的重新确认；旧 grant 不得重放。记录实测 RPO/RTO和丢失窗口。

MySQL 演练需恢复到隔离实例：运行 Flyway validate，核对任务/事件/outbox/幂等账本/Flowable，抽样
跨租户隔离，确认应用账号无 DDL 权限。只在一致性验证通过后恢复读流量，再恢复写流量。误执行
Contract migration 时停止写入并走 PITR，不手改 Flyway history。

路由恢复后验证：

- 新请求 backend 与期望一致，旧请求没有自动重放；
- 中央 PENDING/RUNNING 能排空，lease epoch 和 outbox claim 没有 stale writer；
- session GET/run owner 隔离，capability registry/LKG 正常；
- readiness、错误率、P95、backlog、成本和安全审计回到阈值内；
- rollback 后再次恢复 candidate 的演练也完成，`rollback.post_restore` 有独立证据。

## 外部证据门禁

复制模板并填写 HTTPS 证据链接：

```bash
cp docs/operations/production-evidence-template.json REPLACE_WITH_RELEASE_EVIDENCE_PATH
uv run python scripts/test_production_runbook.py \
  --evidence REPLACE_WITH_RELEASE_EVIDENCE_PATH \
  --require-go
```

`--require-go` 要求 19 项全部为 PASS，具有非空 owner、RFC3339 UTC 时间和 HTTPS evidence URI，
release/candidate/rollback digest 已解析且 decision=GO。缺 IAM、restore、容量、完整高峰 soak、v4
双跑/对抗、tenant canary、dashboard/alert、on-call/change 或整服务回滚证据时保持 NO-GO。

## 事故与升级

- 安全/跨租户/副作用事故：立即停 Agent 新流量，保全 audit/trace/outbox，通知安全和领域 owner；
- 数据一致性事故：停止写入，禁止清表/reset/down migration，由数据库 owner 执行隔离恢复；
- 依赖事故：保持 readiness DOWN，禁止用假成功或关闭 timeout/circuit 掩盖；
- 供应链事故：拒绝未签名 digest，回退前一可信 digest 并重新验证 provenance；
- 评测/证据系统事故：保持当前 primary，不以缺失报告批准发布。

incident commander 记录时间线、影响租户、版本、停止条件、恢复动作和后续修复。事故结束不自动
恢复扩量；必须重新执行本手册从 Shadow 开始的门禁并由 release owner 再次批准。
