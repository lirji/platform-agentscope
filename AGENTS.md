# Codex Agent 工作规则

## 项目目标

本项目是 `langchain4j-platform` 的新一代 Agent 编排服务。使用 AgentScope 2.0
逐步替换原 `agent-service` 的推理与多 Agent 编排，不重写已有 Java 领域服务。

旧项目行为基线位于同级目录 `../langchain4j-platform`。迁移时必须以旧项目的
HTTP/JSON/SSE 契约、安全语义和评测结果为准。

## 架构约束

1. AgentScope 类型只能出现在 `infrastructure/agentscope/` 适配器内，不得进入
   `domain/`、`application/` 或对外 API DTO。
2. `domain` 不依赖 FastAPI、HTTPX、AgentScope、数据库或消息队列。
3. 对外契约必须保持语言中立，使用 Pydantic/OpenAPI/JSON Schema 表达。
4. 所有业务请求默认要求有效 `X-Internal-Token`；健康探针除外。
5. 租户、用户、scope、部门和 trace 必须通过显式上下文传播，禁止全局变量。
6. 有副作用工具必须声明副作用等级、幂等策略和人工确认要求。
7. 不在首阶段复制 knowledge、workflow、analytics、order 等领域逻辑；通过 HTTP/MCP
   工具调用旧平台。

## 开发流程

1. 开始任务前读取 `CODEX_PROGRESS.md`（若存在）和相关迁移文档。
2. 先补契约/测试，再迁移能力。
3. 使用 `uv sync --dev` 安装依赖。
4. 提交前运行：

   ```bash
   uv run ruff check .
   uv run mypy src
   uv run pytest
   ```

5. 每个迁移能力必须补充：
   - API 契约测试
   - 跨租户安全测试
   - 工具调用与失败映射测试
   - 旧/新双跑评测用例
   - 回滚说明

## 禁止事项

- 不提交密钥、访问令牌或生产地址。
- 不让 AgentScope 状态对象成为外部任务存储格式。
- 不对有副作用工具做无条件自动重试。
- 不在未通过双跑门禁前直接替换生产 `AGENT_URI`。
