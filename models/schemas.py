from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TelegramWebhookAck(BaseModel):
    ok: Literal[True] = True


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = Field(default="ai-logistics-copilot")


class ClaudeToolCallPayload(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ConversationState(BaseModel):
    telegram_id: int
    history: list[dict[str, Any]] = Field(default_factory=list)
    pending_draft: str | None = None


class OperatorConversationSummary(BaseModel):
    telegram_id: int
    last_updated: str | None = None
    has_pending_draft: bool = False
    last_message_preview: str = ""


class OperatorConversationDetail(BaseModel):
    telegram_id: int
    last_updated: str | None = None
    pending_draft: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class OperatorReplyBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
