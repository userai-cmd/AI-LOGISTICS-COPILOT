from __future__ import annotations

import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from telegram.ext import Application

from core.config import Settings
from db.postgres import ConversationRepository
from models.schemas import (
    OperatorConversationDetail,
    OperatorConversationSummary,
    OperatorReplyBody,
)

router = APIRouter(prefix="/operator", tags=["operator"])
_bearer = HTTPBearer(auto_error=False)


def _expected_workspace_token(settings: Settings) -> str | None:
    t = (settings.operator_workspace_token or "").strip()
    return t or None


async def require_operator(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    settings: Settings = request.app.state.settings
    expected = _expected_workspace_token(settings)
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Operator workspace is disabled. Set OPERATOR_WORKSPACE_TOKEN.",
        )
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required")
    if not secrets.compare_digest(
        creds.credentials.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Invalid token")


def _repo(request: Request) -> ConversationRepository:
    return request.app.state.conversation_repo


def _ptb(request: Request) -> Application:
    return request.app.state.ptb


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/status")
async def workspace_status(request: Request) -> dict[str, bool]:
    settings: Settings = request.app.state.settings
    return {"workspace_enabled": _expected_workspace_token(settings) is not None}


@router.get(
    "/conversations",
    response_model=list[OperatorConversationSummary],
    dependencies=[Depends(require_operator)],
)
async def list_conversations(
    request: Request,
    limit: int = 80,
) -> list[OperatorConversationSummary]:
    repo = _repo(request)
    rows = await repo.list_recent(limit=limit)
    return [
        OperatorConversationSummary(
            telegram_id=r["telegram_id"],
            last_updated=r["last_updated"].isoformat() if r.get("last_updated") else None,
            has_pending_draft=bool(r.get("pending_draft")),
            last_message_preview=(r.get("last_message_preview") or "")[:280],
        )
        for r in rows
    ]


@router.get(
    "/conversations/{telegram_id}",
    response_model=OperatorConversationDetail,
    dependencies=[Depends(require_operator)],
)
async def get_conversation(
    request: Request,
    telegram_id: int,
) -> OperatorConversationDetail:
    repo = _repo(request)
    snap = await repo.snapshot(telegram_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Conversation not found")
    lu = snap.get("last_updated")
    return OperatorConversationDetail(
        telegram_id=int(snap["telegram_id"]),
        last_updated=lu.isoformat() if lu is not None else None,
        pending_draft=snap.get("pending_draft"),
        history=list(snap.get("history") or []),
    )


@router.post(
    "/conversations/{telegram_id}/send-draft",
    dependencies=[Depends(require_operator)],
)
async def send_pending_draft(
    request: Request,
    telegram_id: int,
) -> dict[str, str]:
    repo = _repo(request)
    ptb = _ptb(request)
    snap = await repo.snapshot(telegram_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Conversation not found")
    draft = snap.get("pending_draft")
    if not isinstance(draft, str) or not draft.strip():
        raise HTTPException(status_code=400, detail="No pending draft for this client")
    await ptb.bot.send_message(chat_id=telegram_id, text=draft.strip())
    await repo.append_delivered_assistant_message(telegram_id, draft.strip())
    return {"status": "sent"}


@router.post(
    "/conversations/{telegram_id}/reply",
    dependencies=[Depends(require_operator)],
)
async def send_custom_reply(
    request: Request,
    telegram_id: int,
    body: OperatorReplyBody,
) -> dict[str, str]:
    repo = _repo(request)
    ptb = _ptb(request)
    snap = await repo.snapshot(telegram_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Conversation not found")
    text = body.text.strip()
    await ptb.bot.send_message(chat_id=telegram_id, text=text)
    await repo.append_delivered_assistant_message(telegram_id, text)
    return {"status": "sent"}


@router.post(
    "/conversations/{telegram_id}/escalate",
    dependencies=[Depends(require_operator)],
)
async def escalate(
    request: Request,
    telegram_id: int,
) -> dict[str, str]:
    settings = _settings(request)
    ptb = _ptb(request)
    repo = _repo(request)
    if not await repo.snapshot(telegram_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    await ptb.bot.send_message(
        chat_id=settings.effective_manager_chat_id,
        text=(
            "🚨 ESCALATE (операторська панель).\n\n"
            f"Клієнт: `{telegram_id}`.\n\n"
            "Подальші дії — вручну (дзвінок / SLA / ERP)."
        ),
    )
    return {"status": "escalated"}
