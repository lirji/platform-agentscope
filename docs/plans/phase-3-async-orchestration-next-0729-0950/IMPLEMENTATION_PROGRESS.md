# Implementation Progress

## 任务目标

按已批准的 `FINAL_PLAN.md` 交付 Phase 3 A+D：Python 进程内执行骨架、中央任务唯一权威、
持久事件 journal、五类 async API、任务 CRUD/SSE、Reflexion SSE、取消/心跳/token 截止、
webhook 兼容和五 kind orphan reaper。

## 当前阶段

- 阶段：8 - 文档与交付报告
- 实现状态：完成
- 发布状态：候选可验证；生产切流仍需外部拓扑门禁和独立审批
- 最后更新：2026-07-29

## 已完成

- Python 十/十四字段 DTO、JWT expiry、中央 HTTP/SSE client、manager 与低基数指标。
- 五个 async submit、task list/get/cancel/SSE 和 Reflexion SSE。
- DAG/Planner/Reflexion optional progress sink；同步调用默认路径保持不变。
- Java JDBC 行锁终态、task-scoped 事件 journal、append 校验、SSE 水位去重。
- 状态/event/Kafka lifecycle outbox/HTTP webhook outbox 的 JDBC 事务提交。
- Agent webhook 十字段 payload、双 header、URL user-info 拒绝、重复 outbox 不复活。
- 定向 orphan reaper、租户上下文恢复、默认关闭和 JDBC Helm 配置。
- OpenAPI/JSON Schema、环境变量、Compose/Helm、运行手册、回滚和异步双跑场景清单。
- 评审修复：队列等待纳入任务硬截止；状态竞争返回 409；SSE replay/live 使用 watermark
  去重；终态后的重复 progress append 仍返回原幂等事件。

## 验证结果

- Python：199 tests passed，覆盖率 89.06%；Ruff、format、mypy、contract check 全绿。
- Python CI 同等门禁：shadow smoke、wheel/sdist build、Compose config 全绿。
- Java：`mvn -pl async-task-service -am test` 全绿；受影响模块 42 tests passed。
- 双仓 `git diff --check` 全绿。

## 未执行的外部门禁

- 未启动真实 MySQL + 两服务拓扑做 SIGKILL、中央重启、双 reaper、慢 SSE、webhook 网络故障注入。
- 未运行旧/新真实模型五类 async 双跑或容量压测。
- 未修改生产 `AGENT_URI`、未部署、未启用 async/orphan 开关。
- DNS rebinding 仍需生产 egress/allowlist。

## 下一步

1. 在测试环境部署中央 JDBC 兼容版，所有新开关保持关闭并核对表/指标。
2. 运行 `QA_REPORT.md` 中的外部故障注入和真实双跑门禁。
3. 通过后另行申请内部租户灰度；生产切流是独立审批。
