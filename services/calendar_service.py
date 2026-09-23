"""Google Calendar API wrapper for schedule inspection and event creation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from config import Settings
from utils.oauth import load_google_credentials

logger = logging.getLogger(__name__)


class CalendarService:
    """Reads and writes events on the user's primary Google Calendar."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_calendar_events(
        self,
        time_min: str,
        time_max: str,
    ) -> list[dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._get_events_sync, time_min, time_max)
        except Exception as exc:
            logger.exception("Failed to list calendar events")
            return [{"error": f"Sir, I could not read the calendar. Details: {exc}"}]

    async def create_calendar_event(
        self,
        title: str,
        start_time: str,
        duration_minutes: int = 30,
        description: str = "",
    ) -> dict[str, Any]:
        try:
            duration = max(1, int(duration_minutes or 30))
            return await asyncio.to_thread(
                self._create_event_sync,
                title,
                start_time,
                duration,
                description or "",
            )
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("Failed to create calendar event")
            return {"error": f"Sir, I could not create that event. Details: {exc}"}

    def _service(self) -> Any:
        creds = load_google_credentials(self._settings)
        if creds is None:
            raise RuntimeError(
                "Google OAuth is not configured. Place credentials.json in the bot "
                "folder and run: python -m utils.setup_oauth"
            )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _get_events_sync(self, time_min: str, time_max: str) -> list[dict[str, Any]]:
        start = _parse_iso(time_min, self._settings.GOOGLE_CALENDAR_TIMEZONE)
        end = _parse_iso(time_max, self._settings.GOOGLE_CALENDAR_TIMEZONE)
        events = (
            self._service()
            .events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=25,
            )
            .execute()
        )
        items = []
        for event in events.get("items") or []:
            items.append(
                {
                    "id": event.get("id"),
                    "title": event.get("summary", "(no title)"),
                    "start": event.get("start", {}),
                    "end": event.get("end", {}),
                    "description": event.get("description", ""),
                    "html_link": event.get("htmlLink", ""),
                }
            )
        return items

    def _create_event_sync(
        self,
        title: str,
        start_time: str,
        duration_minutes: int,
        description: str,
    ) -> dict[str, Any]:
        tz_name = self._settings.GOOGLE_CALENDAR_TIMEZONE
        start = _parse_iso(start_time, tz_name)
        end = start + timedelta(minutes=duration_minutes)
        created = (
            self._service()
            .events()
            .insert(
                calendarId="primary",
                body={
                    "summary": title,
                    "description": description,
                    "start": {
                        "dateTime": start.isoformat(),
                        "timeZone": tz_name,
                    },
                    "end": {
                        "dateTime": end.isoformat(),
                        "timeZone": tz_name,
                    },
                },
            )
            .execute()
        )
        return {
            "id": created.get("id"),
            "title": created.get("summary"),
            "start": created.get("start"),
            "end": created.get("end"),
            "html_link": created.get("htmlLink", ""),
            "status": created.get("status", "confirmed"),
        }


def _parse_iso(value: str, default_tz: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("A date and time are required.")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_tz))
    return parsed.astimezone(ZoneInfo(default_tz))
