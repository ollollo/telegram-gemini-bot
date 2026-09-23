"""Async SQLite storage for per-user conversation history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp DATETIME NOT NULL
);
"""

_CREATE_USER_INDEX = """
CREATE INDEX IF NOT EXISTS idx_messages_user_id_id
ON messages (user_id, id);
"""


class AsyncDatabase:
    """Manages conversation history with a sliding-window query API."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not initialized. Call init_db() first.")
        return self._connection

    async def init_db(self) -> None:
        """Open the SQLite file and create the messages schema."""

        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._connection = await aiosqlite.connect(self._db_path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA journal_mode=WAL;")
            await self._connection.execute("PRAGMA foreign_keys=ON;")
            await self._connection.execute(_CREATE_MESSAGES_TABLE)
            await self._connection.execute(_CREATE_USER_INDEX)
            await self._connection.commit()
            logger.info("Database initialized at %s", self._db_path)
        except aiosqlite.Error:
            logger.exception("Failed to initialize SQLite database")
            raise

    async def close(self) -> None:
        """Close the underlying SQLite connection."""

        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    async def add_message(self, user_id: int, role: str, content: str) -> None:
        """Persist a single chat message."""

        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            await self.connection.execute(
                """
                INSERT INTO messages (user_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, role, content, timestamp),
            )
            await self.connection.commit()
        except aiosqlite.Error:
            logger.exception("Failed to insert message for user_id=%s", user_id)
            raise

    async def get_history(self, user_id: int, limit: int) -> list[dict[str, Any]]:
        """Return the last `limit` messages in chronological order.

        Each item is a Gemini-compatible dict:
        ``{"role": "user"|"model", "parts": [{"text": "..."}]}``.
        """

        try:
            cursor = await self.connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()
        except aiosqlite.Error:
            logger.exception("Failed to load history for user_id=%s", user_id)
            raise

        history: list[dict[str, Any]] = []
        for row in reversed(rows):
            history.append(
                {
                    "role": row["role"],
                    "parts": [{"text": row["content"]}],
                }
            )
        return history

    async def clear_history(self, user_id: int) -> None:
        """Delete all stored messages for a user."""

        try:
            await self.connection.execute(
                "DELETE FROM messages WHERE user_id = ?",
                (user_id,),
            )
            await self.connection.commit()
            logger.info("Cleared history for user_id=%s", user_id)
        except aiosqlite.Error:
            logger.exception("Failed to clear history for user_id=%s", user_id)
            raise
