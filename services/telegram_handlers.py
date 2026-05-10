from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from core.config import Settings
from db.postgres import ConversationRepository
from services.claude_service import ClaudeService
from services.faq import try_faq_response
from services.sentiment import is_aggressive_tone
from services.telegram_service import (
    build_operator_keyboard,
    format_operator_ticket,
    purge_draft_anchors,
)

log = logging.getLogger(__name__)

_CB_PATTERN = re.compile(r"^(send|edit|escalate):(-?\d+)$")


async def _try_clear_inline_keyboard(update: Update) -> None:
    q = update.callback_query
    if not q or not q.message:
        return
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        log.warning("Could not remove inline keyboard (stale message?)", exc_info=True)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            (
                "Вітаємо! Це logistics-copilot.\n\n"
                "Опишіть питання: статус відправлення, строки, умови, адреси — ми підключимо оператора або "
                "відповімо автоматично, коли це безпечно."
            ),
        )
        return

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        me = await context.bot.get_me()
        un = me.username or ""
        link = f"https://t.me/{un}" if un else ""
        await update.message.reply_text(
            (
                "Клієнтські звернення — лише в особистому чаті з ботом.\n\n"
                f"Відкрий: {link} → Start → напиши питання туди."
            ),
        )


async def on_text_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    settings: Settings = context.application.bot_data["settings"]
    conv_repo: ConversationRepository = context.application.bot_data["conversation_repo"]

    chat = update.effective_chat
    chat_id = chat.id

    # Якщо OPERATOR_CHAT_ID = ваш user id, у приваті з того ж акаунту без reply раніше
    # все йшло в handle_operator_chat_text і не потрапляло в БД/клієнтський пайплайн.
    operator_inbox = chat_id == settings.operator_chat_id
    if operator_inbox and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await handle_operator_chat_text(update, context)
        return
    if (
        operator_inbox
        and chat.type == ChatType.PRIVATE
        and update.message.reply_to_message is not None
    ):
        await handle_operator_chat_text(update, context)
        return

    if chat.type != ChatType.PRIVATE:
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            me = await context.bot.get_me()
            un = me.username or ""
            if un:
                await update.message.reply_text(
                    "Тут відповіді не формую: це група. Напишіть мені в особисті → "
                    f"https://t.me/{un}",
                )
            else:
                await update.message.reply_text(
                    "Напишіть у приватний чат із ботом (іконка бота → особисті повідомлення).",
                )
        return

    await handle_customer_private_text(update, context, settings=settings, conversation_repo=conv_repo)


async def handle_customer_private_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    settings: Settings,
    conversation_repo: ConversationRepository,
) -> None:
    claude: ClaudeService = context.application.bot_data["claude_service"]
    anchors: dict[int, dict] = context.application.bot_data["draft_anchor"]

    msg = update.message
    customer_id = update.effective_chat.id
    username = update.effective_user.username if update.effective_user else None
    text = msg.text.strip()

    try:
        history = await conversation_repo.append_user_message_and_clear_pending(customer_id, text)
    except Exception:
        log.exception("Postgres conversation append failed (telegram_id=%s)", customer_id)
        await msg.reply_text("Сервіс тимчасово недоступний. Спробуйте пізніше.")
        return

    if is_aggressive_tone(text):
        manager_id = settings.effective_manager_chat_id
        handle = f"@{username}" if username else "без username"
        await context.bot.send_message(
            chat_id=manager_id,
            text=(
                "🚨 Aggressive sentiment / високий ризик конфлікту.\n\n"
                f"Клієнт: `{customer_id}` ({handle}).\n"
                f"\n—— Текст ——\n{text}"
            ),
        )
        ack = (
            "Ми отримали ваше повідомлення й передали його керівнику операторської зміни. "
            "Просимо зачекати на відповідь."
        )
        await msg.reply_text(ack)
        try:
            await conversation_repo.append_delivered_assistant_message(customer_id, ack)
        except Exception:
            log.exception("Failed persisting escalation ack transcript")
        return

    faq = try_faq_response(text)
    if faq:
        await msg.reply_text(faq)
        try:
            await conversation_repo.append_delivered_assistant_message(customer_id, faq)
        except Exception:
            log.exception("Failed persisting FAQ transcript")
        return

    transcript_for_models = history[:-1]
    latest_user_message = history[-1]["content"]
    transcript_payload = [{"role": m["role"], "content": str(m["content"])} for m in transcript_for_models]

    try:
        draft = await claude.draft_operator_reply(
            history_messages=transcript_payload,
            latest_user_message=latest_user_message,
            user_telegram_id=customer_id,
        )
    except Exception:
        log.exception("Claude drafting failed")
        fallback = (
            "Ми передали ваше повідомлення оператору. Дайте нам трохи часу та надішліть ТТН, якщо питання "
            "стосується конкретного відправлення."
        )
        await msg.reply_text(fallback)
        try:
            await conversation_repo.append_delivered_assistant_message(customer_id, fallback)
        except Exception:
            log.exception("Failed persisting fallback transcript")
        return

    try:
        await conversation_repo.set_history_and_pending_draft(customer_id, history, draft)
    except Exception:
        log.exception("Failed saving pending AI draft")

    purge_draft_anchors(anchors, customer_id)

    operator_text = format_operator_ticket(
        customer_chat_id=customer_id,
        username=username,
        customer_text=text,
        ai_draft=draft,
    )
    keyboard = build_operator_keyboard(customer_id)

    try:
        sent = await context.bot.send_message(
            chat_id=settings.operator_chat_id,
            text=operator_text,
            reply_markup=keyboard,
        )
        anchors[int(sent.message_id)] = {"customer_chat_id": customer_id}
    except Exception:
        log.exception("Failed notifying operator")


async def handle_operator_chat_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conv_repo: ConversationRepository = context.application.bot_data["conversation_repo"]
    anchors: dict[int, dict] = context.application.bot_data["draft_anchor"]

    msg = update.message
    if not msg.text or msg.text.startswith("/"):
        return
    reply_mid = msg.reply_to_message.message_id if msg.reply_to_message else None
    if reply_mid is None:
        await msg.reply_text("Щоб надіслати EDIT, зробіть reply на картку клієнта з чорнеткою.")
        return

    meta = anchors.get(int(reply_mid))
    if meta is None:
        await msg.reply_text("Не знайшов привʼязку reply → клієнт. Оберіть reply саме до картки з кнопками.")
        return

    customer_id = int(meta["customer_chat_id"])
    outbound = msg.text.strip()
    await context.bot.send_message(chat_id=customer_id, text=outbound)
    try:
        await conv_repo.append_delivered_assistant_message(customer_id, outbound)
        await conv_repo.clear_pending_draft(customer_id)
    except Exception:
        log.exception("Failed persisting EDIT reply transcript")
        return
    purge_draft_anchors(anchors, customer_id)


async def on_operator_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    settings: Settings = context.application.bot_data["settings"]
    conv_repo: ConversationRepository = context.application.bot_data["conversation_repo"]
    anchors: dict[int, dict] = context.application.bot_data["draft_anchor"]

    data = q.data or ""
    m = _CB_PATTERN.match(data)
    if not m:
        await _try_clear_inline_keyboard(update)
        return

    intent, sid = m.group(1), m.group(2)
    customer_id = int(sid)

    if intent == "escalate":
        await context.bot.send_message(
            chat_id=settings.effective_manager_chat_id,
            text=(
                "🚨 ESCALATE від оператора.\n\n"
                f"Клієнт: `{customer_id}`.\n\n"
                "Подальші дії виконуєте вручну (дзвінок / SLA / ERP)."
            ),
        )
        purge_draft_anchors(anchors, customer_id)
        await _try_clear_inline_keyboard(update)
        return

    snapshot = await conv_repo.snapshot(customer_id)
    pending = snapshot.get("pending_draft") if snapshot else None
    draft_text = pending if isinstance(pending, str) else None

    if intent == "send":
        if not draft_text:
            await context.bot.send_message(
                chat_id=settings.operator_chat_id,
                text=f"⚠️ Немає збереженої чернетки для `{customer_id}`. EDIT або повтор запит у клієнта.",
            )
            purge_draft_anchors(anchors, customer_id)
            await _try_clear_inline_keyboard(update)
            return
        await context.bot.send_message(chat_id=customer_id, text=draft_text)
        try:
            await conv_repo.append_delivered_assistant_message(customer_id, draft_text)
            await conv_repo.clear_pending_draft(customer_id)
        except Exception:
            log.exception("Failed persist after SEND")
        purge_draft_anchors(anchors, customer_id)
        await _try_clear_inline_keyboard(update)
        return

    # intent == "edit"
    await context.bot.send_message(
        chat_id=settings.operator_chat_id,
        text=(
            "✏️ EDIT: надішліть фінальний текст reply саме як відповідь (reply) "
            "на картку клієнта з чорнеткою (повідомлення з кнопками)."
        ),
    )


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(on_operator_inline, pattern=_CB_PATTERN))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_dispatch))
