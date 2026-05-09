from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from core.config import Settings
from services.erp_service import ErpService

log = logging.getLogger(__name__)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_ttn_status",
        "description": (
            "Mock request to ERP/1C: returns deterministic TTN shipment status snapshot for demos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"number": {"type": "string", "description": "TTN / tracking number"}},
            "required": ["number"],
        },
    },
    {
        "name": "calculate_delivery_cost",
        "description": "Rough mock delivery tariff estimate by weight (kg) and destination city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "weight": {"type": "number", "description": "Weight in kilograms"},
                "city": {"type": "string", "description": "Recipient city"},
            },
            "required": ["weight", "city"],
        },
    },
    {
        "name": "register_damage",
        "description": "Register a shipment damage / claim ticket in PostgreSQL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ttn": {"type": "string"},
                "details": {"type": "string"},
            },
            "required": ["ttn", "details"],
        },
    },
]


class ClaudeService:
    def __init__(self, settings: Settings, erp: ErpService) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model_name
        self._erp = erp

    async def draft_operator_reply(
        self,
        *,
        history_messages: list[dict[str, str]],
        latest_user_message: str,
        user_telegram_id: int,
    ) -> str:
        system = (
            "Ти — AI-копілот логістичного контакт-центру. "
            "Пиши українською коротко, ввічливо й по факту даних із інструментів. "
            "Якщо даних бракує — запитай лише необхідні уточнення. "
            "Не видавай вигадані статуси без виклику get_ttn_status."
        )

        messages: list[dict[str, Any]] = [
            *[{"role": m["role"], "content": m["content"]} for m in history_messages[-20:]],
            {"role": "user", "content": latest_user_message},
        ]

        for _step in range(10):
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=1200,
                temperature=0.2,
                system=system,
                tools=TOOLS,
                messages=messages,
            )

            blocks = getattr(message, "content", []) or []
            texts = [
                str(getattr(b, "text", "")).strip()
                for b in blocks
                if getattr(b, "type", None) == "text"
            ]

            tool_blocks = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
            if not tool_blocks:
                joined = "\n".join(part for part in texts if part).strip()
                if joined:
                    return joined
                return (
                    "Не вдалося сформулювати чернетку: немає тексту у відповіді моделі "
                    f"(stop_reason={getattr(message,'stop_reason',None)})."
                )

            messages.append({"role": "assistant", "content": message.content})

            tool_payload: list[dict[str, Any]] = []
            for block in tool_blocks:
                name = getattr(block, "name", "")
                tb_id = getattr(block, "id", "")
                raw_input = getattr(block, "input", {}) or {}
                try:
                    result = await self._execute_tool(name, raw_input, user_telegram_id=user_telegram_id)
                    tool_payload.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tb_id,
                            "content": json.dumps(result, ensure_ascii=False),
                        },
                    )
                except Exception as exc:  # noqa: BLE001 — surface as tool outcome
                    log.exception("Tool execution failed (%s)", name)
                    tool_payload.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tb_id,
                            "content": json.dumps({"error": repr(exc)}, ensure_ascii=False),
                        },
                    )

            messages.append({"role": "user", "content": tool_payload})

        return "Перервав генерацію: занадто довга послідовність викликів інструментів."

    async def _execute_tool(
        self,
        name: str,
        inp: dict[str, Any],
        *,
        user_telegram_id: int,
    ) -> dict[str, Any]:
        if name == "get_ttn_status":
            number = str(inp.get("number", "")).strip()
            snap = await self._erp.get_ttn_status(number)
            return {"ttn": snap.ttn, "status": snap.status, "location": snap.location, "eta": snap.eta}
        if name == "calculate_delivery_cost":
            weight = float(inp.get("weight", 0))
            city = str(inp.get("city", "")).strip()
            total, note = await self._erp.calculate_delivery_cost(weight, city)
            return {"total": total, "note": note}
        if name == "register_damage":
            ttn = str(inp.get("ttn", "")).strip()
            details = str(inp.get("details", "")).strip()
            cid = await self._erp.register_damage(ttn=ttn, details=details, user_id=user_telegram_id)
            return {"claim_id": cid, "status": "open"}
        return {"error": f"unknown_tool:{name}"}
