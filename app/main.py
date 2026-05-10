from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application

from api.webhooks import router as telegram_router
from core.config import Settings, get_settings
from core.logging_config import configure_logging
from db.postgres import ClaimsRepository, ConversationRepository, create_pool
from models.schemas import HealthResponse
from services.claude_service import ClaudeService
from services.erp_service import ErpService
from services.telegram_handlers import register_handlers

log = logging.getLogger(__name__)


def _configure_ptb_logging() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def build_settings() -> Settings:
    return get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = build_settings()
    configure_logging(settings.log_level)
    _configure_ptb_logging()
    app.state.settings = settings

    pool = await create_pool(settings)
    application: Application | None = None
    try:
        claims_repo = ClaimsRepository(pool)
        conversation_repo = ConversationRepository(pool)
        erp = ErpService(claims_repo)
        claude = ClaudeService(settings, erp)

        application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        application.bot_data.update(
            {
                "settings": settings,
                "conversation_repo": conversation_repo,
                "claude_service": claude,
                "draft_anchor": {},
            },
        )

        register_handlers(application)

        await application.initialize()
        if settings.set_webhook_on_start:
            kwargs: dict[str, object] = {"allowed_updates": Update.ALL_TYPES}
            if settings.telegram_webhook_secret:
                kwargs["secret_token"] = settings.telegram_webhook_secret
            log.info("Registering Telegram webhook: %s", settings.telegram_webhook_url)
            await application.bot.set_webhook(url=settings.telegram_webhook_url, **kwargs)

        app.state.ptb = application

        yield
    finally:
        if application is not None:
            if settings.set_webhook_on_start:
                try:
                    await application.bot.delete_webhook(drop_pending_updates=False)
                except Exception:
                    log.exception("Failed deleting Telegram webhook on shutdown")

            try:
                await application.shutdown()
            except Exception:
                log.exception("Telegram Application shutdown failed")
        await pool.close()


app = FastAPI(title="AI-LOGISTICS COPILOT", lifespan=lifespan)
app.include_router(telegram_router, prefix="/api/webhooks")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "AI-LOGISTICS COPILOT",
        "status": "ok",
        "health": "/health",
        "telegram_webhook": "/api/webhooks/telegram",
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()
