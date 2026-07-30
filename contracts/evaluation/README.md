# Evaluation contracts

本目录是旧/新 Agent 双跑 case 与 report 的语言中立事实源。Schema 由
`agentscope_platform.evaluation.models` 生成，但消费者只依赖提交的 JSON Schema，不依赖
Pydantic 或 AgentScope 类型。

更新模型后运行：

```bash
uv run python scripts/export_contracts.py
uv run python scripts/export_contracts.py --check
```

运行评测使用独立 CLI：

```bash
uv run agentscope-shadow-eval \
  --legacy-url http://127.0.0.1:8085 \
  --candidate-url http://127.0.0.1:18085
```

CLI 是 CI/Nightly/发布门禁，不是在线 Agent API 的请求依赖。真实 token 只通过环境变量
`SHADOW_INTERNAL_TOKEN`、`SHADOW_LEGACY_TOKEN` 或 `SHADOW_CANDIDATE_TOKEN` 注入。
