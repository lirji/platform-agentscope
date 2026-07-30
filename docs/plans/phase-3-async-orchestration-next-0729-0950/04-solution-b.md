# 候选方案 B：中央拉取队列 + 可恢复 Worker

## 1. 方案定位

将 `async-task-service` 从“状态登记簿”扩展为任务派发源。Python worker 主动按 kind
claim PENDING 任务、取得租约、读取输入并执行，因此进程重启后可由其他 worker 接管。
orphan reaper 只负责最终无法重试或超过总时限的任务。

它与方案 A 的根本区别是：提交 HTTP 请求不再持有执行生命周期，执行由独立拉取循环驱动。

## 2. 架构与模块职责

### 中央服务

- 增加按 tenant/kind/状态领取任务的 claim API，原子完成
  `PENDING -> RUNNING + workerId + lease`。
- 保存可完整重建请求的业务输入、执行身份或受限执行凭证引用。
- 增加 attempt、not-before、最大重试或不可恢复标记，支持重新领取。
- orphan reaper 将过期 RUNNING 退回可领取或在超过阈值后置 `FAILED`。

### Python

- API 提交仅 create 后返回 `202`。
- 独立 poller 拉取五类任务并交给现有 service。
- worker 使用 claim 得到的身份上下文访问旧平台。
- 查询、取消、SSE 仍直接代理中央。

## 3. 核心流程

1. API 验证来访 token，将业务请求和执行身份材料写入中央任务。
2. worker 长轮询/定期 poll，原子 claim。
3. worker 重建 `RunContext`，执行并 heartbeat。
4. 进程失败后租约过期，任务可被重新 claim；超过 attempts/总截止时 reaper 失败。
5. cancel 与 claim/完成均以中央 CAS 决胜。

## 4. 关键前提与待补能力

当前代码无法直接支撑本方案：

- 中央 `AsyncTask` 没有 scopes、department、身份凭证引用、attempt、not-before。
- Python 当前把调用者原始 token 传给旧平台；中央 JWT 默认有效期仅五分钟。
- “token 不持久化”意味着任务重启后没有凭据访问旧平台。
- 中央没有 claim/list-by-kind-for-worker API，也没有服务身份换取受限委托 token 的设施。

要实现可恢复执行，必须额外选择其一：

1. 建立短期委托 token broker，由 worker 根据受保护的任务身份换取新 token；或
2. 加密持久化可刷新凭证；或
3. 将所有下游调用改成可信服务身份并显式传递租户/用户上下文。

第 2 项直接违背硬约束；第 1、3 项均是跨平台安全架构变更，不能作为本期隐含实现。

## 5. 改动范围

- 中央协议、数据库表、claim API、store、worker 身份模型、reaper 语义全面扩展。
- Python 增加独立 worker 进程/loop、claim client、重建上下文、可恢复 attempt 管理。
- 部署增加 worker 副本、leader/claim 参数和资源隔离。
- 旧平台安全组件需要支持受限委托；实际类/方法尚未在本次范围内发现，标记为“待验证”，
  不能在实施计划中虚构。

## 6. 扩展性与实施成本

- 水平扩容、故障转移和任务削峰能力最好。
- 可将其他领域任务逐步接入统一 worker 协议。
- 实施成本最高之一；需要安全团队、协议兼容和数据库迁移协同。

## 7. 风险评审

### 兼容性

- HTTP 响应可保持，但 create 后尚未 claim，`PENDING` 时间更长。
- 任务输入 schema 和身份传播发生重大变化，跨模块兼容面广。
- 如果重试非幂等推理/工具，结果与旧服务单次执行语义不同。

### 事务、并发与幂等

- claim 必须为数据库原子条件更新；多 worker 只能一个获胜。
- 租约过期不代表旧 worker 已停止，重领会造成双执行；仅靠 lease 无法做到 exactly-once。
- 现有工具虽为只读，模型调用本身仍有费用与非确定性；重试会产生重复成本和不同输出。
- create、claim、attempt、terminal、event/outbox 需要清晰的事务边界。

### 性能

- poll 造成数据库压力，需长轮询、分区或消息唤醒。
- 大量持久化输入/身份材料增加存储与清理成本。

### 安全

- 这是本方案的致命难点：不持久化 token 与跨重启恢复执行无法同时在现有认证模型下成立。
- token broker 若范围过大，会引入租户越权；必须绑定 taskId/tenant/user/scopes/department/
  audience/expiry 并可审计。

### 数据迁移

- 需要新增 attempt、调度字段、身份/凭证引用及索引，可能还要新表。
- 旧任务的默认值、回填和旧 producer 兼容均需迁移设计。

### 灰度与回滚

- 必须双写或按 kind 切换 producer；旧 push 与新 pull 不能同时执行同一任务。
- 回滚时需冻结 claim、排空 worker、明确处理中任务归属，操作复杂。

## 8. 典型失败场景

- claim 后 worker 卡死但未停止，租约到期被第二实例执行。
- 委托 token 服务不可用导致全局积压。
- 身份字段缺失使重启任务无法复现原始权限。
- 版本升级后旧 input 无法被新 worker 反序列化。
- retry 产生不同模型答案，破坏双跑评测解释性。

## 9. 结论

本方案解决了方案 A 的进程恢复弱点，但需要一个当前不存在且高度敏感的委托身份机制。
在“token 不持久化”和本期范围不扩展认证体系的条件下，不具备直接实施前提。可作为未来
阶段的目标架构，不能作为本次批准后的默认执行方案。
