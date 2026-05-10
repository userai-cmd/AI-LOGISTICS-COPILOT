from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from telegram import Update

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


async def _process_update_background(ptb, payload: dict) -> None:
    """Run PTB pipeline off the webhook HTTP response path (Claude/DB can take tens of seconds)."""
    try:
        update = Update.de_json(payload, ptb.bot)
        await ptb.process_update(update)
    except Exception:
        log.exception("Failed processing Telegram update")


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Annotated[
        str | None,
        Header(alias="X-Telegram-Bot-Api-Secret-Token"),
    ] = None,
) -> dict:
    settings = request.app.state.settings
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload = await request.json()

    ptb = request.app.state.ptb
    background_tasks.add_task(_process_update_background, ptb, payload)

    # Telegram expects a fast 200; long-running Claude/tool work runs in the background task.
    return {"ok": True}
