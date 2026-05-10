from __future__ import annotations

import json
import logging
import ssl
from typing import Any
from urllib.parse import urlparse

import asyncpg

from core.config import Settings

log = logging.getLogger(__name__)


def _normalize_dsn(url: str) -> str:
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql://" + u[len("postgres://") :]
    return u


def _dsn_host_port(dsn_normalized: str) -> tuple[str | None, int]:
    parsed = urlparse(dsn_normalized)
    return parsed.hostname, int(parsed.port or 5432)


def _ssl_for_asyncpg(use_ssl: bool, host: str | None) -> bool | ssl.SSLContext:
    """Railway *.proxy.rlwy.net часто термінує TLS інакше; ssl=True інколи дає збій атрибута handshake."""
    if not use_ssl:
        return False
    h = (host or "").lower()
    if "proxy.rlwy.net" in h:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return True


async def create_pool(settings: Settings) -> asyncpg.Pool:
    kwargs: dict[str, Any] = {"min_size": 1, "max_size": 10}
    use_ssl = settings.postgres_should_use_ssl()
    cfg = settings.database_ssl
    dsn = _normalize_dsn(settings.database_url)
    host, port = _dsn_host_port(dsn)
    log.info(
        "Postgres connect target host=%s port=%s ssl=%s (DATABASE_SSL env=%s)",
        host,
        port,
        use_ssl,
        "unset→auto" if cfg is None else cfg,
    )
    ssl_opt = _ssl_for_asyncpg(use_ssl, host)
    if ssl_opt is not False:
        kwargs["ssl"] = ssl_opt

    try:
        return await asyncpg.create_pool(dsn, **kwargs)
    except ConnectionRefusedError:
        hint = (
            "Немає процесу Postgres на цьому host:port або змінна вказує не ту мережу. "
            "Railway: у сервісі додатка Database URL → Variable Reference на Postgres → DATABASE_URL; "
            "або використайте Postgres DATABASE_PUBLIC_URL (хост *.proxy.rlwy.net + зовнішній порт з UI, не 5432). "
            "Спробуйте прибрати DATABASE_SSL із Variables (увімкнеться авто по хосту)."
        )
        log.error(
            "Postgres connection refused (host=%s port=%s, ssl=%s). %s",
            host,
            port,
            use_ssl,
            hint,
        )
        raise


def _history_from_db(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        return list(parsed) if isinstance(parsed, list) else []
    return []


class ConversationRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def snapshot(self, telegram_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, telegram_id, history, pending_draft, last_updated
                FROM conversations
                WHERE telegram_id = $1
                """,
                telegram_id,
            )
        if not row:
            return None
        h = row["history"]
        return {
            "id": str(row["id"]) if row["id"] is not None else None,
            "telegram_id": row["telegram_id"],
            "history": _history_from_db(h),
            "pending_draft": row["pending_draft"],
            "last_updated": row["last_updated"],
        }

    async def append_user_message_and_clear_pending(self, telegram_id: int, text: str) -> list[dict[str, Any]]:
        existing = await self.snapshot(telegram_id)
        history = _history_from_db(existing.get("history") if existing else None)
        history.append({"role": "user", "content": text})
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (telegram_id, history, pending_draft, last_updated)
                VALUES ($1, $2::jsonb, NULL, now())
                ON CONFLICT (telegram_id) DO UPDATE SET
                    history = EXCLUDED.history,
                    pending_draft = NULL,
                    last_updated = now()
                """,
                telegram_id,
                json.dumps(history, ensure_ascii=False),
            )
        return history

    async def set_history_and_pending_draft(
        self,
        telegram_id: int,
        history: list[dict[str, Any]],
        draft: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (telegram_id, history, pending_draft, last_updated)
                VALUES ($1, $2::jsonb, $3, now())
                ON CONFLICT (telegram_id) DO UPDATE SET
                    history = EXCLUDED.history,
                    pending_draft = EXCLUDED.pending_draft,
                    last_updated = now()
                """,
                telegram_id,
                json.dumps(history, ensure_ascii=False),
                draft,
            )

    async def append_delivered_assistant_message(
        self,
        telegram_id: int,
        text: str,
    ) -> list[dict[str, Any]]:
        existing = await self.snapshot(telegram_id)
        history = _history_from_db(existing.get("history") if existing else None)
        history.append({"role": "assistant", "content": text})
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (telegram_id, history, pending_draft, last_updated)
                VALUES ($1, $2::jsonb, NULL, now())
                ON CONFLICT (telegram_id) DO UPDATE SET
                    history = EXCLUDED.history,
                    pending_draft = NULL,
                    last_updated = now()
                """,
                telegram_id,
                json.dumps(history, ensure_ascii=False),
            )
        return history

    async def clear_pending_draft(self, telegram_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE conversations
                SET pending_draft = NULL, last_updated = now()
                WHERE telegram_id = $1
                """,
                telegram_id,
            )

    async def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 500))
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT telegram_id, history, pending_draft, last_updated
                FROM conversations
                ORDER BY last_updated DESC
                LIMIT $1
                """,
                lim,
            )
        out: list[dict[str, Any]] = []
        for row in rows:
            hist = _history_from_db(row["history"])
            preview = ""
            if hist:
                last = hist[-1]
                c = last.get("content") if isinstance(last, dict) else None
                preview = (str(c) if c is not None else "")[:280]
            out.append(
                {
                    "telegram_id": row["telegram_id"],
                    "pending_draft": row["pending_draft"],
                    "last_updated": row["last_updated"],
                    "history": hist,
                    "last_message_preview": preview,
                },
            )
        return out


class ClaimsRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def register_damage(
        self,
        *,
        ttn: str,
        user_id: int | None,
        details: str,
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO claims (ttn, user_id, description, status)
                VALUES ($1, $2, $3, 'open')
                RETURNING id, ttn, user_id, status, description, created_at, updated_at
                """,
                ttn,
                user_id,
                details,
            )
        if not row:
            return {}
        return {
            "id": str(row["id"]),
            "ttn": row["ttn"],
            "user_id": row["user_id"],
            "status": row["status"],
            "description": row["description"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
