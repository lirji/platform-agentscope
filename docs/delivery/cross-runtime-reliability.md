# 跨运行时可靠性整改

本会话按 Claude Engineering Skill 的测试保护、纵向切片、验证和复审流程执行。
规范计划与聚合状态在同级 langchain4j-platform 的
`docs/delivery/cross-runtime-reliability/DELIVERY_PLAN.md`、`DELIVERY_STATUS.md`。
Java 保持业务/任务/预算数据权威，AgentScope 保持推理与编排，生产部署单独验收。

## S1 RAG 租户边界

Java RAG 回填验签租户。Python 工具只接受与当前运行一致且非空的 tenantId；缺失/null/空值
无法证明片段归属，直接返回工具错误，不将命中内容交给模型。不修改协议或正常匹配行为。
旧代码新增三个用例全部失败；修复后工具 11 项、全量 483 项通过，ruff/format/mypy 通过。

历史 ESS run 的阻塞状态保留；本轮采用用户后续明确授权的交互式实施，不伪造历史 run 成功。

## S3 共用预算

所有模型工厂调用（含 planner/reviewer/analytics/text/stream）经 Java authority 预留与结算。
专用 service JWT 绑定租户、用户、操作和额度，不授予普通用户签名权限。
仅完整且已完成的 usage 结算；中断、取消或缺失 usage 保持预留。
模型调用禁止应用层重试，RPC 仅重试原操作。提供商 token 估算可能超额，实际 usage 仍全量记录。
配置默认关闭，需要与 Java 同时启用并注入独立服务凭据；schema/HTTP 组合固定由后续契约门禁落实。
细节、开启/回滚和本地验证见规范目录 S3_SHARED_BUDGET.md。
聚焦 38 项、全量 492 项、ruff/format/mypy、Compose 静态校验通过；未调用真实模型。

## S5：退款回执

发起请求结果未知时，仅按原用户、租户、幂等键和原诉求读取 `/workflow/refund/receipt`，
不重放写操作。`refund_receipt` 是无确认消费的只读工具；未读到回执显示结果未确认，
新发起仍需新有效确认。聚焦 9 项、全量 494 项通过，Java 真 MySQL Flowable 验证通过。

## S6：独立只读 worker

默认 inline；可选 api/worker 角色由 `compose.readonly-worker.yml` 启用。
先执行 Java async-task V3 迁移并开启 dispatch。`ASYNC_TASK_WORKER_ID` 与
Java `ASYNC_TASK_DISPATCH_SERVICE_ID` 一致；两进程使用相同不可变 runtime revision、配置和版本。
生产要求 `ASYNC_TASK_RUNTIME_REVISION=git:<40hex>` 或 `sha256:<64hex>`。
worker 入口 `python -m agentscope_platform.worker`，不监听HTTP；`--health` 检查成功领取轮询的时效。
API 不执行 request 闭包；新 worker 按持久化输入重建，禁用所有外部/写工具，拒绝旧确认 grant。
崩溃恢复可重复只读调用/模型费用；Java epoch 阻止旧写回，预算仍逐模型调用预留。
完整 507 项、mypy/Ruff、真实 MySQL 和独立进程恢复/DAG/假OpenAI验证通过。
完整设计、队列与租户配额、回滚及外部生产限制见 Java 规范 S6_DURABLE_WORKER.md。

## S7：流式候选

独立入口 `agentscope_platform.conversation_candidate:app`, 无Agent容器/状态/任务; 显式Compose overlay。
强制JWT/chat scope, 连续序号、单终态、有界输入输出/并发、背压/断连关闭。
SDK完整终帧去重; 每调用显式关闭parser/HTTP资源。真实Java→独立Python→假OpenAI测试
验证成功/错误/TCP取消; 默认关闭, 不访问真实模型。细节与限制见Java S7_STREAM_SHADOW.md。

## S4：不可变契约组合

46个producer契约文件由manifest固定摘要; 新预算/回执/领取模型同时供HTTP客户端使用。
CI构建确定性ZIP制品带source Git SHA/manifest digest。Java固定producer完整提交与摘要,
CI检出该提交并重新校验export和Java DTO; 无源/无ref/漂移均失败, 不再跳过成功。
旧组合仍从其固定提交读取, 不受同级工作树或latest HEAD影响; 更新组合需显式review/pin。
契约聚焦24项、HTTP/预算/worker组合42项、mypy/Ruff、export及供应链静态门禁通过。

## S8：聚合验收与交付阻塞

干净全量518pass/coverage89.27%, Ruff/format/mypy通过。
运行提交34df909的[远程CI](https://github.com/lirji/platform-agentscope/actions/runs/36979153821)
已成功, 包含依赖审计、契约、回归、构建和runtime镜像扫描。
仅更新已有cryptography/PyJWT/urllib3安全版本和runtime PCRE2包, 未放宽扫描门禁。

Java配套实现本地1406tests/0fail, 真实MySQL/Redis/独立worker/SSE/TCP恢复与取消验证通过。
Java远程SBOM另外发现85条HIGH/CRITICAL、31依赖坐标, 需Boot/Cloud及客户端兼容升级;
用户2026-10-02接受已披露版本扫描例外; 两仓已正常快进合并/push main。升级提案与唯一聚合状态/QA/自复审/交付报告见
`../langchain4j-platform/docs/delivery/cross-runtime-reliability/`。
原有用户dirty文件/目录和历史治理状态保持; 原工作树新增未提交JWT测试旧decode预期
与安全升级更早拒绝冲突, 未修改该用户测试。生产NO-GO保持。

Java cutover修复Linux管道SIGPIPE误报后, [远程36980014838](https://github.com/lirji/langchain4j-platform/actions/runs/36980014838)
SUCCESS (完整reactor、固定契约/SDK、Compose与Helm门禁)。Java SBOM安全扫描仍FAIL, 用户本轮接受其合并例外。

## 本轮main合并例外

2026-10-02用户明确接受已披露既有框架/依赖版本的扫描结果并要求合并main。
本轮不新增框架升级; Java85条版本扫描记录仍FAIL, CI门禁和severity保持。
按Python→Java正常合并/push main; 例外范围与执行事实见Java规范MERGE_EXCEPTION/DELIVERY_REPORT。

## Git交付结果

Python main c4fc90d→1a7ceec先推送, Java main e8f11cb→8bf6ad6后推送,
均为正常快进, git ls-remote与任务提交祖先关系验证成功。后续仅本轮交付记录/进度闭合。
合并后[Python CI36983232314](https://github.com/lirji/platform-agentscope/actions/runs/36983232314)
运行中; 之前相同产品代码的quality成功。最终main文档提交会触发新CI, 不声称全绿。
工程结论COMPLETED_WITH_ACCEPTED_FINDINGS; 原工作树用户dirty贡献与治理目录保留, 生产NO-GO保持。
