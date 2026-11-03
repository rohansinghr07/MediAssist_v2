"""Telegram layer - turns Telegram updates into engine calls, and engine replies into Telegram messages."""
import html
import logging

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
                      ReplyKeyboardRemove, Update)
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from config import settings
from engine import Engine

log = logging.getLogger("telegram")


def pressed_label(reply_markup, data):
    """Find the text of the button the user pressed."""
    if not reply_markup:
        return None
    for row in reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data == data:
                return button.text
    return None


def with_choice(message_html, label):
    """Original message + the user's choice, so the chat keeps a record of what was tapped."""
    return f"{message_html}\n\n👉 <b>{html.escape(label)}</b>"


def build(engine_holder: dict) -> Application:
    """engine_holder["engine"] is filled after the Application exists (the engine needs app.bot to send)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in .env")

    # concurrent_updates: patients are served in parallel (the engine keeps one-at-a-time per patient)
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).concurrent_updates(True).build()

    async def sender(chat_id, text, buttons=None, contact_button=None, remove_keyboard=False):
        markup = None
        if contact_button:  # bottom keyboard with Telegram's "share contact" button
            markup = ReplyKeyboardMarkup([[KeyboardButton(contact_button, request_contact=True)]],
                                         resize_keyboard=True, one_time_keyboard=True)
        elif remove_keyboard:
            markup = ReplyKeyboardRemove()
        elif buttons:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in buttons])
        await app.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)

    engine = Engine(sender)
    engine_holder["engine"] = engine

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user
        await engine.handle_text(chat.id, update.message.text, user.full_name if user else None)

    async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user
        parts = update.message.text.split()
        if parts[0].split("@")[0] == "/start" and len(parts) > 1:  # deep link from the website
            return await engine.handle_start(chat.id, parts[1], user.full_name if user else None)
        await engine.handle_text(chat.id, update.message.text.split()[0].split("@")[0],
                                 user.full_name if user else None)

    async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        # Keep the message, remove its buttons (so they can't be pressed twice) and show what was chosen
        label = pressed_label(query.message.reply_markup if query.message else None, query.data)
        try:
            if label and query.message and query.message.text:
                await query.edit_message_text(with_choice(query.message.text_html, label),
                                              parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                              reply_markup=None)
            else:
                await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        user = update.effective_user
        await engine.handle_button(update.effective_chat.id, query.data, user.full_name if user else None)

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        media = msg.voice or msg.audio
        user = update.effective_user
        await context.bot.send_chat_action(chat_id=msg.chat_id, action="typing")
        tg_file = await media.get_file()
        audio = bytes(await tg_file.download_as_bytearray())
        name = "voice.ogg" if msg.voice else (getattr(media, "file_name", None) or "audio.mp3")
        await engine.handle_voice(msg.chat_id, audio, media.duration or 0, name, user.full_name if user else None)

    async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg, user = update.message, update.effective_user
        own = bool(user and msg.contact.user_id == user.id)
        await engine.handle_contact(msg.chat_id, msg.contact.phone_number, own, user.full_name if user else None)

    async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat:
            await engine.handle_non_text(update.effective_chat.id)

    async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
        log.error("Telegram error: %s", context.error, exc_info=context.error)

    async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
        try:
            await engine.run_reminders()
        except Exception:
            log.exception("reminder job failed")

    async def calcom_sync_job(context: ContextTypes.DEFAULT_TYPE):
        try:
            await engine.sync_with_calcom()
        except Exception:
            log.exception("Cal.com sync job failed")

    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["start", "menu", "language", "track"], on_command, filters=private))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(private & (filters.VOICE | filters.AUDIO), on_voice))
    app.add_handler(MessageHandler(private & filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(private & ~filters.TEXT, on_other))
    app.add_error_handler(on_error)
    app.job_queue.run_repeating(reminder_job, interval=settings.REMINDER_CHECK_SECONDS, first=15)
    app.job_queue.run_repeating(calcom_sync_job, interval=settings.CAL_SYNC_SECONDS, first=30)
    return app
