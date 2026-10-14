# 本地整改与依赖准备

## 授权、范围与验收

2026-10-14 用户批准按剩余事项建议执行，随后明确“暂时没有，先完成本地整改和依赖整改准备”。
本轮交付本仓历史安全修复、JWT/Shadow 测试、过期文档与 Java 依赖准备；Git 正常任务分支、
合并与推送 main 按 AGENTS.md 持续授权执行。真实模型/MCP/Sandbox、生产发布和 Java 版本升级
不在本轮执行范围。历史 ESS 的阻塞/审批结果保持原样，本轮是用户新授权的交互式整改。

验收：生产禁止关闭鉴权；非法/非规范 grant 在 HTTP 和 codec 边界拒绝；合法 grant 只能
消费一次；回环测试不经代理；现有 Ruff/format/Mypy、pytest、契约、运行手册、Shadow、
供应链审计和包构建通过；当前状态与源码/远程记录一致，Git 交付可追溯。

## 切片状态

| ID | 范围 | 状态 |
|---|---|---|
| L1 | 交付生产鉴权保护、JWT 与回环测试修复 | DONE；16f8deb 已合并 main |
| L2 | multidict 6.7.1 → 6.9.1 安全补丁 | DONE；07af2d8 已合并 main |
| L3 | 同步迁移/运行/CI 文档，整理历史状态 | DONE；9abcc5d 已合并 main |
| D0 | Java 最新 SBOM 与兼容路线准备 | 完成；未执行 Java 升级 |
| L4 | runtime Perl 安全补丁 | DONE；fd3a44b 远程构建及镜像扫描 PASS，已合并 main |
| G1 | 分批提交、main 合并推送、远程 CI | DONE；修复后源码 fd3a44b CI SUCCESS，main 推送成功 |

## 实现与验证证据

- 基线 `a7526db`，原目录任务分支 `fix/pending-security-remediation`；原有 6 个 tracked
  dirty 文件与 `tests/test_config.py` 纳入本任务审查与交付。`.engineering/remediation/`
  和 `.workflow/` 为历史本地治理记录，保留而不加入本次提交。
- 修改前聚焦测试 **1 fail / 24 pass**：PyJWT 2.15.1 提前拒绝非规范编码，旧测试预期不成立。
  修改后 **26 pass**，同时验证未消费/已消费状态、合法 grant 单次消费和 HTTP 不进入 Agent。
- `Settings` 在 prod/production（含大小写和空白归一化）下禁止关闭内部鉴权；本地显式关闭
  保持兼容。测试同时覆盖生产正常启动配置与匿名业务请求 401。
- 首次全量 **526 pass / 89.44% coverage**；Ruff、format（289 files）、Mypy（97 files）、
  contract export、供应链配置、生产运行手册静态门禁、对抗集校验和 Shadow 8 samples 通过。
- 最新 `uv audit` 发现 multidict 漏洞后，将锁文件唯一版本变化固定为 6.9.1。
  [供应方公告](https://github.com/aio-libs/multidict/security/advisories/GHSA-54p9-h82j-f925)
  说明受影响版本及修复下限；aiohttp 现有约束 `>=4.5,<7` 兼容该版本。
  保留 Apache-2.0 许可证，无新增直接依赖；升级后审计 105 个生产包，0 已知漏洞。
- Code Hygiene 没有 blocking finding；引擎未自动识别格式化器，结论
  `IMPLEMENTATION_COMPLETE_WITH_LIMITATIONS`。实际 `uv run ruff format --check .` 已通过，
  不把引擎识别限制当作未执行格式检查，也不声称独立审查人批准。
- 本地详细日志/原始扫描位于 `.git/codex-pending-security-remediation/`，最终验证指纹为同目录 `validated-source.json`。

依赖更新后的最终验证：526 passed / 89.44%，Ruff/format/Mypy、contract export、运行手册、
供应链配置、对抗集、Shadow smoke、sdist/wheel、契约包导出和三组 Compose config 均通过。
自复审核对生产配置的失败关闭、codec/HTTP 拒绝路径、replay 状态、monkeypatch 自动恢复、
唯一依赖版本变化和文档实际代码映射；无阻断发现。未执行独立多 Agent 审查或真实外部集成。

## 文档同步与旧记录归并

| 事实来源 | 同步文档 | 当前结论 |
|---|---|---|
| `core/config.py`、config tests | README | 生产不能禁用鉴权，local 开发保持兼容 |
| `api/routes.py`、metrics tests、Java management 配置 | README、async-orchestration | Python metrics 免 token；Java management 默认 9086；由网络隔离 |
| `application/planning.py`、governed tools | README、migration-plan、current-system-map | Process 默认只读；受确认约束的退款发起已实现，禁止自动审批 |
| cross-runtime S1/S5/S6 与 session 实现 | migration-plan、async-orchestration、current-system-map | RAG fail closed、回执恢复、独立只读 worker 和 checkpoint 已实现 |
| Python Actions run 36983375366 | cross-runtime-reliability | a7526db CI SUCCESS；首次 main 的旧 run 已 cancelled |

本次开始前完整进度保留在 [历史快照](history/progress-before-pending-security-remediation.md)。
历史 F-05/F-01/F-03/F-12 的产品缺口已由后续 S1/S5/S6 等交付覆盖；F-10 的共用预算已有 S3，
不能把独立的租户运营费用熔断需求自动等同于共用 token 预算。F-04 字符串过滤、F-06 PII
范围扩展和 F-11 Trace 契约统一继续作为可选演进，不冒充当前缺陷或本轮已实现。
历史治理运行的状态不被产品后续修复追溯改为成功。

## 外部验收与回退边界

- 真实模型开放式答案门禁已有本地失败记录，未通过；Shadow v4/对抗/相同数据集回放待命名
  非生产环境、模型与费用限制。MCP/Sandbox 还需 provider URL、服务身份与隔离/出网测试条件。
- 旧服务运行时 OpenAPI 导出与 breaking-change 比较仍待可用旧服务，不能由静态 DTO 替代。
- 生产证据的 19 项 owner、candidate/rollback digest、恢复、容量、灰度及值班证据仍缺失，
  `NO-GO` 保持。用户明确暂无环境，本轮不启动或配置真实外部 provider。
- Java 安全整改准备见 [准备报告](dependency-remediation-readiness.md)。没有更改其 POM 或锁定契约。
- 本轮无需数据库或外部 API 迁移；回退测试/文档不会改变业务协议。鉴权保护和安全补丁不得
  通过关闭生产鉴权或退回已知漏洞版本规避；部署回退需仍满足相同安全不变量。

## 镜像扫描补充整改

首次 main [CI 38507980722](https://github.com/lirji/platform-agentscope/actions/runs/38507980722)
的 Linux 测试、依赖审计、契约、构建均通过，runtime 扫描发现 perl-base 的 7 条记录
（3 CRITICAL、4 HIGH），原版本 `5.36.0-7+deb12u3`、修复下限 `5.36.0-7+deb12u4`。
完整扫描来自制品 11868059757，保存在本地 `python-ci/trivy-image.json`。
L4 只在原 Dockerfile 的定向更新增加 `perl-base` 和最低版本断言，不改变 base generation、
业务源码、CI 严重度或豁免规则。本地 runtime 的包升级与版本断言通过；ARM64 builder 下载 multidict wheel 在三次重试后超时，
不是测试失败。未获得最终镜像，因此本地隔离网络 smoke 未执行。使用 GitHub Linux 任务分支
CI 验证精确 Dockerfile 的构建与扫描。

[补丁 CI 38508544838](https://github.com/lirji/platform-agentscope/actions/runs/38508544838)
对应 `fd3a44b5a3936df8fc26c385db62fa055bb2b221`，结论 **SUCCESS**：锁定安装/审计、
契约、Ruff/format/Mypy、全量测试、Shadow、SBOM/包构建、Compose、runtime 构建及扫描全通过。
只执行 quality，tag-only release 被跳过。首次失败记录保留，不解释为测试失败或伪造生产发布。

## Git 交付

任务分支 `fix/pending-security-remediation`，依次提交：

- `07af2d8`：multidict 安全升级及供应链说明。
- `16f8deb`：生产鉴权保护、JWT/回环测试与功能运行文档。
- `9abcc5d`：进度同步、历史快照与 Java 依赖整改准备。
- `fd3a44b`：镜像 Perl 安全补丁及首次 CI 失败记录。

已在原有 verification worktree 正常快进 main：`a7526db → 9abcc5d → fd3a44b`，推送成功。
后续仅本报告和根进度收尾；完整 HEAD 以远程 main 为准，源码 CI 证据固定到 fd3a44b。
每次 main 推送按现有工作流再次运行，[最新运行列表](https://github.com/lirji/platform-agentscope/actions/workflows/ci.yml)
用于查询后续文档提交的 CI，不把旧 run 冒充新 SHA 的执行结果。

最终源码和锁文件与 526 项本地验证指纹一致；Dockerfile 由上述远程 CI 单独验证。
Java 仓仍为 `0b8267340129a46407e649caae6badd51acf017f` 且干净，本轮没有 Java 变更。
本仓 tracked 改动均已交付；`.engineering/remediation/`、`.workflow/` 是保留的历史未跟踪
记录。既有 verification worktree 没有未提交/未跟踪改动，但有忽略的覆盖率/测试缓存。
原目录 `.env`、`.venv`、IDE 配置、reports、dist 与缓存保留，未复制其秘密到 Git。
`.pytest_cache/.ruff_cache/.mypy_cache/__pycache__`、构建 dist 和 verification worktree
可在另行清理授权后评估清理；历史治理证据、环境配置及本次 `.git/` 验证日志应先妥善保存。
本轮未新建工作树、未清理用户目录，也未执行生产部署或 tag/release。
