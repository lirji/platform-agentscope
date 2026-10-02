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
