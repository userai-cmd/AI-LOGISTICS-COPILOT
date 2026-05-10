from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from core.config import Settings

log = logging.getLogger(__name__)


def _normalize_dsn(url: str) -> str:
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql://" + u[len("postgres://") :]
    return u


async def create_pool(settings: Settings) -> asyncpg.Pool:
    kwargs: dict[str, Any] = {"min_size": 1, "max_size": 10}
    use_ssl = settings.postgres_should_use_ssl()
    cfg = settings.database_ssl
    log.info(
        "Postgres connect ssl=%s (DATABASE_SSL env=%s)",
        use_ssl,
        "unset→auto" if cfg is None else cfg,
    )
    if use_ssl:
        kwargs["ssl"] = True

    return await asyncpg.create_pool(
        _normalize_dsn(settings.database_url),
        **kwargs,
    )


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
