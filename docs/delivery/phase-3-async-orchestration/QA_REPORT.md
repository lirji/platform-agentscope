# Phase 3 Async Orchestration QA Report

## 结论

- 自动化实现门禁：PASS。
- 测试环境部署建议：CONDITIONAL GO（保持 async/orphan 默认关闭）。
- 生产切流建议：NO GO，直到真实拓扑故障注入、双跑、容量和回滚演练完成。

## 覆盖

| 领域 | 证据 | 结果 |
| --- | --- | --- |
| 五类 async 契约 | 参数化 FastAPI 测试、OpenAPI/JSON Schema | PASS |
| 租户/kind 隔离 | Python kind 过滤、Java tenant scoped controller tests | PASS |
| token 安全 | expiry 验证、MockTransport header/body、持久 data 负向断言 | PASS |
| 状态/取消 | manager swallow-cancel、Java row-lock transition | PASS |
| lease/heartbeat/shutdown | fake gateway manager tests、现有 Java lease tests | PASS |
| event/SSE | JDBC journal 幂等/sequence、UTF-8 chunk/CRLF、watermark 去重 | PASS |
| orphan | allowlist、stale 判定、scheduler tenant context restore | PASS |
| webhook | outbox retry/dead、十字段 payload、alias header、userinfo reject | PASS |
| Process 只读 | 复用既有只读 Planner/DAG；async case 禁止写工具 | PASS（离线） |
| 静态/构建 | Ruff、format、mypy、Maven、build、Compose | PASS |

## 尚需外部执行

1. MySQL 原地升级、两副本中央服务和两副本 Python。
2. create/lease/cancel 响应丢失与中央重启。
3. Python SIGKILL 后 stale task 只被一个 reaper 终结。
4. cancel/success/reaper/heartbeat barrier 竞态。
5. 慢 SSE、重连、事件 retention 和 webhook 4xx/5xx/network。
6. 旧/新五类 async + Reflexion SSE 真实模型双跑。
7. heartbeat 并发、事件写放大和 P95/P99 容量。
8. 关闭开关、切回旧服务且保留新表的回滚演练。

任何一项出现跨租户、双终态、Process 写调用、token 泄漏或 SSE 漏序，均为发布阻断。
