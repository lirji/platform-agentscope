"""只读退款回执沿用原调用参数, 绝不在body选择可信租户/用户."""

from pydantic import BaseModel, ConfigDict, Field


class RefundReceiptRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    chat_id: str | None = Field(default=None, alias="chatId")
    message: str
    dedupe_id: str | None = Field(default=None, alias="dedupeId")
    webhook_url: str | None = Field(default=None, alias="webhookUrl")
