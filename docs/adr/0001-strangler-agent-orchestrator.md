# ADR-0001：采用独立 AgentScope 编排服务与绞杀者迁移

## 状态

Accepted

## 背景

现有平台是 Java 21/Spring Boot 多服务系统。Agent 推理和编排集中在 `agent-service`，
但鉴权、知识检索、流程、订单、异步任务、互操作和评测已经形成独立领域服务。

AgentScope 2.0 能更直接地支持 Agent、工具、权限、会话、事件、多 Agent 和 sandbox。
全平台 Python 重写会重复实现成熟领域逻辑，并显著扩大安全与回归风险。

## 决策

1. 新建独立 Python 项目 `agentscope-platform`。
2. 只迁移 Agent 编排有界上下文。
3. 现有 Java 服务作为 HTTP/MCP 工具后端。
4. 通过自有 domain/application ports 隔离 AgentScope。
5. 保持旧 `/agent/**` 契约。
6. 使用双跑、shadow、按能力/租户灰度和可回滚切换。
7. AgentScope 2.0 直接提供核心框架，不依赖进入归档路线的独立 AgentScope Runtime。

## 结果

收益：

- Agent 能力开发速度和生态适配能力提高。
- 领域服务、数据与安全投资得到复用。
- 迁移可灰度、可比较、可回滚。
- 框架升级被限制在适配层。

代价：

- 过渡期维护 Java/Python 双栈。
- 内部 JWT、审计、成本和任务语义需要 Python 兼容实现。
- 契约与评测设施必须先行。
- 团队需要 Python/异步运行时运维能力。

## 被否决方案

### 全平台改写

工程量、数据迁移和安全回归风险过高，与采用 AgentScope 的直接收益不匹配。

### 一次性替换 agent-service

缺少双跑与灰度，任何契约、租户、异步或副作用差异都会直接影响现有客户端。
