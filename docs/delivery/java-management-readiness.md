# Java 管理端口兼容修复

用户确认范围：2026-10-14，修复并发布本地AgentScope，完成Java平台Docker整栈启动；不涉及生产部署。

## 问题与行为

Java actuator已移到独立管理端口，AgentScope原来仍从业务地址追加`/actuator/health/readiness`，得到404；必需的async-task探测失败使`/readiness`返回503。

新增五个可选`*_MANAGEMENT_BASE_URL`配置，分别对应ASYNC_TASK、KNOWLEDGE、ANALYTICS、WORKFLOW、ORDER。留空回退既有业务地址，已配置时仅探测管理地址；业务HTTP请求地址不变，必需/可选依赖和失败语义不变。管理地址失败不会再尝试业务地址。Java整栈Compose显式配置9086/9084/9083/9082/9093，独立Compose通过DOCKER_前缀传入可达地址。

## 验证

- 新增管理地址测试在原实现FAIL（仍访问五个业务地址）；修复后6项探针测试PASS。
- 覆盖配置管理地址、留空兼容、404/503保持DOWN、禁用async不探测、业务地址保持。
- 全量530 passed，覆盖率89.38%；Ruff/format/Mypy通过。
- 契约快照、供应链静态门禁、离线Shadow 8样本、三组Compose渲染通过。无API契约变更、无真实模型请求。
- Java仓observability新增管理端口一致性检查，production-cutover/runtime-hardening通过。

## 交付与回退

两仓使用fix/java-management-readiness任务分支，先交付Python配置支持，再交付JavaCompose。部署使用提交固定镜像；本地健康证据由Java仓docs/delivery/rag-quality-loop/DEPLOYMENT_RESULT.md统一记录。
回退本次配置可留空沿用原行为，但新Java管理端口分离时会重新出现readiness失败，不能标记为健康。没有数据库变化。
原有未跟踪`.engineering/remediation/`和`.workflow/`及既有main工作树保留，不纳入本次提交。
