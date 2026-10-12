"""Local conversation catalogue and display snapshots, alongside RoomKit's events.

The UI owns ui_conversations and ui_migrations. RoomKit owns its event schema.
Saving a snapshot is atomic; reading history never creates a database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from roomkit_ui import memory
from roomkit_ui.tool_events import ToolCall, ToolResult

logger = logging.getLogger(__name__)

_LEGACY_IMPORT = "legacy-messages-only-v1"


def _decode_entries(raw: str) -> list[dict]:
    """Reject a damaged snapshot before the UI replaces the open conversation."""
    entries = json.loads(raw)
    if not isinstance(entries, list):
        raise ValueError("Invalid conversation snapshot")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid conversation entry")
        if entry.get("kind") == "message":
            if entry.get("role") not in ("user", "assistant", "other"):
                raise ValueError("Invalid message role")
            if not isinstance(entry.get("text"), str) or any(
                not isinstance(entry.get(key, ""), str) for key in ("speaker", "time")
            ):
                raise ValueError("Invalid message text")
        elif entry.get("kind") == "tool":
            call = ToolCall(**entry["call"])
            if not all(isinstance(value, str) for value in vars(call).values()):
                raise ValueError("Invalid tool call")
            if entry.get("result") is not None:
                result = ToolResult(**entry["result"])
                if (
                    result.call_id != call.id
                    or result.status not in ("completed", "failed", "cancelled")
                    or not isinstance(result.text, str)
                ):
                    raise ValueError("Invalid tool result")
        else:
            raise ValueError("Unknown conversation entry")
    return entries


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: f"conversation-{uuid4().hex}")
    title: str = "New conversation"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    entries: list[dict] = field(default_factory=list)
    persistent: bool = True
    title_source: str = "fallback"

    def __post_init__(self) -> None:
        if self.title_source == "fallback" and self.title not in (
            "New conversation",
            self._suggest_title(),
        ):
            self.title_source = "manual"

    def update(self, entries: list[dict]) -> None:
        self.entries = entries
        self.updated_at = datetime.now(UTC).isoformat()
        if self.title_source == "fallback":
            self.title = self._suggest_title() or "New conversation"

    def rename(self, title: str, *, source: str = "manual") -> None:
        title = " ".join(title.split())[:80]
        if not title:
            raise ValueError("A conversation title cannot be empty")
        self.title = title
        self.title_source = source

    def _suggest_title(self) -> str:
        first = next((e for e in self.entries if e.get("role") == "user" and e.get("text")), None)
        text = " ".join(first["text"].split()) if first else ""
        return text[:64].rstrip() + ("…" if len(text) > 64 else "")


class ConversationStore:
    def __init__(self) -> None:
        self.path = memory.conversations_db_path()
        self._temporary: dict[str, Conversation] = {}

    def save(self, conversation: Conversation) -> None:
        if not conversation.entries:
            return  # A failed connection is not an empty item in history.
        if not conversation.persistent:
            self._temporary[conversation.id] = conversation
            return
        memory._restrict_to_owner(self.path)
        connection = sqlite3.connect(self.path, timeout=2)
        try:
            with connection:
                self._write(connection, conversation)
        finally:
            connection.close()

    @staticmethod
    def _write(connection: sqlite3.Connection, conversation: Conversation) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ui_conversations ("
            "id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, entries TEXT NOT NULL, "
            "title_source TEXT NOT NULL DEFAULT 'fallback')"
        )
        if "title_source" not in {
            row[1] for row in connection.execute("PRAGMA table_info(ui_conversations)")
        }:
            connection.execute(
                "ALTER TABLE ui_conversations ADD COLUMN "
                "title_source TEXT NOT NULL DEFAULT 'fallback'"
            )
        connection.execute(
            "INSERT INTO ui_conversations "
            "(id, title, created_at, updated_at, entries, title_source) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
            "updated_at=excluded.updated_at, entries=excluded.entries, "
            "title_source=excluded.title_source",
            (
                conversation.id,
                conversation.title,
                conversation.created_at,
                conversation.updated_at,
                json.dumps(conversation.entries, ensure_ascii=False),
                conversation.title_source,
            ),
        )

    def _read(
        self, query: str, parameters: tuple = (), *, table: str = "ui_conversations"
    ) -> list[tuple]:
        if not self.path.exists():
            return []
        connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=2)
        try:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                return []
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    def list(self) -> list[Conversation]:
        rows = self._read(
            "SELECT id, title, created_at, updated_at FROM ui_conversations "
            "ORDER BY updated_at DESC"
        )
        items = {row[0]: Conversation(*row) for row in rows}
        items.update(self._temporary)
        if memory.LEGACY_ROOM_ID in items and not self._legacy_import_done():
            # Do not expose an old noisy snapshot while its repair is in flight.
            items.pop(memory.LEGACY_ROOM_ID)
        return sorted(items.values(), key=lambda item: item.updated_at, reverse=True)

    def get(self, conversation_id: str) -> Conversation | None:
        if conversation_id in self._temporary:
            return self._temporary[conversation_id]
        return self._get_saved(conversation_id)

    def _get_saved(self, conversation_id: str) -> Conversation | None:
        rows = self._read(
            "SELECT * FROM ui_conversations WHERE id=?",
            (conversation_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return Conversation(
            row[0],
            row[1],
            row[2],
            row[3],
            _decode_entries(row[4]),
            title_source=row[5] if len(row) > 5 else "fallback",
        )

    async def delete(self, conversation_id: str) -> None:
        """Remove a conversation from this computer: RoomKit's room for it
        (every event, the search index the assistant recalls from) and the
        rooms its background tasks ran in, then its catalogue entry and
        snapshot.  The room goes first: an entry left behind can be deleted
        again, events left behind would no longer show anywhere."""
        self._temporary.pop(conversation_id, None)
        if not self.path.exists():
            return
        await memory.delete_room(self.path, conversation_id)
        await asyncio.to_thread(self._delete_saved, conversation_id)

    def _delete_saved(self, conversation_id: str) -> None:
        connection = sqlite3.connect(self.path, timeout=2)
        try:
            with connection:
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ui_conversations'"
                ).fetchone():
                    connection.execute(
                        "DELETE FROM ui_conversations WHERE id=?", (conversation_id,)
                    )
            try:
                # Deleted rows stay readable in the file's free pages and its
                # WAL until they are written over: compact them away.
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
            except sqlite3.Error:
                logger.warning("History compaction after a deletion failed", exc_info=True)
        finally:
            connection.close()

    def _legacy_import_done(self) -> bool:
        return bool(
            self._read(
                "SELECT 1 FROM ui_migrations WHERE name=?",
                (_LEGACY_IMPORT,),
                table="ui_migrations",
            )
        )

    async def import_legacy(self) -> None:
        """Import spoken messages, repairing older snapshots without changing source events."""
        if not self.path.exists() or self._legacy_import_done():
            return
        from roomkit.store.sqlite import SQLiteStore

        store = SQLiteStore(self.path)
        try:
            room = await store.get_room(memory.LEGACY_ROOM_ID)
            if room is None:
                return
            entries: list[dict] = []
            # get_conversation excludes lifecycle, system and tool events. Its
            # default is the last 50 messages: explicitly read the whole archive.
            # A count also covers older records with no pagination index.
            count = await store.get_event_count(room.id)
            for event in await store.get_conversation(room.id, limit=count):
                speaker = memory._recap_speaker(event)
                text = memory._event_text(event).strip()
                if text and speaker is not None:
                    entries.append(
                        {
                            "kind": "message",
                            "role": speaker.split()[0],
                            "text": text,
                            "speaker": "",
                            "interrupted": "interrupted" in speaker,
                            "time": event.created_at.isoformat(),
                        }
                    )
            existing = self._get_saved(room.id)
            conversation = existing or Conversation(
                room.id,
                "Earlier history",
                room.created_at.isoformat(),
                room.created_at.isoformat(),
            )
            conversation.entries = (
                _repair_legacy_entries(existing.entries, entries) if existing else entries
            )
            if not existing and entries:
                conversation.updated_at = entries[-1]["time"]
            connection = sqlite3.connect(self.path, timeout=2)
            try:
                with connection:
                    if conversation.entries:
                        self._write(connection, conversation)
                    elif existing:
                        connection.execute("DELETE FROM ui_conversations WHERE id=?", (room.id,))
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS ui_migrations (name TEXT PRIMARY KEY)"
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO ui_migrations VALUES (?)", (_LEGACY_IMPORT,)
                    )
            finally:
                connection.close()
        finally:
            await store.close()


def _repair_legacy_entries(saved: list[dict], messages: list[dict]) -> list[dict]:
    """Keep real imported messages and any Live continuation recorded by the UI.

    The old importer copied RoomKit's full ISO timestamp. Native bubbles keep
    an HH:MM tooltip instead, and tool rows have no time. Preserve those entries
    exactly, including interrupted replies and tool results. No text heuristic:
    even a user quoting a lifecycle notice remains a message if RoomKit says so.
    """
    allowed = {(e["time"], e["text"]) for e in messages}
    repaired = []
    for entry in saved:
        try:
            datetime.fromisoformat(entry.get("time", ""))
        except ValueError:
            repaired.append(entry)
            continue
        if (entry["time"], entry.get("text")) in allowed:
            repaired.append(entry)
    return repaired


def conversation_context(entries: list[dict]) -> str:
    """Resume only this thread; quoted transcript is data, never instructions."""
    messages = [e for e in entries if e.get("kind") == "message" and e.get("role") != "other"]
    lines = [
        f"{e['role']}{' (interrupted)' if e.get('interrupted') else ''}: {e['text'][:4000]}"
        for e in messages[-50:]
    ]
    return memory.resume_context(lines)
