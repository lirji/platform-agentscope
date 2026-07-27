from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    internal_auth_required: bool = True
    internal_jwt_header: str = "X-Internal-Token"
    internal_jwt_algorithm: str = "HS256"
    internal_jwt_secret: SecretStr = SecretStr("")
    internal_jwt_public_key: SecretStr = SecretStr("")
    internal_jwt_public_key_file: Path | None = None

    knowledge_base_url: str = "http://localhost:8084"
    analytics_base_url: str = "http://localhost:8083"
    workflow_base_url: str = "http://localhost:8082"
    order_base_url: str = "http://localhost:8093"
    http_connect_timeout_seconds: float = Field(default=1, gt=0)
    http_read_timeout_seconds: float = Field(default=10, gt=0)

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

    @property
    def agent_enabled(self) -> bool:
        return bool(self.gateway_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
