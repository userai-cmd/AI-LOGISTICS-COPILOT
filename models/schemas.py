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
