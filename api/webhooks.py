from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from telegram import Update

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


async def _process_update_background(ptb, payload: dict) -> None:
    """Run PTB pipeline off the webhook HTTP response path (Claude/DB can take tens of seconds)."""
    uid = payload.get("update_id")
    try:
        update = Update.de_json(payload, ptb.bot)
        log.info("Processing Telegram update_id=%s", uid)
        await ptb.process_update(update)
    except Exception:
        log.exception("Failed processing Telegram update (update_id=%s)", uid)


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
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
    asyncio.create_task(_process_update_background(ptb, payload))

    # Telegram expects a fast 200; Claude/DB runs in a separate asyncio task.
    return {"ok": True}
