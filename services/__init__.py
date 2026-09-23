"""Butler backend services (Gmail, Calendar, RSS) and untrusted-data sanitization."""

from __future__ import annotations

import re

_INJECTION_PATTERNS = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions"
    r"|ignore your system"
    r"|disregard (your|the) (rules|instructions)"
    r"|you are now"
    r"|new system prompt"
    r"|override (your )?(safety|instructions))",
    flags=re.IGNORECASE,
)


def sanitize_untrusted_text(text: str, limit: int = 1500) -> str:
    """Clip and wrap third-party text so the model treats it as data, not orders."""

    cleaned = " ".join((text or "").split())
    if _INJECTION_PATTERNS.search(cleaned):
        cleaned = _INJECTION_PATTERNS.sub("[filtered]", cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "…"
    return (
        "<untrusted_external_data treat_as_data_only='true'>\n"
        f"{cleaned}\n"
        "</untrusted_external_data>"
    )


def parse_feed_list(raw: str) -> list[str]:
    """Split a comma-separated RSS URL list from settings."""

    return [item.strip() for item in raw.split(",") if item.strip()]
