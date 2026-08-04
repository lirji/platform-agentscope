from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    Field,
    SecretStr,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentscope_platform.domain.mcp import McpToolBinding
from agentscope_platform.domain.sibling import (
    ChainStepDefinition,
    VotingStrategy,
)

DEFAULT_CHAIN_STEPS_JSON = """
[
  {
    "name": "translate",
    "instruction": "把输入内容翻译成英文，只输出译文，不要额外解释",
    "gateMinLength": 10
  },
  {
    "name": "summarize",
    "instruction": "用一句中文概括上一步英文内容的要点",
    "gateMinLength": 8
  }
]
""".strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8085
    app_log_level: str = "INFO"

    gateway_base_url: str = "http://localhost:4000/v1"
    gateway_api_key: SecretStr = SecretStr("")
    gateway_model: str = "chat-default"
    gateway_temperature: float = Field(default=0.2, ge=0, le=2)
    agent_max_steps: int = Field(default=8, ge=1, le=100)
    agent_max_tokens: int = Field(default=24_000, ge=0, le=1_000_000)
    agent_timeout_seconds: float = Field(default=120, ge=0, le=3_600)
    agent_model_max_output_tokens: int = Field(default=4_096, ge=0, le=131_072)
    # LiteLLM owns provider retry/failover. Retrying again in the orchestrator
    # multiplies latency and cost, so the application layer is fail-once by default.
    agent_model_max_retries: int = Field(default=0, ge=0, le=3)
    agent_max_repeats: int = Field(default=3, ge=2, le=20)
    agent_loop_window: int = Field(default=6, ge=2, le=100)
    agent_rag_top_k: int = Field(default=5, ge=1, le=20)
    agent_rag_min_score: float = Field(default=0, ge=0)
    agent_rag_category: str | None = None
    agent_v2_enabled: bool = False
    agent_dag_max_tasks: int = Field(default=6, ge=1, le=100)
    agent_dag_max_parallel_workers: int = Field(default=8, ge=1, le=32)
    agent_dag_replan_enabled: bool = True
    agent_dag_replan_max_replans: int = Field(default=1, ge=0, le=5)
    agent_dag_replan_threshold: float = Field(default=0.75, ge=0, le=1)
    agent_dag_replan_weight_correctness: float = Field(default=0.5, ge=0)
    agent_dag_replan_weight_completeness: float = Field(default=0.35, ge=0)
    agent_dag_replan_weight_clarity: float = Field(default=0.15, ge=0)
    agent_planner_max_tokens: int = Field(default=1_200, ge=128, le=8_192)
    agent_planner_timeout_seconds: float = Field(default=30, gt=0, le=300)
    agent_planner_max_retries: int = Field(default=0, ge=0, le=3)
    agent_chaining_steps_json: str = DEFAULT_CHAIN_STEPS_JSON
    agent_voting_n: int = Field(default=3, ge=1, le=50)
    agent_voting_max_candidates: int = Field(default=10, ge=1, le=50)
    agent_voting_strategy: VotingStrategy = VotingStrategy.MAJORITY
    agent_voting_min_agreement: float = Field(default=0.5, ge=0, le=1)
    agent_sibling_max_parallel_workers: int = Field(default=10, ge=1, le=50)
    agent_reflexion_threshold: float = Field(default=0.75, ge=0, le=1)
    agent_reflexion_max_attempts: int = Field(default=2, ge=0, le=10)
    agent_reflexion_weight_correctness: float = Field(default=0.4, ge=0)
    agent_reflexion_weight_completeness: float = Field(default=0.4, ge=0)
    agent_reflexion_weight_clarity: float = Field(default=0.2, ge=0)
    agent_session_store: Literal["memory", "redis"] = "memory"
    agent_session_redis_url: SecretStr = SecretStr("")
    agent_session_redis_namespace: str = Field(
        default="agentscope:agent-session",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$",
    )
    agent_session_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    agent_session_lease_seconds: int = Field(default=180, ge=30, le=3_600)

    internal_auth_required: bool = True
    internal_jwt_header: str = "X-Internal-Token"
    internal_jwt_algorithm: str = "HS256"
    internal_jwt_secret: SecretStr = SecretStr("")
    internal_jwt_public_key: SecretStr = SecretStr("")
    internal_jwt_public_key_file: Path | None = None
    internal_jwt_issuer: str = Field(
        default="langchain4j-platform",
        pattern=r"^\S{1,128}$",
    )
    internal_jwt_audience: str = Field(
        default="platform-internal",
        pattern=r"^\S{1,128}$",
    )
    internal_jwt_key_id: str = Field(
        default="platform-internal-v1",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    internal_jwt_token_use: str = Field(
        default="internal_access",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )
    internal_jwt_clock_skew_seconds: int = Field(default=5, ge=0, le=30)
    internal_jwt_max_ttl_seconds: int = Field(default=300, ge=30, le=900)

    knowledge_base_url: str = "http://localhost:8084"
    analytics_base_url: str = "http://localhost:8083"
    analytics_external_planner_shadow_enabled: bool = False
    analytics_external_planner_max_tables: int = Field(default=20, ge=1, le=100)
    workflow_base_url: str = "http://localhost:8082"
    agent_refund_start_enabled: bool = False
    agent_confirmation_header: str = Field(
        default="X-Agent-Confirmation-Grants",
        pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$",
    )
    agent_confirmation_secret: SecretStr = SecretStr("")
    agent_confirmation_issuer: str = Field(
        default="agentscope-platform", min_length=1, max_length=128
    )
    agent_confirmation_audience: str = Field(
        default="agentscope-tool-execution",
        min_length=1,
        max_length=128,
    )
    agent_confirmation_key_id: str = Field(
        default="agentscope-confirmation-v1",
        min_length=1,
        max_length=128,
    )
    agent_confirmation_ttl_seconds: int = Field(default=120, ge=30, le=300)
    agent_confirmation_clock_skew_seconds: int = Field(default=5, ge=0, le=30)
    agent_confirmation_max_grants: int = Field(default=8, ge=1, le=16)
    agent_confirmation_replay_store: Literal["memory", "redis"] = "memory"
    agent_confirmation_redis_url: SecretStr = SecretStr("")
    agent_confirmation_redis_namespace: str = Field(
        default="agentscope:tool-confirmation",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$",
    )
    agent_downstream_jwt_header: str = Field(
        default="X-Agent-Service-Token",
        pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$",
    )
    agent_downstream_jwt_secret: SecretStr = SecretStr("")
    agent_downstream_jwt_issuer: str = Field(
        default="agentscope-platform",
        pattern=r"^\S{1,128}$",
    )
    agent_downstream_jwt_subject: str = Field(
        default="agentscope-orchestrator",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    agent_downstream_jwt_key_id: str = Field(
        default="agentscope-downstream-v1",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    agent_downstream_jwt_ttl_seconds: int = Field(default=60, ge=30, le=120)
    agent_mcp_audience: str = Field(default="mcp-provider", pattern=r"^\S{1,128}$")
    agent_browser_audience: str = Field(default="browser-sandbox", pattern=r"^\S{1,128}$")
    agent_code_audience: str = Field(default="code-sandbox", pattern=r"^\S{1,128}$")
    agent_mcp_enabled: bool = False
    agent_mcp_url: str = ""
    agent_mcp_tools_json: str = "[]"
    agent_mcp_max_arguments_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    agent_mcp_max_result_chars: int = Field(default=32_768, ge=1024, le=262_144)
    agent_browser_enabled: bool = False
    agent_browser_sandbox_url: str = ""
    agent_browser_allowed_hosts_json: str = "[]"
    agent_browser_timeout_seconds: float = Field(default=15, gt=0, le=300)
    agent_browser_max_input_chars: int = Field(default=4000, ge=100, le=20_000)
    agent_browser_max_output_chars: int = Field(default=20_000, ge=1000, le=100_000)
    agent_code_exec_enabled: bool = False
    agent_code_sandbox_url: str = ""
    agent_code_timeout_seconds: float = Field(default=3, ge=0.1, le=300)
    agent_code_max_source_chars: int = Field(default=4000, ge=100, le=20_000)
    agent_code_max_output_chars: int = Field(default=2000, ge=100, le=100_000)
    agent_code_max_memory_mb: int = Field(default=64, ge=16, le=1024)
    agent_code_max_processes: int = Field(default=4, ge=1, le=64)
    order_base_url: str = "http://localhost:8093"
    http_connect_timeout_seconds: float = Field(default=1, gt=0)
    http_read_timeout_seconds: float = Field(default=10, gt=0)
    http_max_connections: int = Field(default=100, ge=1, le=1000)
    http_max_keepalive_connections: int = Field(default=20, ge=0, le=1000)
    http_keepalive_expiry_seconds: float = Field(default=30, gt=0, le=300)
    http_dependency_max_concurrent: int = Field(default=32, ge=1, le=1000)
    http_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    http_circuit_recovery_seconds: float = Field(default=15, gt=0, le=300)
    readiness_probe_timeout_seconds: float = Field(default=2, gt=0, le=10)

    agent_input_cost_usd_per_million_tokens: float = Field(default=0, ge=0)
    agent_output_cost_usd_per_million_tokens: float = Field(default=0, ge=0)

    async_task_enabled: bool = False
    async_task_base_url: str = "http://localhost:8086"
    async_task_worker_id: str = ""
    async_task_worker_jwt_header: str = Field(
        default="X-Async-Worker-Token",
        pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$",
    )
    async_task_worker_jwt_secret: SecretStr = SecretStr("")
    async_task_worker_jwt_issuer: str = Field(
        default="platform-services",
        pattern=r"^\S{1,128}$",
    )
    async_task_worker_jwt_audience: str = Field(
        default="async-task-worker",
        pattern=r"^\S{1,128}$",
    )
    async_task_worker_jwt_key_id: str = Field(
        default="async-task-worker-v1",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    async_task_worker_jwt_ttl_seconds: int = Field(default=60, ge=30, le=120)
    async_task_lease_seconds: float = Field(default=60, gt=3, le=3600)
    async_task_heartbeat_seconds: float = Field(default=15, gt=0)
    async_task_max_concurrent: int = Field(default=8, ge=1, le=100)
    async_task_max_inflight: int = Field(default=100, ge=1, le=10_000)
    async_task_max_runtime_seconds: float = Field(default=240, gt=0, le=3600)
    async_task_drain_timeout_seconds: float = Field(default=30, gt=0, le=300)
    async_task_token_safety_seconds: float = Field(default=20, gt=0)
    async_task_connect_timeout_seconds: float = Field(default=1, gt=0)
    async_task_request_timeout_seconds: float = Field(default=5, gt=0)
    async_task_stream_idle_timeout_seconds: float = Field(default=30, gt=0, le=300)
    async_task_event_max_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    async_task_progress_enabled: bool = True

    otel_enabled: bool = False
    otel_service_name: str = "agentscope-orchestrator"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    @field_validator("internal_jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"HS256", "RS256"}:
            raise ValueError("INTERNAL_JWT_ALGORITHM must be HS256 or RS256")
        return normalized

    @field_validator(
        "agent_max_tokens",
        "agent_timeout_seconds",
        "agent_model_max_output_tokens",
    )
    @classmethod
    def validate_finite_agent_limit(
        cls,
        value: int | float,
        info: ValidationInfo,
    ) -> int | float:
        if value <= 0:
            env_name = (info.field_name or "agent_limit").upper()
            raise ValueError(f"{env_name} must be greater than zero")
        return value

    @model_validator(mode="after")
    def validate_orchestrator_limits(self) -> "Settings":
        if self.http_max_keepalive_connections > self.http_max_connections:
            raise ValueError("HTTP_MAX_KEEPALIVE_CONNECTIONS must not exceed HTTP_MAX_CONNECTIONS")
        if self.agent_voting_n > self.agent_voting_max_candidates:
            raise ValueError("AGENT_VOTING_N must not exceed AGENT_VOTING_MAX_CANDIDATES")
        if self.async_task_heartbeat_seconds * 3 > self.async_task_lease_seconds:
            raise ValueError(
                "ASYNC_TASK_HEARTBEAT_SECONDS must not exceed one third of ASYNC_TASK_LEASE_SECONDS"
            )
        if self.async_task_max_inflight < self.async_task_max_concurrent:
            raise ValueError(
                "ASYNC_TASK_MAX_INFLIGHT must not be less than ASYNC_TASK_MAX_CONCURRENT"
            )
        if self.async_task_token_safety_seconds <= self.async_task_request_timeout_seconds:
            raise ValueError(
                "ASYNC_TASK_TOKEN_SAFETY_SECONDS must exceed ASYNC_TASK_REQUEST_TIMEOUT_SECONDS"
            )
        if self.agent_session_lease_seconds >= self.agent_session_ttl_seconds:
            raise ValueError(
                "AGENT_SESSION_LEASE_SECONDS must be less than AGENT_SESSION_TTL_SECONDS"
            )
        if (
            self.agent_session_store == "redis"
            and not self.agent_session_redis_url.get_secret_value().startswith(
                ("redis://", "rediss://")
            )
        ):
            raise ValueError(
                "AGENT_SESSION_REDIS_URL must use redis or rediss when session store is redis"
            )
        if self.async_task_enabled:
            worker_id = self.async_task_worker_id.strip()
            if (
                not worker_id
                or len(worker_id) > 128
                or not all(char.isalnum() or char in "._-" for char in worker_id)
            ):
                raise ValueError(
                    "ASYNC_TASK_WORKER_ID must be a stable service identity "
                    "when async tasks are enabled"
                )
            worker_secret = self.async_task_worker_jwt_secret.get_secret_value()
            if len(worker_secret.encode("utf-8")) < 32:
                raise ValueError(
                    "ASYNC_TASK_WORKER_JWT_SECRET must contain at least 32 bytes "
                    "when async tasks are enabled"
                )
            shared_worker_secrets = {
                self.internal_jwt_secret.get_secret_value(),
                self.agent_confirmation_secret.get_secret_value(),
                self.agent_downstream_jwt_secret.get_secret_value(),
            }
            shared_worker_secrets.discard("")
            if worker_secret in shared_worker_secrets:
                raise ValueError(
                    "ASYNC_TASK_WORKER_JWT_SECRET must not reuse internal, confirmation, "
                    "or downstream secrets"
                )
        if self.agent_mcp_enabled:
            if not self.agent_mcp_url.strip():
                raise ValueError("AGENT_MCP_URL is required when AGENT_MCP_ENABLED=true")
            if not self.agent_mcp_url.startswith(("http://", "https://")):
                raise ValueError("AGENT_MCP_URL must use http or https")
            if not self.agent_mcp_tools:
                raise ValueError(
                    "AGENT_MCP_TOOLS_JSON must contain an explicit allowlist when MCP is enabled"
                )
        if self.agent_browser_enabled:
            if not self.agent_browser_sandbox_url.startswith(("http://", "https://")):
                raise ValueError(
                    "AGENT_BROWSER_SANDBOX_URL must use http or https when Browser is enabled"
                )
            if not self.agent_browser_allowed_hosts:
                raise ValueError(
                    "AGENT_BROWSER_ALLOWED_HOSTS_JSON must be non-empty when Browser is enabled"
                )
        if self.agent_code_exec_enabled and not self.agent_code_sandbox_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "AGENT_CODE_SANDBOX_URL must use http or https when code execution is enabled"
            )
        write_tools_enabled = (
            self.agent_refund_start_enabled
            or self.agent_browser_enabled
            or self.agent_code_exec_enabled
            or (
                self.agent_mcp_enabled
                and any(not binding.metadata.read_only for binding in self.agent_mcp_tools)
            )
        )
        external_tools_enabled = (
            self.agent_mcp_enabled or self.agent_browser_enabled or self.agent_code_exec_enabled
        )
        if external_tools_enabled:
            downstream_secret = self.agent_downstream_jwt_secret.get_secret_value()
            if len(downstream_secret.encode("utf-8")) < 32:
                raise ValueError(
                    "AGENT_DOWNSTREAM_JWT_SECRET must contain at least 32 bytes "
                    "when an external tool provider is enabled"
                )
            shared_secrets = {
                self.internal_jwt_secret.get_secret_value(),
                self.agent_confirmation_secret.get_secret_value(),
            }
            shared_secrets.discard("")
            if downstream_secret in shared_secrets:
                raise ValueError(
                    "AGENT_DOWNSTREAM_JWT_SECRET must not reuse internal or confirmation secrets"
                )
            audiences = {
                self.agent_mcp_audience,
                self.agent_browser_audience,
                self.agent_code_audience,
            }
            if len(audiences) != 3:
                raise ValueError("external tool provider audiences must be distinct")
        if write_tools_enabled:
            if len(self.agent_confirmation_secret.get_secret_value().encode("utf-8")) < 32:
                raise ValueError(
                    "AGENT_CONFIRMATION_SECRET must contain at least 32 bytes "
                    "when write tools are enabled"
                )
            if not self.agent_confirmation_issuer.strip():
                raise ValueError("AGENT_CONFIRMATION_ISSUER is required")
            if not self.agent_confirmation_audience.strip():
                raise ValueError("AGENT_CONFIRMATION_AUDIENCE is required")
            if not self.agent_confirmation_key_id.strip():
                raise ValueError("AGENT_CONFIRMATION_KEY_ID is required")
            if (
                self.app_env.strip().casefold() in {"prod", "production"}
                and self.agent_confirmation_replay_store != "redis"
            ):
                raise ValueError(
                    "AGENT_CONFIRMATION_REPLAY_STORE must be redis in production "
                    "when write tools are enabled"
                )
        if (
            self.agent_confirmation_replay_store == "redis"
            and not self.agent_confirmation_redis_url.get_secret_value().startswith(
                ("redis://", "rediss://")
            )
        ):
            raise ValueError(
                "AGENT_CONFIRMATION_REDIS_URL must use redis or rediss when replay store is redis"
            )
        if (
            self.app_env.strip().casefold() in {"prod", "production"}
            and self.agent_session_store != "redis"
        ):
            raise ValueError("AGENT_SESSION_STORE must be redis in production")
        return self

    @property
    def agent_chaining_steps(self) -> tuple[ChainStepDefinition, ...]:
        adapter = TypeAdapter(list[ChainStepDefinition])
        return tuple(adapter.validate_json(self.agent_chaining_steps_json))

    @property
    def agent_write_tools_enabled(self) -> bool:
        return (
            self.agent_refund_start_enabled
            or self.agent_browser_enabled
            or self.agent_code_exec_enabled
            or (
                self.agent_mcp_enabled
                and any(not binding.metadata.read_only for binding in self.agent_mcp_tools)
            )
        )

    @property
    def agent_mcp_tools(self) -> tuple[McpToolBinding, ...]:
        adapter = TypeAdapter(list[McpToolBinding])
        bindings = tuple(adapter.validate_json(self.agent_mcp_tools_json))
        if len(bindings) > 16:
            raise ValueError("AGENT_MCP_TOOLS_JSON supports at most 16 tools")
        local_names = [binding.metadata.name for binding in bindings]
        if len(local_names) != len(set(local_names)):
            raise ValueError("AGENT_MCP_TOOLS_JSON contains duplicate local tool names")
        remote_names = [binding.remote_name for binding in bindings]
        if len(remote_names) != len(set(remote_names)):
            raise ValueError("AGENT_MCP_TOOLS_JSON contains duplicate remote tool names")
        return bindings

    @property
    def agent_browser_allowed_hosts(self) -> tuple[str, ...]:
        adapter = TypeAdapter(list[str])
        values = tuple(
            item.strip().casefold()
            for item in adapter.validate_json(self.agent_browser_allowed_hosts_json)
        )
        if len(values) > 64:
            raise ValueError("AGENT_BROWSER_ALLOWED_HOSTS_JSON supports at most 64 hosts")
        if any(
            not value
            or "/" in value
            or ":" in value
            or value.startswith(".")
            or value.endswith(".")
            for value in values
        ):
            raise ValueError("AGENT_BROWSER_ALLOWED_HOSTS_JSON contains an invalid hostname")
        if len(values) != len(set(values)):
            raise ValueError("AGENT_BROWSER_ALLOWED_HOSTS_JSON contains duplicate hosts")
        return values

    @property
    def agent_enabled(self) -> bool:
        return bool(self.gateway_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
