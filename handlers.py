"""Aiogram command and message handlers for Jarvis."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import Settings
from database import AsyncDatabase
from gemini_service import GeminiService
from utils import clip_telegram_text, stream_to_telegram

logger = logging.getLogger(__name__)

router = Router(name="jarvis_butler")

WELCOME_TEXT = (
    "Good day, Sir. Jarvis at your service.\n\n"
    "I can converse, analyse photographs, summarise unread mail, "
    "brief you on science and gaming news, and manage your calendar.\n\n"
    "Commands:\n"
    "/start — this briefing\n"
    "/clear — erase our prior conversation"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT)


@router.message(Command("clear"))
async def cmd_clear(message: Message, db: AsyncDatabase) -> None:
    user_id = message.from_user.id if message.from_user else message.chat.id
    try:
        await db.clear_history(user_id)
    except Exception:
        logger.exception("Failed to clear history for user_id=%s", user_id)
        await message.answer("Sir, I could not clear our history just now.")
        return
    await message.answer("Consider the slate wiped clean, Sir.")


@router.message(F.photo)
async def handle_photo(
    message: Message,
    db: AsyncDatabase,
    gemini: GeminiService,
) -> None:
    if message.bot is None or not message.photo:
        return

    user_id = message.from_user.id if message.from_user else message.chat.id
    caption = message.caption or ""
    photo = message.photo[-1]

    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        )
        file = await message.bot.download(photo)
        if file is None:
            await message.answer("Sir, I could not retrieve that photograph.")
            return
        image_bytes = file.read() if hasattr(file, "read") else bytes(file)
    except Exception:
        logger.exception("Failed to download photo for user_id=%s", user_id)
        await message.answer("Sir, the photograph could not be downloaded.")
        return

    history_text = f"[Photo] {caption}".strip() if caption else "[Photo]"
    try:
        await db.add_message(user_id, "user", history_text)
        reply = await gemini.analyze_image(image_bytes, caption)
        await db.add_message(user_id, "model", reply)
    except Exception:
        logger.exception("Photo analysis failed for user_id=%s", user_id)
        await message.answer("Sir, I was unable to analyse this image at present.")
        return

    await message.answer(clip_telegram_text(reply))


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text(
    message: Message,
    db: AsyncDatabase,
    gemini: GeminiService,
    settings: Settings,
) -> None:
    if message.bot is None:
        return

    text = (message.text or "").strip()
    if not text:
        return

    user_id = message.from_user.id if message.from_user else message.chat.id

    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        )
        await db.add_message(user_id, "user", text)
        history = await db.get_history(user_id, settings.MAX_HISTORY_MESSAGES)
        if history and history[-1].get("role") == "user":
            history = history[:-1]

        chunks = gemini.stream_chat_response(history, text)
        final_text = await stream_to_telegram(
            message,
            chunks,
            min_edit_interval=settings.STREAM_EDIT_INTERVAL,
        )
        if final_text:
            await db.add_message(user_id, "model", final_text)
    except Exception:
        logger.exception("Text handling failed for user_id=%s", user_id)
        await message.answer("Sir, something went awry. Kindly try again.")
