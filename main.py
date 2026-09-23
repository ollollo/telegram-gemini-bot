"""Application entrypoint: initialize services and start aiogram polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp.resolver import ThreadedResolver
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage

from config import Settings, get_settings
from database import AsyncDatabase
from gemini_service import GeminiService
from handlers import router
from services.calendar_service import CalendarService
from services.gmail_service import GmailService
from services.news_service import NewsService

logger = logging.getLogger(__name__)


def build_telegram_session(proxy: str | None) -> AiohttpSession:
    """Build an aiohttp session that does not use aiodns.

    On Windows, aiohttp's default AsyncResolver (aiodns/pycares) often fails
    with ``Timeout while contacting DNS servers`` for api.telegram.org.
    ThreadedResolver uses the OS DNS stack instead.
    """

    cleaned = proxy.strip() if proxy else None
    session = AiohttpSession(proxy=cleaned)
    session._connector_init["resolver"] = ThreadedResolver()
    return session


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    configure_logging()
    settings: Settings = get_settings()

    db = AsyncDatabase(settings.DATABASE_PATH)
    await db.init_db()

    gmail = GmailService(settings)
    calendar = CalendarService(settings)
    news = NewsService(settings)
    gemini = GeminiService(settings, gmail=gmail, calendar=calendar, news=news)
    # Plain text: Gemini chunks often contain `<`/`>` that break Telegram HTML.
    bot = Bot(token=settings.BOT_TOKEN, session=build_telegram_session(settings.TELEGRAM_PROXY))
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    dispatcher.workflow_data.update(
        {
            "db": db,
            "gemini": gemini,
            "settings": settings,
        }
    )

    async def on_shutdown() -> None:
        logger.info("Shutting down…")
        await gemini.aclose()
        await db.close()
        await bot.session.close()

    dispatcher.shutdown.register(on_shutdown)

    logger.info("Starting polling for model=%s", settings.GEMINI_MODEL)
    retry_delay = 2.0
    while True:
        try:
            await dispatcher.start_polling(bot)
            break
        except TelegramNetworkError:
            logger.exception(
                "Telegram API is unreachable (DNS/network). Retrying in %.0fs. "
                "If this keeps failing, set TELEGRAM_PROXY in .env.",
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


if __name__ == "__main__":
    asyncio.run(main())
