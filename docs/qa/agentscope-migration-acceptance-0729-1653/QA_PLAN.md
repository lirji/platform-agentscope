# AgentScope 迁移验收 QA 计划

## 目标

验证独立 `agentscope-platform` 是否能够作为 `langchain4j-platform/agent-service`
的候选替代实现，而不是验证旧 Java Agent 到 `async-task-service` 的镜像链路。

## 范围

- 当前 `agentscope-platform` 未提交实现；
- 旧 Java `agent-service` 作为 Shadow 基线；
- Java `async-task-service` 作为中央异步任务权威；
- localhost LiteLLM 与现有平台只读服务；
- 不修改 edge 当前默认路由，不执行生产灰度。

## 用例

| ID | 场景 | 预期 |
|---|---|---|
| AS-01 | 契约、静态检查、类型、测试、覆盖率、构建 | 所有仓库门禁通过 |
| AS-02 | AgentScope `/agent/run` 最小 ReAct | 200、DONE、只调用 `current_time` |
| AS-03 | 旧/新 Shadow | 契约、完成率、工具准确率与延迟门禁通过 |
| AS-04 | `/agent/v2/run` 开关与回滚入口 | 开启时 200，关闭实例返回 404 |
| AS-05 | AgentScope 异步 ReAct | 中心 kind=`agent.run`，最终 SUCCEEDED/DONE |
| AS-06 | AgentScope 异步 DAG | 中心收到 worker、synthesis、critic/replan 进度 |
| AS-07 | SSE 断点续订 | `Last-Event-ID` 后仅回放后续连续事件 |
| AS-08 | 鉴权与租户隔离 | 匿名/伪造/过期 401，跨租户任务 404 |
| AS-09 | 指标 | 认证后可抓取，低基数且不泄漏 taskId/userId |
| AS-10 | 时间敏感 Critic | 正确工具时间不应被误判并触发无效 replan |

## 成本与安全约束

- 只访问 localhost；
- 使用短时本地 HS256 内部 JWT，不保存原始 token；
- 真实模型仅执行少量 `current_time` 用例；
- 不调用写工具、外部 webhook或生产服务；
- 临时 AgentScope 实例使用 `:18084`，测试后停止；保留原 `:18085` 回滚实例。
