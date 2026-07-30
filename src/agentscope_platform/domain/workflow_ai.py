from pydantic import BaseModel, ConfigDict, Field


class WorkflowTicketDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)


class WorkflowTicketDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    priority: str = Field(pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    category: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2_000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class WorkflowReplyDraftRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    chat_id: str = Field(alias="chatId", min_length=1, max_length=500)
    message: str = Field(min_length=1, max_length=20_000)


class WorkflowReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str = Field(min_length=1, max_length=20_000)
