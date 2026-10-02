from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    tone: str
    citation_policy: str
    extra: str


class ConversationHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=4000)


class ConversationGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"]
    message: str
    context: str
    style: ConversationStyle
    history: list[ConversationHistoryMessage] = Field(max_length=32)


class ConversationGenerationReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str = Field(min_length=1)
