"""Async Gemini API wrapper with Jarvis function-calling tools."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types

from config import Settings
from services.calendar_service import CalendarService
from services.gmail_service import GmailService
from services.news_service import NewsService

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def build_safety_settings() -> list[types.SafetySetting]:
    """Default safety thresholds applied to every generation request."""

    threshold = types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
    categories = (
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
    return [
        types.SafetySetting(category=category, threshold=threshold)
        for category in categories
    ]


def build_butler_tools() -> types.Tool:
    """Declare Gmail, Calendar, and news functions for Gemini."""

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="fetch_unread_emails",
                description=(
                    "Retrieve a concise summary of unread emails from Sir's Gmail inbox."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "How many unread emails to fetch (default 5, max 15).",
                        }
                    },
                },
            ),
            types.FunctionDeclaration(
                name="fetch_news_digest",
                description=(
                    "Fetch notable recent news. Use category 'science', 'gaming', or 'all'."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["science", "gaming", "all"],
                            "description": "News category to retrieve.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of stories per request (default 5).",
                        },
                    },
                },
            ),
            types.FunctionDeclaration(
                name="create_calendar_event",
                description=(
                    "Create an event on Sir's primary Google Calendar. "
                    "Call only when the date and time are explicit."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Event title.",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start time in ISO 8601, e.g. 2026-09-24T18:00:00.",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration in minutes. Default 30.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional event notes.",
                        },
                    },
                    "required": ["title", "start_time"],
                },
            ),
            types.FunctionDeclaration(
                name="get_calendar_events",
                description="List events on Sir's primary calendar between two ISO timestamps.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "time_min": {
                            "type": "string",
                            "description": "Window start in ISO 8601.",
                        },
                        "time_max": {
                            "type": "string",
                            "description": "Window end in ISO 8601.",
                        },
                    },
                    "required": ["time_min", "time_max"],
                },
            ),
        ]
    )


class GeminiService:
    """Async wrapper around `genai.Client` with a butler tool loop."""

    def __init__(
        self,
        settings: Settings,
        gmail: GmailService,
        calendar: CalendarService,
        news: NewsService,
    ) -> None:
        self._settings = settings
        self._gmail = gmail
        self._calendar = calendar
        self._news = news
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._safety_settings = build_safety_settings()
        self._tools = [build_butler_tools()]

    def _generation_config(self, *, with_tools: bool) -> types.GenerateContentConfig:
        config_kwargs: dict[str, Any] = {
            "system_instruction": self._settings.SYSTEM_INSTRUCTION,
            "safety_settings": self._safety_settings,
            "temperature": 0.7,
        }
        if with_tools:
            config_kwargs["tools"] = self._tools
        return types.GenerateContentConfig(**config_kwargs)

    async def stream_chat_response(
        self,
        history: list[dict[str, Any]],
        new_message: str,
    ) -> AsyncIterator[str]:
        """Yield text chunks, executing Gemini tool calls between rounds if needed."""

        contents: list[types.Content | dict[str, Any]] = list(history)
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=new_message)],
            )
        )

        try:
            for _round in range(MAX_TOOL_ROUNDS):
                function_calls: list[Any] = []
                model_parts: list[Any] = []
                stream = await self._client.aio.models.generate_content_stream(
                    model=self._settings.GEMINI_MODEL,
                    contents=contents,
                    config=self._generation_config(with_tools=True),
                )
                async for chunk in stream:
                    calls = _extract_function_calls(chunk)
                    if calls:
                        function_calls.extend(calls)
                    parts = _extract_content_parts(chunk)
                    if parts:
                        model_parts.extend(parts)
                    if calls:
                        continue
                    text = _safe_chunk_text(chunk)
                    if text:
                        yield text

                if not function_calls:
                    return

                contents.append(
                    types.Content(
                        role="model",
                        parts=model_parts
                        or [
                            types.Part.from_function_call(
                                name=str(call.name),
                                args=dict(call.args or {}),
                            )
                            for call in function_calls
                        ],
                    )
                )
                tool_parts = await self._execute_function_calls(function_calls)
                # Gemini 2.x/3.x rejects role "tool"; function results must be "user".
                contents.append(types.Content(role="user", parts=tool_parts))

            stream = await self._client.aio.models.generate_content_stream(
                model=self._settings.GEMINI_MODEL,
                contents=contents,
                config=self._generation_config(with_tools=False),
            )
            async for chunk in stream:
                text = _safe_chunk_text(chunk)
                if text:
                    yield text
        except Exception:
            logger.exception("Gemini streaming request failed")
            raise

    async def analyze_image(
        self,
        image_bytes: bytes,
        caption: str,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Run a non-streaming multimodal request against the configured model."""

        prompt = caption.strip() or "Describe this image in detail."
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part.from_text(text=prompt),
                ],
            )
        ]

        try:
            response = await self._client.aio.models.generate_content(
                model=self._settings.GEMINI_MODEL,
                contents=contents,
                config=self._generation_config(with_tools=False),
            )
        except Exception:
            logger.exception("Gemini image analysis request failed")
            raise

        text = getattr(response, "text", None)
        if not text:
            logger.warning("Gemini returned an empty image analysis response")
            return "Sir, I could not make anything useful of this image."
        return text

    async def _execute_function_calls(self, calls: list[Any]) -> list[types.Part]:
        parts: list[types.Part] = []
        for call in calls:
            name = str(getattr(call, "name", "") or "")
            raw_args = getattr(call, "args", None) or {}
            args = dict(raw_args)
            logger.info("Executing butler tool %s", name)
            try:
                result = await self._dispatch_tool(name, args)
            except Exception as exc:
                logger.exception("Tool %s failed", name)
                result = {"error": f"Tool '{name}' failed: {exc}"}
            payload = _json_safe({"result": result})
            parts.append(types.Part.from_function_response(name=name, response=payload))
        return parts

    async def _dispatch_tool(self, name: str, args: dict[str, Any]) -> Any:
        if name == "fetch_unread_emails":
            return await self._gmail.fetch_unread_emails(limit=int(args.get("limit", 5)))
        if name == "fetch_news_digest":
            return await self._news.fetch_news_digest(
                category=str(args.get("category", "all")),
                limit=int(args.get("limit", 5)),
            )
        if name == "create_calendar_event":
            return await self._calendar.create_calendar_event(
                title=str(args.get("title", "")),
                start_time=str(args.get("start_time", "")),
                duration_minutes=int(args.get("duration_minutes", 30) or 30),
                description=str(args.get("description", "") or ""),
            )
        if name == "get_calendar_events":
            return await self._calendar.get_calendar_events(
                time_min=str(args.get("time_min", "")),
                time_max=str(args.get("time_max", "")),
            )
        return {"error": f"Unknown tool '{name}'."}

    async def aclose(self) -> None:
        """Close the underlying async HTTP client if the SDK exposes it."""

        close = getattr(self._client.aio, "aclose", None)
        if close is not None:
            await close()
            logger.info("Gemini async client closed")


def _extract_function_calls(chunk: Any) -> list[Any]:
    calls = getattr(chunk, "function_calls", None)
    if calls:
        return list(calls)
    found: list[Any] = []
    for candidate in getattr(chunk, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            function_call = getattr(part, "function_call", None)
            if function_call:
                found.append(function_call)
    return found


def _extract_content_parts(chunk: Any) -> list[Any]:
    parts: list[Any] = []
    for candidate in getattr(chunk, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            parts.append(part)
    return parts


def _safe_chunk_text(chunk: Any) -> str | None:
    try:
        text = chunk.text
    except Exception:
        return None
    return text or None


def _json_safe(value: Any) -> dict[str, Any]:
    try:
        json.dumps(value)
        return value if isinstance(value, dict) else {"result": value}
    except TypeError:
        return {"result": str(value)}
