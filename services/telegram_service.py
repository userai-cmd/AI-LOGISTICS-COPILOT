from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def format_operator_ticket(
    *,
    customer_chat_id: int,
    username: str | None,
    customer_text: str,
    ai_draft: str,
) -> str:
    handle = f"@{username}" if username else "—"
    return (
        f"Клієнт chat_id=`{customer_chat_id}` ({handle})\n"
        f"\n—— Повідомлення клієнта ——\n{customer_text.strip()}\n\n"
        f"—— Чернетка AI ——\n{ai_draft.strip()}"
    )


def build_operator_keyboard(customer_chat_id: int) -> InlineKeyboardMarkup:
    sid = str(customer_chat_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ SEND", callback_data=f"send:{sid}"),
                InlineKeyboardButton("✏️ EDIT", callback_data=f"edit:{sid}"),
                InlineKeyboardButton("🚨 ESCALATE", callback_data=f"escalate:{sid}"),
            ]
        ],
    )


def purge_draft_anchors(anchors: dict[int, dict], customer_chat_id: int) -> None:
    remove_ids = [mid for mid, meta in anchors.items() if meta.get("customer_chat_id") == customer_chat_id]
    for mid in remove_ids:
        anchors.pop(mid, None)
