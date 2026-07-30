# 候选方案 D：中央持久化事件日志 + 进程内执行器

## 1. 方案定位

保留方案 A 的进程内执行模型和 token 不持久化约束，但将中央任务服务扩展为通用、
持久化的任务事件日志。Python 执行器把生命周期和 DAG 细粒度进度写到中央，所有
`/agent/tasks/{taskId}/stream` 都只代理中央 SSE。

它与方案 A 的根本区别是：中央不仅保存任务快照，还保存可回放的有序事件，从而能够
严格复刻旧 DAG SSE，并让 `Last-Event-ID` 在服务重启后仍有效。

## 2. 架构与模块职责

### agentscope-platform

- 复用方案 A 的领域 DTO、manager、中央 client、心跳/取消/截止机制。
- 为 DAG/plan/analyst/process 编排增加可选 progress sink；默认无 sink 时同步契约不变。
- 按旧 Java 实现的事件名和 data 形状发布：
  `dag-planned`、`dag-replan`、`dag-replanned`、`dag-levels`、
  `dag-level-start`、`dag-worker-start`、`dag-worker-result`、
  `dag-level-complete`、`dag-synthesis-start`、`dag-synthesis-result`、
  `dag-critique`。
- 向中央追加事件，不在本地维持可恢复历史；任务 SSE 仍为纯代理。

### async-task-service

- 新增语言中立的 event append API，接收 event name、JSON data、workerId、事件幂等键。
- 新增持久化事件表和 append/read repository。
- 生命周期状态变更与对应 `status` 事件在同一数据库事务写入。
- SSE 先按 Last-Event-ID 读库回放，再订阅内存 live sink；通过 sequence 去重。
- 新增保留期/清理策略。
- orphan reaper 与方案 A 相同，但其 `FAILED` 状态事件也进入持久化日志。

## 3. 建议事件模型

以下均为拟新增内容，不是现有表：

- `TASK_ID`
- `SEQUENCE`：中央分配、对任务单调递增
- `EVENT_KEY`：producer 生成的幂等键，任务内唯一
- `EVENT_NAME`
- `DATA_JSON`
- `CREATED_AT`
- `WORKER_ID`（可空；生命周期系统事件可无）

唯一约束建议：

- `(TASK_ID, SEQUENCE)`
- `(TASK_ID, EVENT_KEY)`

事件 append 必须验证：

- tenant 与任务一致；
- task kind 属于允许发布进度的范围；
- 非终态；
- workerId 持有未过期租约；
- event name 在该 kind 的白名单中；
- data 大小、深度和字段受限。

## 4. 核心流程

1. 提交、租约、执行和 token 截止遵循方案 A。
2. service 在关键节点调用 progress sink。
3. sink 为每个逻辑事件生成稳定 `event_key`，中央事务分配 sequence 并持久化。
4. 重试同一 `event_key` 返回已存在事件，不重复播报。
5. SSE 连接以 task-scoped sequence 作为 `id`；重连时从数据库读取 `id` 之后的事件，
   再切到实时流。
6. terminal update 在同一中央事务写任务快照、生命周期事件和可用的 Kafka lifecycle
   outbox；HTTP webhook outbox 当前仍由提交后监听器入队，需单独处理或接受残余窗口。

## 5. 改动范围

- 包含方案 A 的全部 Python/Java 改动。
- Python 额外修改 `application/dag.py`、`application/planning.py` 及相关 service
  以发出旧事件。
- 中央额外修改 controller/store/JDBC store/SSE service，新增 event DTO/repository/
  schema/config/清理。
- 数据库新增事件表及多个索引；需要容量评估和保留策略。
- 契约导出、SSE 兼容测试和并发测试显著增加。

## 6. 扩展性与实施成本

- 可服务其他异步领域的统一进度和可靠重放，扩展性最好。
- 事件协议一旦公开，需要版本化、配额和治理。
- 实施成本高，中央服务改动成为本期关键路径；数据量和一致性测试复杂。

## 7. 风险评审

### 兼容性

- 能最完整保持旧 DAG 细粒度 SSE，并改进中央现有“重启丢历史、全局 id 重置”的行为。
- 旧 SSE 是否要求 event `id` 的具体值未见契约保证；应验证客户端只按不透明 ID 使用。
- 新中央事件 API 对其他 producer 必须默认不可见/不可用，避免扩大影响。

### 事务、并发与幂等

- sequence 分配需任务级锁或数据库原子计数，热点任务可能争用。
- append 重试必须以 `EVENT_KEY` 去重。
- 回放与 live 订阅切换存在漏事件/重复事件窗口，必须以 sequence 水位衔接。
- 生命周期状态、event、Kafka outbox可做同事务；现有 HTTP webhook outbox监听器仍存在
  commit 后进程崩溃窗口，除非将其也改为 store 内事务写入。

### 性能

- DAG 每个 worker/level 多事件，写放大明显。
- 慢 SSE 客户端需要背压或断开策略，不能无限缓存。
- 查询必须按 `(TASK_ID, SEQUENCE)` 索引；清理需分批且避免锁表。

### 安全

- 任意 JSON event 容易保存模型输出或敏感输入；需字段/大小白名单与脱敏。
- append API 必须同时验证 tenant、kind、worker lease，不能仅凭 taskId。
- token 仍只在 Python 内存，事件中禁止出现 header/context。

### 数据迁移

- 新表可旁路上线，无需回填旧事件；已有任务只能从当前状态合成一个 status 快照。
- 回滚前产生的表可保留，但旧 SSE service 不认识新 ID 语义；需要版本兼容开关。

### 灰度与回滚

- 先建表和双写事件但仍使用旧内存 SSE；校验一致后按租户启用持久化读取。
- Python 进度发布可按 kind 开关。
- 回滚读取路径时保留写入或同时关闭，避免客户端看到非单调 ID。
- 事件表变更不应在紧急回滚时删除。

## 8. 典型失败场景

- append 成功但响应丢失：稳定 event key 去重。
- 回放结束与 live 订阅之间写入事件：以数据库二次追平水位消除空档。
- 两个 producer 错误持有同一任务：租约校验拒绝非 owner。
- terminal 后迟到进度：拒绝 append，不让 done 后再出现 worker event。
- 大事件拖垮数据库/SSE：严格大小限制并返回稳定 4xx。
- 清理与重连竞争：明确 retention 后的“最早可用事件”语义，必要时先发送当前 status。

## 9. 验证重点

- 旧 Java DAG 事件名、顺序、data shape 的逐帧黄金测试。
- 重启中央服务后 Last-Event-ID 继续回放。
- append 幂等、并发 sequence 单调、回放/live 无漏无重。
- 事件与 terminal、取消、reaper 的竞态。
- 大量 DAG 与慢消费者的容量/背压测试。

## 10. 结论

本方案最能满足“旧 SSE 契约”按严格含义解释时的要求，也消除中央现有内存事件历史的
重启缺口；代价是把本期从“异步入口迁移”扩大为“中央可靠事件平台建设”。若评审确认
旧 DAG 细粒度事件属于发布门禁，应选择本方案或吸收其事件日志部分；若只要求任务生命
周期 SSE，则方案 A 更符合已批准基线。
