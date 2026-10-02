"""跨运行时计量DTO; 租户和用户只来自专用RPC签名."""

from pydantic import BaseModel, ConfigDict, Field


class BudgetReservationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation_id: str = Field(alias="operationId", min_length=1, max_length=128)
    tokens: int = Field(ge=1)


class BudgetReservationReply(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation_id: str = Field(alias="operationId", min_length=1, max_length=128)
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reserved_tokens: int = Field(alias="reservedTokens", ge=1)


class BudgetSettlementRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    operation_id: str = Field(alias="operationId", min_length=1, max_length=128)
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reserved_tokens: int = Field(alias="reservedTokens", ge=1)
    actual_tokens: int = Field(alias="actualTokens", ge=0)
