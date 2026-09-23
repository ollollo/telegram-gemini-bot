"""Gmail API wrapper for unread inbox summaries."""

from __future__ import annotations

import asyncio
import base64
import logging
from email.utils import parseaddr
from typing import Any

from bs4 import BeautifulSoup
from googleapiclient.discovery import build

from config import Settings
from services import sanitize_untrusted_text
from utils.oauth import load_google_credentials

logger = logging.getLogger(__name__)


class GmailService:
    """Reads unread INBOX messages using stored OAuth credentials."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch_unread_emails(self, limit: int = 5) -> list[dict[str, Any]]:
        try:
            capped = max(1, min(int(limit), 15))
            return await asyncio.to_thread(self._fetch_unread_emails_sync, capped)
        except Exception as exc:
            logger.exception("Failed to fetch unread emails")
            return [
                {
                    "error": (
                        "Sir, I was unable to reach your inbox at this moment. "
                        f"Details: {exc}"
                    )
                }
            ]

    def _fetch_unread_emails_sync(self, limit: int) -> list[dict[str, Any]]:
        creds = load_google_credentials(self._settings)
        if creds is None:
            return [
                {
                    "error": (
                        "Google OAuth is not configured. Place credentials.json in "
                        "the bot folder and run: python -m utils.setup_oauth"
                    )
                }
            ]

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        listing = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], q="is:unread", maxResults=limit)
            .execute()
        )
        messages = listing.get("messages") or []
        results: list[dict[str, Any]] = []
        for item in messages:
            full = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            headers = {
                header["name"].lower(): header["value"]
                for header in (full.get("payload") or {}).get("headers") or []
            }
            sender = parseaddr(headers.get("from", ""))[1] or headers.get("from", "unknown")
            body = _extract_body(full.get("payload") or {})
            results.append(
                {
                    "sender": sender,
                    "subject": headers.get("subject", "(no subject)"),
                    "date": headers.get("date", ""),
                    "body": sanitize_untrusted_text(body),
                }
            )
        return results


def _extract_body(payload: dict[str, Any]) -> str:
    plain = _find_part_text(payload, "text/plain")
    if plain:
        return plain
    html = _find_part_text(payload, "text/html")
    if html:
        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    snippet_data = (payload.get("body") or {}).get("data")
    if snippet_data:
        return _decode_b64(snippet_data)
    return ""


def _find_part_text(payload: dict[str, Any], mime_type: str) -> str:
    if payload.get("mimeType") == mime_type:
        data = (payload.get("body") or {}).get("data")
        if data:
            return _decode_b64(data)
    for part in payload.get("parts") or []:
        found = _find_part_text(part, mime_type)
        if found:
            return found
    return ""


def _decode_b64(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
