from pydantic import BaseModel, ConfigDict, Field


class AnalyticsSqlPlan(BaseModel):
    """Language-neutral, read-only SQL plan produced by the AI runtime."""

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=20_000)
