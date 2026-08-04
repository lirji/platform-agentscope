# 开发指南

## 环境

```bash
uv sync --dev
cp .env.example .env
```

Python 固定为 3.12，AgentScope 固定为 2.0.5。升级 AgentScope 必须先阅读 release notes，
运行完整契约和评测套件，再单独提交依赖升级。

## 新增工具

1. 在 `application` 定义必要的领域端口。
2. 在 `infrastructure/http`、`infrastructure/mcp` 或 `infrastructure/sandbox` 实现客户端。
3. 工具从 `current_run_context()` 获取身份，不能让模型传 tenantId。
4. 返回前限制大小、处理敏感字段、标记来源。
5. 用 `GovernedFunctionTool` 注册，并声明完整 `ToolMetadata`；不能直接绕过 Tool Policy。
6. 补工具单测、HTTP stub 集成测试和双跑评测。

工具元数据至少包含：

- `read_only`
- `side_effect`
- `idempotency`
- `requires_confirmation`
- `required_scopes`
- `timeout`
- `retry_policy`

Phase 4 已提供统一 Tool Policy。写工具默认关闭，确认和幂等只能来自可信请求上下文；远端
MCP/sandbox 失败不得回退到本地执行。每项能力必须有独立关闭开关和 `stub_only` 评测用例。

## 新增 API

- DTO 放 `domain`，保持语言中立。
- 用例放 `application`。
- FastAPI 路由只负责解析、认证、调用和错误映射。
- 用 alias 保持旧 camelCase JSON。
- 不返回 AgentScope `Msg/Event/State`。

## 配置

- 所有密钥来自环境变量或 secret manager。
- `.env.example` 只放占位符。
- 本地可临时关闭内部认证；共享环境必须开启。
- RS256 下游只配置公钥；确需签发时另建显式 signer 配置和密钥权限。

## 日志

允许记录：

- traceId、tenantId、userId。
- tool 名、持续时间、状态。
- model 名、token、成本。

禁止记录：

- 内部 JWT、API key。
- 完整 Authorization。
- 未脱敏 PII。
- code/browser sandbox 的秘密环境变量。
