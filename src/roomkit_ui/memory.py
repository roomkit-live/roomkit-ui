"""Persistent conversation memory.

Sessions share one durable room backed by roomkit's ``SQLiteStore``, so the
transcript survives the process: the voice-channel AI rebuilds its context
from the room automatically, the realtime providers (whose context lives
server-side and starts blank) get a recap of recent exchanges injected into
the system prompt, and the ``recall_conversations`` tool lets the agent
search the whole history ("what did we talk about last week?") through the
store's FTS5 index.

``SQLiteStore`` ships in roomkit after 0.45.0 — on an older roomkit
:func:`build_store` returns ``None`` and every session behaves exactly as
before (in-memory, forgotten at exit).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# One durable room for all sessions, both modes. VC and realtime write the
# same timeline, so a discussion started in one mode is remembered in the
# other.
ROOM_ID = "main"

RECALL_TOOL: dict = {
    "type": "function",
    "name": "recall_conversations",
    "description": (
        "Search past conversations with the user (full-text, all previous "
        "sessions). Call this when the user refers to something discussed "
        "earlier — 'last week', 'the other day', 'remember when'. Returns "
        "matching exchanges with their dates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words to search for in past conversations.",
            }
        },
        "required": ["query"],
    },
}


def conversations_db_path() -> Path:
    """Platform data path for the conversation database."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "RoomKit UI"
    else:
        base = Path.home() / ".local" / "share" / "roomkit-ui"
    return base / "conversations.db"


def build_store(settings: dict) -> Any | None:
    """A persistent store, or ``None`` when disabled or unavailable."""
    if not settings.get("conversation_memory", True):
        return None
    try:
        from roomkit.store.sqlite import SQLiteStore
    except ImportError:
        logger.info("roomkit has no SQLiteStore — conversation memory disabled")
        return None
    return SQLiteStore(conversations_db_path())


def memory_active(settings: dict) -> bool:
    """Whether sessions will run with a persistent store."""
    if not settings.get("conversation_memory", True):
        return False
    try:
        from roomkit.store.sqlite import SQLiteStore  # noqa: F401
    except ImportError:
        return False
    return True


async def ensure_room(kit: Any) -> None:
    """Create the durable room once; later sessions reuse it.

    ``create_room`` on an existing id would reset the room row (counters,
    metadata) over a kept timeline — reuse must go through ``room_exists``.
    """
    if not await kit.store.room_exists(ROOM_ID):
        await kit.create_room(room_id=ROOM_ID)


def _event_role(event: Any) -> str:
    role = (event.metadata or {}).get("role") if hasattr(event, "metadata") else None
    if role:
        return str(role)
    source = getattr(event, "source", None)
    if source is not None and getattr(source, "channel_id", "") == "ai":
        return "assistant"
    return "user"


def _event_text(event: Any) -> str:
    return str(getattr(event.content, "body", "") or "")


async def memory_recap(kit: Any, *, limit: int = 14, max_line_chars: int = 200) -> str:
    """A system-prompt block recapping the most recent stored exchanges.

    Empty string when there is no history. Realtime providers keep their
    context server-side, so this is the only way past sessions reach them.
    """
    try:
        events = await kit.store.get_conversation(ROOM_ID, limit=limit)
    except Exception:
        logger.exception("Failed to load conversation recap")
        return ""
    lines = []
    for event in events:
        text = _event_text(event).strip()
        if not text:
            continue
        if len(text) > max_line_chars:
            text = text[: max_line_chars - 1] + "…"
        stamp = event.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"- [{stamp}] {_event_role(event)}: {text}")
    if not lines:
        return ""
    joined = "\n".join(lines)
    return (
        "## Memory of previous conversations\n"
        "You and the user have talked before. The most recent exchanges "
        "(oldest first):\n"
        f"{joined}\n"
        "Use the recall_conversations tool to search older history when the "
        "user refers to a past discussion that is not in this recap."
    )


async def recall_conversations(kit: Any, arguments: dict) -> str:
    """Handle the recall_conversations tool call. Returns a JSON string."""
    store = getattr(kit, "store", None) if kit is not None else None
    if store is None or not hasattr(store, "search_events"):
        return json.dumps({"error": "Conversation memory is not enabled."})
    query = str(arguments.get("query", "")).strip()
    if not query:
        return json.dumps({"error": "A search query is required."})
    try:
        events = await store.search_events(query, room_id=ROOM_ID, limit=8)
    except Exception:
        logger.exception("recall_conversations search failed")
        return json.dumps({"error": "The conversation search failed."})
    results = [
        {
            "when": event.created_at.strftime("%Y-%m-%d %H:%M"),
            "speaker": _event_role(event),
            "text": _event_text(event),
        }
        for event in events
    ]
    if not results:
        return json.dumps({"results": [], "note": "No past conversation matches this query."})
    return json.dumps({"results": results}, ensure_ascii=False)
