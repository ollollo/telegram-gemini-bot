"""Helpers for throttled Telegram message edits during Gemini streaming."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
THINKING_PLACEHOLDER = "At once, Sir…"


def clip_telegram_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Trim text to Telegram's message length limit."""

    if len(text) <= limit:
        return text
    suffix = "…"
    return text[: limit - len(suffix)] + suffix


async def _safe_edit_text(status_message: Message, text: str) -> bool:
    """Edit a message, ignoring no-op updates and backing off on 429s."""

    try:
        await status_message.edit_text(text)
        return True
    except TelegramRetryAfter as exc:
        logger.warning(
            "Telegram rate limit while editing message_id=%s, retry in %.1fs",
            status_message.message_id,
            exc.retry_after,
        )
        await asyncio.sleep(float(exc.retry_after))
        try:
            await status_message.edit_text(text)
            return True
        except TelegramBadRequest:
            return False
    except TelegramBadRequest as exc:
        logger.debug("Ignored TelegramBadRequest during edit: %s", exc)
        return False


async def stream_to_telegram(
    message: Message,
    text_generator: AsyncIterator[str],
    min_edit_interval: float = 1.2,
) -> str:
    """Stream Gemini chunks into a single Telegram message with throttling."""

    status_message = await message.answer(THINKING_PLACEHOLDER)
    buffer = ""
    last_edit_at = 0.0
    last_sent = THINKING_PLACEHOLDER

    try:
        async for chunk in text_generator:
            if not chunk:
                continue
            buffer += chunk
            now = time.monotonic()
            if now - last_edit_at < min_edit_interval:
                continue

            display = clip_telegram_text(buffer)
            if display == last_sent:
                last_edit_at = now
                continue

            if await _safe_edit_text(status_message, display):
                last_sent = display
            last_edit_at = time.monotonic()
    except Exception:
        logger.exception("Streaming generator failed; sending fallback text")
        if not buffer.strip():
            fallback = "Sir, I encountered an error while composing a reply."
            await _safe_edit_text(status_message, fallback)
            return ""

    final_text = buffer.strip()
    display = clip_telegram_text(
        final_text or "Sir, I was unable to compose a response. Please try again."
    )
    if display != last_sent:
        await _safe_edit_text(status_message, display)
    return final_text
