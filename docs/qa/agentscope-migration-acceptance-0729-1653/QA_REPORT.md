# AgentScope 迁移验收 QA 报告

## 结论

**PASS，适合继续 localhost/test 灰度；尚未完成 edge 切流，不能宣称生产替换完成。**

正确的 AgentScope 迁移链路已经通过同步 ReAct、旧/新 Shadow、候选路由、中央异步任务、
DAG 细粒度事件、SSE 断点续订、鉴权、租户隔离和指标测试。

本轮发现并修复一个稳定复现的 P2：时间敏感 DAG 答案会被 Critic 错误判定，造成不必要
replan。修复后真实回归由 2 次 attempt、`acceptedByThreshold=false` 改为 1 次 attempt、
`acceptedByThreshold=true`。

## 环境

- 仓库：`agentscope-platform`，HEAD `9921bd6` 加当前未提交迁移实现；
- Python：uv 环境 Python 3.12；
- 候选基线实例：`127.0.0.1:18085`，健康，candidate route 默认关闭；
- 临时验收实例：`127.0.0.1:18084`，测试时开启 candidate route 和异步能力，测试后已停止；
- 旧 Java Agent：`127.0.0.1:8085`；
- 中央任务：`127.0.0.1:8086`；
- LiteLLM：`127.0.0.1:4000`；
- Java platform Compose：25/25 服务运行。

## 仓库门禁

```text
契约快照检查                 PASS
Ruff lint                    PASS
Ruff format --check          PASS
mypy                         PASS（54 source files）
pytest + coverage            PASS（205 passed）
覆盖率                       88.94%（门槛 80%）
Shadow smoke                 PASS（8 samples）
sdist / wheel build          PASS
Compose config               PASS
```

## 黑盒结果

| ID | 结果 | 实际证据 |
|---|---|---|
| AS-02 | PASS | `/agent/run` 200，tenant=`acme`、DONE、1 step、唯一 action=`current_time` |
| AS-03 | PASS | 单案例真实 Shadow：旧/新均 100% pass/completion/tool accuracy，无契约错误 |
| AS-04 | PASS | 临时实例 `/agent/v2/run` 200；默认关闭实例 readiness=DISABLED 且接口 404 |
| AS-05 | PASS | 任务 `cd512c31-36e8-482a-8104-d51afbcb2e50` 为 SUCCEEDED/DONE；中心 kind=`agent.run` |
| AS-06 | PASS | DAG 任务 `178bc60d-ee67-43a9-91a6-21de007c3bc3` 成功，中心持久化 21 个连续事件 |
| AS-07 | PASS | 全量事件 id 1–21；`Last-Event-ID: 10` 仅返回 id 11–21，共 11 条 |
| AS-08 | PASS | 匿名/伪造/过期 token 为 401；`globex` 读取 `acme` 任务及 SSE 均为 404 |
| AS-09 | PASS | 认证 metrics 200，6 条自定义 series，不含 taskId/userId |
| AS-10 | PASS | 修复后真实时间 DAG 首轮 Critic 全维度 1.0，1 attempt 即接受 |

Shadow 单样本记录：

| 目标 | HTTP | stop reason | 工具 | 延迟 |
|---|---:|---|---|---:|
| Legacy Java Agent | 200 | DONE | `current_time` | 2587 ms |
| AgentScope candidate | 200 | DONE | `current_time` | 1958 ms |

该延迟只是一轮冒烟，不作为性能结论。

## AgentScope 异步迁移证据

旧 Java Agent 的兼容镜像使用通用 kind=`agent.task`；AgentScope 候选不是这条链路。
AgentScope 会按入口创建真实 kind：

- ReAct：`agent.run`
- DAG：`agent.dag`
- 其它异步入口对应各自 allowlist kind

DAG 中心 SSE 实际包含：

```text
PENDING
RUNNING
dag-levels
dag-level-start
dag-worker-start
dag-worker-result
dag-level-complete
dag-synthesis-start
dag-synthesis-result
dag-critique
dag-replan
dag-replanned
...
SUCCEEDED
```

因此旧 Java `agent.task` 无法追加细粒度事件的问题，不是 AgentScope 迁移实现的缺陷。

## 已修复缺陷

### AS-BUG-01：时间敏感答案被 Critic 误判并触发无效 replan（P2，已关闭）

复现：

1. 提交一个只调用 `current_time` 的单节点 DAG；
2. 工具返回与系统时间一致的 UTC 时间；
3. Critic 连续两次把 2026 日期或 2 秒执行延迟判为 correctness=0；
4. 结果产生 2 个 attempt，仍可能 `acceptedByThreshold=false`。

修复：

- Critic user payload 注入由服务器生成的可信 UTC 评测时间；
- system prompt 明确 ±120 秒属于正常工具、综合和网络延迟，必须判为当前且正确；
- clock 支持测试注入，naive datetime 明确按 UTC 处理；
- 原始内部 token、租户凭据仍不会进入评审 prompt。

真实回归：

```text
修复前重试：attempts=2, accepted=false, correctness=0.0/0.0
最终修复后：attempts=1, accepted=true, correctness=1.0
```

修改文件：

- `src/agentscope_platform/infrastructure/agentscope/reviewer.py`
- `tests/test_reviewer.py`

## 剩余发布边界

- `langchain4j-platform` 当前 edge Compose 的 `AGENT_URI` 仍指向旧
  `http://agent-service:8085`；这是迁移路线图中尚未执行的 Phase 5，而非本轮候选代码失败。
- 本轮证明候选服务与旧平台内部 JWT、工具服务和中央任务兼容，但没有把真实前端流量切到候选。
- 生产前仍需按测试租户执行 edge 灰度、回滚演练、代表性多案例 Shadow、容量和告警门禁。

## 清理

- 临时 `:18084` AgentScope 实例已停止；
- 原 `:18085` 候选实例保持运行且 candidate route 仍为 DISABLED；
- Java platform 保持 25/25 运行；
- 中央数据库保留两条本轮终态 QA 任务及事件，未执行删除或清库。
