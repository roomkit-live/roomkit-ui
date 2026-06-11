"""Tests for built-in tool dispatch."""

import json

from roomkit_ui.builtin_tools import BUILTIN_TOOLS, handle_builtin_tool
from roomkit_ui.settings import save_settings


def test_unknown_tool_returns_none():
    assert handle_builtin_tool("definitely_not_a_tool") is None


def test_get_current_date():
    out = json.loads(handle_builtin_tool("get_current_date"))
    assert set(out) == {"date", "day"}
    assert len(out["date"].split("-")) == 3


def test_get_current_time():
    out = json.loads(handle_builtin_tool("get_current_time"))
    assert "time" in out and "timezone" in out


def test_get_roomkit_info():
    out = json.loads(handle_builtin_tool("get_roomkit_info"))
    assert "roomkit" in out and "roomkit_ui" in out


def test_list_attitudes_includes_presets_and_custom():
    save_settings({"custom_attitudes": json.dumps([{"name": "Pirate", "text": "Arr"}])})
    out = json.loads(handle_builtin_tool("list_attitudes"))
    names = [a["name"] for a in out["attitudes"]]
    assert "Pirate" in names
    assert any(a["type"] == "preset" for a in out["attitudes"])


def test_list_attitudes_survives_corrupt_custom_json():
    save_settings({"custom_attitudes": "{not valid json"})
    out = json.loads(handle_builtin_tool("list_attitudes"))
    # Presets still listed; corrupt custom block ignored.
    assert all(a["type"] == "preset" for a in out["attitudes"])
    assert len(out["attitudes"]) > 0


def test_builtin_definitions_have_required_fields():
    for tool in BUILTIN_TOOLS:
        assert tool["name"]
        assert tool["description"]
