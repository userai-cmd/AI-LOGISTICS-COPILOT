from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from telegram import Update

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


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
    update = Update.de_json(payload, ptb.bot)

    try:
        await ptb.process_update(update)
    except Exception:
        # Telegram aggressively retries non-2xx; we log and ACK to avoid retry storms while debugging prod.
        log.exception("Failed processing Telegram update")
    return {"ok": True}
