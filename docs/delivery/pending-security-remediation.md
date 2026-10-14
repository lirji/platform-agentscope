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
| L1 | 交付生产鉴权保护、JWT 与回环测试修复 | 本地验证通过，提交 16f8deb |
| L2 | multidict 6.7.1 → 6.9.1 安全补丁 | 审计与依赖变更后全量复验通过，提交 07af2d8 |
| L3 | 同步迁移/运行/CI 文档，整理历史状态 | 完成，待 Git 交付 |
| D0 | Java 最新 SBOM 与兼容路线准备 | 完成；未执行 Java 升级 |
| G1 | 分批提交、main 合并推送、远程 CI | 待执行 |

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

## Git 交付

L2 提交 07af2d8，L1 与功能文档提交 16f8deb；L3/D0 为本次记录提交。
原 main 在既有 verification worktree，已核对其无未提交/未跟踪冲突，随后正常快进。未获清理授权，不删除历史工作树、治理目录或缓存。
