from functools import lru_cache
from pathlib import Path

from pydantic import (
    Field,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    agent_max_tokens: int = Field(default=0, ge=0)
    agent_timeout_seconds: float = Field(default=0, ge=0)
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

    internal_auth_required: bool = True
    internal_jwt_header: str = "X-Internal-Token"
    internal_jwt_algorithm: str = "HS256"
    internal_jwt_secret: SecretStr = SecretStr("")
    internal_jwt_public_key: SecretStr = SecretStr("")
    internal_jwt_public_key_file: Path | None = None

    knowledge_base_url: str = "http://localhost:8084"
    analytics_base_url: str = "http://localhost:8083"
    analytics_external_planner_shadow_enabled: bool = False
    analytics_external_planner_max_tables: int = Field(default=20, ge=1, le=100)
    workflow_base_url: str = "http://localhost:8082"
    order_base_url: str = "http://localhost:8093"
    http_connect_timeout_seconds: float = Field(default=1, gt=0)
    http_read_timeout_seconds: float = Field(default=10, gt=0)

    async_task_enabled: bool = False
    async_task_base_url: str = "http://localhost:8086"
    async_task_worker_id: str = ""
    async_task_lease_seconds: float = Field(default=60, gt=3, le=3600)
    async_task_heartbeat_seconds: float = Field(default=15, gt=0)
    async_task_max_concurrent: int = Field(default=8, ge=1, le=100)
    async_task_max_inflight: int = Field(default=100, ge=1, le=10_000)
    async_task_max_runtime_seconds: float = Field(default=240, gt=0, le=3600)
    async_task_token_safety_seconds: float = Field(default=20, gt=0)
    async_task_connect_timeout_seconds: float = Field(default=1, gt=0)
    async_task_request_timeout_seconds: float = Field(default=5, gt=0)
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

    @model_validator(mode="after")
    def validate_orchestrator_limits(self) -> "Settings":
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
        return self

    @property
    def agent_chaining_steps(self) -> tuple[ChainStepDefinition, ...]:
        adapter = TypeAdapter(list[ChainStepDefinition])
        return tuple(adapter.validate_json(self.agent_chaining_steps_json))

    @property
    def agent_enabled(self) -> bool:
        return bool(self.gateway_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
