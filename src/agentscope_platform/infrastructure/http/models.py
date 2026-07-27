from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    score: float | None = None
    doc_id: str | None = Field(default=None, alias="docId")
    display_name: str | None = Field(default=None, alias="displayName")
    category: str | None = None
    index: str | None = None
    text: str | None = None
    source: str | None = None
    visibility: str | None = None


class KnowledgeQueryReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str | None = None
    tenant_id: str | None = Field(default=None, alias="tenantId")
    hits: list[KnowledgeHit] = Field(default_factory=list)


class OrderView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    order_no: str = Field(alias="orderNo")
    customer: str | None = None
    amount: str | None = None
    status: str
    created_at: str | None = Field(default=None, alias="createdAt")


class AnalyticsSqlReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str | None = None
    sql: str | None = None
    row_count: int = Field(default=0, alias="rowCount")
    rows: list[dict[str, Any]] = Field(default_factory=list)
    answer: str | None = None
    guard_blocked: bool = Field(default=False, alias="guardBlocked")


class AnalyticsTablesReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tables: list[str] = Field(default_factory=list)


class AnalyticsTableSchemaReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    table: str
    schema_text: str | None = Field(default=None, alias="schema")
