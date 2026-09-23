"""RSS aggregator for science and gaming news."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import feedparser

from config import Settings
from services import parse_feed_list, sanitize_untrusted_text

logger = logging.getLogger(__name__)


class NewsService:
    """Fetches and normalizes RSS items from configured science/gaming feeds."""

    def __init__(self, settings: Settings) -> None:
        self._feeds: dict[str, list[str]] = {
            "science": parse_feed_list(settings.RSS_SCIENCE_FEEDS),
            "gaming": parse_feed_list(settings.RSS_GAMING_FEEDS),
        }

    async def fetch_news_digest(
        self,
        category: str = "all",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        try:
            capped = max(1, min(int(limit), 10))
            key = (category or "all").strip().lower()
            if key not in {"all", "science", "gaming"}:
                return [{"error": "Category must be 'science', 'gaming', or 'all'."}]
            return await asyncio.to_thread(self._fetch_sync, key, capped)
        except Exception as exc:
            logger.exception("Failed to fetch news digest")
            return [
                {
                    "error": (
                        "Sir, I was unable to retrieve the news digest at this moment. "
                        f"Details: {exc}"
                    )
                }
            ]

    def _fetch_sync(self, category: str, limit: int) -> list[dict[str, Any]]:
        targets = (
            self._feeds.items()
            if category == "all"
            else [(category, self._feeds[category])]
        )
        collected: list[dict[str, Any]] = []
        for name, urls in targets:
            remaining = limit if category != "all" else max(1, limit // 2)
            collected.extend(self._parse_category(name, urls, remaining))
        if not collected:
            return [{"error": "No news items were available from the configured feeds."}]
        return collected[: limit if category != "all" else limit]

    def _parse_category(self, category: str, urls: list[str], limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for url in urls:
            if len(items) >= limit:
                break
            try:
                parsed = feedparser.parse(url)
            except Exception:
                logger.exception("RSS parse failed for %s", url)
                continue
            for entry in parsed.entries:
                if len(items) >= limit:
                    break
                summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                items.append(
                    {
                        "title": getattr(entry, "title", "Untitled"),
                        "summary": sanitize_untrusted_text(str(summary), limit=400),
                        "link": getattr(entry, "link", ""),
                        "published": getattr(entry, "published", "")
                        or getattr(entry, "updated", ""),
                        "category": category,
                    }
                )
        return items
