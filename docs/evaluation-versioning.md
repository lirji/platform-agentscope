# 运行版本与评测数据闭环

## 目标与边界

Agent 的结果只有绑定实际 prompt、model 配置和 tool contract 才能复现。运行时因此为三类输入
计算规范 JSON 的 SHA-256 版本，并写入内部 `agent-trajectory.v1`：

- `promptVersion`：系统 prompt 内容摘要；
- `modelVersion`：模型名和影响输出的运行参数摘要；
- `toolsetVersion` 与 `toolVersions`：启用工具集合及每个 `ToolMetadata` + 实现 revision 的摘要。

摘要不包含 prompt 原文、goal、tool 参数、observation、token、grant 或凭据。旧
`/agent/run` JSON 保持不变；同步响应只增加
`X-Agent-Prompt-Version`、`X-Agent-Model-Version` 和 `X-Agent-Toolset-Version`。评测报告仅保存
这些摘要。若启用 `--require-version-metadata`，任一目标缺少版本头或同一批次发生版本漂移都会
fail closed。

实现变更如果未改变 `ToolMetadata`，必须同步递增 `TOOL_IMPLEMENTATION_REVISION`。模型网关 alias
背后的 provider 映射仍需由 LiteLLM 配置版本/发布证据补充；本摘要只证明本服务看到的模型配置。

## 版本化数据集

`agent-evaluation-dataset.v1` 包含 dataset ID、类型、创建时间、只读 cases 和内容摘要。摘要绑定
ID、类型、case 顺序与完整 case 内容；修改后沿用旧 `version` 会被拒绝。类型包括：

- `baseline`：批准的回归基线；
- `adversarial`：每个 case 必须显式声明至少一个 `forbiddenTools`；
- `feedback`：由已同意用于评测的线上只读反馈导入。

将旧 JSONL 转成版本化数据集：

```bash
uv run agentscope-eval-dataset migrate \
  --input eval/baseline/readonly-cases.jsonl \
  --output reports/readonly-dataset.v1.json \
  --dataset-id readonly-baseline \
  --kind baseline

uv run agentscope-eval-dataset validate reports/readonly-dataset.v1.json
```

仓库示例 `eval/datasets/agent-safety-adversarial.v1.json` 覆盖 prompt injection、副作用越权与
凭据外泄。它是离线/测试数据，不授权向生产目标发送请求。

## 可验证回放

首次双跑：

```bash
uv run agentscope-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --dataset reports/readonly-dataset.v1.json \
  --require-version-metadata \
  --output reports/readonly-shadow-v4.json
```

回放时同时提供原报告。CLI 会先验证原报告的 dataset ID/version 与当前数据集完全一致，再把原
报告 SHA-256 和生成时间写入新报告；不匹配时退出码为 2：

```bash
uv run agentscope-shadow-eval \
  --legacy-url http://localhost:28085 \
  --candidate-url http://localhost:18085 \
  --dataset reports/readonly-dataset.v1.json \
  --replay-report reports/readonly-shadow-v4.json \
  --require-version-metadata \
  --output reports/readonly-replay-v4.json
```

这是“用同一版本 case 重新执行”的回放，不会自动重放历史副作用或保存历史回答正文。

## 线上反馈导入

输入为一行一个 `agent-online-feedback.v1`。每条记录必须：

- `consentForEvaluation=true`；
- `readOnly=true`；
- 提供稳定 feedback ID、goal、rating、expectedTools 和 forbiddenTools；
- 不包含 tenant/user/token 等额外字段（严格 schema 会拒绝）。

```bash
uv run agentscope-eval-dataset import-feedback \
  --input reports/consented-feedback.jsonl \
  --output reports/feedback-dataset.v1.json \
  --dataset-id feedback-nightly
```

导入只保存 feedback ID 的不可逆摘要前缀，并遮蔽邮箱、中国手机号和身份证号；原始 ID、rating
和未脱敏记录不进入数据集。该规则不是通用 DLP，导入前仍须由数据治理流程完成来源授权、敏感
字段清理和留存审批。反馈数据集只能走只读 shadow，不得用于自动执行写工具。

## 发布、回滚与保留

- 发布证据至少保留 dataset ID/version、report digest、三类运行版本、阈值和审批记录。
- 报告 v4 缺数据集版本、目标版本漂移、无版本头或回放版本不一致时不得进入 canary。
- CLI/评测故障只停止评测 job，保持当前 primary；不得通过关闭安全检查让报告变绿。
- 回滚 prompt/model/tool 后必须生成新的运行版本并重新评测，不能把旧报告标记为新版本结果。
- 反馈原始导出按批准的短期保留策略删除；版本化数据集和脱敏报告按发布证据策略保留。
