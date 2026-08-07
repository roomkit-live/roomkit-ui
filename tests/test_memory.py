"""Tests for persistent conversation memory (roomkit_ui.memory)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from roomkit_ui.memory import (
    ROOM_ID,
    build_store,
    ensure_room,
    memory_active,
    memory_recap,
    recall_conversations,
)


def _sqlite_available() -> bool:
    try:
        from roomkit.store.sqlite import SQLiteStore  # noqa: F401
    except ImportError:
        return False
    return True


def _event(text: str, role: str, when: str = "2026-08-01 10:00") -> SimpleNamespace:
    return SimpleNamespace(
        content=SimpleNamespace(body=text),
        metadata={"role": role},
        source=SimpleNamespace(channel_id="voice"),
        created_at=datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=UTC),
    )


class _FakeStore:
    def __init__(self, events=(), hits=()):
        self._events = list(events)
        self._hits = list(hits)
        self.search_queries: list[str] = []

    async def get_conversation(self, room_id, *, limit=50):
        assert room_id == ROOM_ID
        return self._events[-limit:]

    async def search_events(self, query, *, room_id=None, limit=20):
        self.search_queries.append(query)
        return self._hits[:limit]


def _kit(store) -> SimpleNamespace:
    return SimpleNamespace(store=store)


def test_memory_disabled_by_setting():
    assert build_store({"conversation_memory": False}) is None
    assert memory_active({"conversation_memory": False}) is False


def test_memory_availability_follows_roomkit():
    assert memory_active({}) is _sqlite_available()
    store = build_store({})
    assert (store is not None) is _sqlite_available()


async def test_recap_formats_roles_dates_and_truncates():
    events = [
        _event("on a parlé du chantier AEC", "user", "2026-08-01 10:00"),
        _event("x" * 500, "assistant", "2026-08-01 10:01"),
        _event("", "user"),
    ]
    recap = await memory_recap(_kit(_FakeStore(events=events)))
    assert "## Memory of previous conversations" in recap
    assert "- [2026-08-01 10:00] user: on a parlé du chantier AEC" in recap
    assert "assistant: " + "x" * 199 + "…" in recap
    assert recap.count("\n- ") == 2  # the empty event is dropped


async def test_recap_empty_history_is_empty_string():
    assert await memory_recap(_kit(_FakeStore())) == ""


async def test_recall_returns_hits_as_json():
    hits = [_event("le projet dont tu parlais", "assistant", "2026-07-30 18:22")]
    store = _FakeStore(hits=hits)
    out = json.loads(await recall_conversations(_kit(store), {"query": "projet"}))
    assert store.search_queries == ["projet"]
    assert out["results"] == [
        {"when": "2026-07-30 18:22", "speaker": "assistant", "text": "le projet dont tu parlais"}
    ]


async def test_recall_without_store_or_query_reports_legibly():
    out = json.loads(await recall_conversations(None, {"query": "x"}))
    assert "error" in out
    out = json.loads(await recall_conversations(_kit(object()), {"query": "x"}))
    assert "error" in out
    out = json.loads(await recall_conversations(_kit(_FakeStore()), {"query": " "}))
    assert "error" in out


async def test_recall_no_match_says_so():
    out = json.loads(await recall_conversations(_kit(_FakeStore()), {"query": "introuvable"}))
    assert out["results"] == []
    assert "note" in out


@pytest.mark.skipif(not _sqlite_available(), reason="installed roomkit has no SQLiteStore")
async def test_ensure_room_survives_two_kit_lifecycles(tmp_path):
    from roomkit import RoomKit
    from roomkit.store.sqlite import SQLiteStore

    kit = RoomKit(store=SQLiteStore(tmp_path / "m.db"))
    await ensure_room(kit)
    room = await kit.store.get_room(ROOM_ID)
    await kit.close()

    kit2 = RoomKit(store=SQLiteStore(tmp_path / "m.db"))
    await ensure_room(kit2)  # must reuse, not reset
    room2 = await kit2.store.get_room(ROOM_ID)
    assert room2.created_at == room.created_at
    await kit2.close()
