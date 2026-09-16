# Contracts

本目录是跨语言边界的事实源：Python 与 Java 之间只交换这些 JSON 契约，不传 AgentScope 或
LangChain4j 框架对象。`boundaries/` 为当前边界，`legacy/` 为替换 Java `agent-service` 期间冻结的
兼容面，`capabilities/` 为发布的能力目录实例，`evaluation/` 为评测 case 与 report。

## manifest.json

`manifest.json` 逐个 JSON 契约固定 `sha256`，供其它语言的消费方钉住具体版本：

```json
{ "schema_version": "1", "files": { "boundaries/...": "sha256:..." } }
```

它覆盖手写契约（例如 `boundaries/conversation-generation.schema.json`），因此手写 schema 的改动
也会被检测到——这类文件不由 Pydantic 重新生成，manifest 是唯一能发现改动的地方。相邻的
`README.md` 不参与固定，改文档不会报契约过期。

改动契约后运行：

```bash
uv run python scripts/export_contracts.py          # 重新生成 + 刷新 manifest
uv run python scripts/export_contracts.py --check  # 验证/CI
```

## 消费方

`langchain4j-platform` 只复制 Java 真正消费或生产的契约到
`platform-protocol/src/main/resources/contracts/agentscope/`，并用本目录 manifest 的 digest 固定；
同步与漂移检查由该仓 `deploy/sync-agent-contracts.sh` 执行。本目录是唯一权威，消费方不得在
自己仓库里修改契约语义。
