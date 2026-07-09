"""Tests for MCP schema cleaning, stdio config parsing, and tool registration."""

import json
from types import SimpleNamespace

import pytest

from roomkit_ui.mcp_manager import MCPManager, _clean_schema, _parse_stdio_config


def test_clean_schema_strips_rejected_keys_recursively():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "x": {"type": "string", "$schema": "nested"},
            "items": [{"additionalProperties": True, "type": "number"}],
        },
    }
    out = _clean_schema(schema)
    assert "$schema" not in out
    assert "additionalProperties" not in out
    assert "$schema" not in out["properties"]["x"]
    assert "additionalProperties" not in out["properties"]["items"][0]
    assert out["properties"]["items"][0]["type"] == "number"


def test_clean_schema_passes_scalars_through():
    assert _clean_schema("x") == "x"
    assert _clean_schema(3) == 3


def test_parse_stdio_simple_command():
    cmd, args, env = _parse_stdio_config({"command": "uvx mcp-server-fetch"})
    assert cmd == "uvx"
    assert args == ["mcp-server-fetch"]
    assert env is None


def test_parse_stdio_quoted_path_with_spaces():
    cmd, args, env = _parse_stdio_config({"command": '"/Applications/My App/server" --port 1234'})
    assert cmd == "/Applications/My App/server"
    assert args == ["--port", "1234"]


def test_parse_stdio_separate_args_field():
    cmd, args, _ = _parse_stdio_config({"command": "npx", "args": "-y some-server"})
    assert cmd == "npx"
    assert args == ["-y", "some-server"]


def test_parse_stdio_env_only_includes_explicit_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("PATH", "/sensitive/path")
    cfg = {"command": "server", "env": "FOO=bar\nBAZ = qux value "}
    _, _, env = _parse_stdio_config(cfg)
    assert env is not None
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "qux value"
    assert "OPENAI_API_KEY" not in env
    assert "PATH" not in env


def test_parse_stdio_empty_command():
    cmd, args, env = _parse_stdio_config({})
    assert cmd == ""
    assert args == []
    assert env is None


def test_register_tools_tracks_sessions_and_apps():
    mgr = MCPManager([])
    session = object()
    result = SimpleNamespace(
        tools=[
            SimpleNamespace(
                name="plain_tool",
                description="does things",
                inputSchema={"type": "object", "$schema": "x"},
                meta=None,
            ),
            SimpleNamespace(
                name="app_tool",
                description="",
                inputSchema={},
                meta={"ui": {"resourceUri": "ui://widget/main"}},
            ),
        ]
    )
    mgr._register_tools(session, result, "srv")

    assert mgr._tool_to_session["plain_tool"] is session
    assert mgr._tool_to_session["app_tool"] is session
    assert mgr.get_tool_server("plain_tool") == "srv"
    assert mgr.get_tool_server("app_tool") == "srv"
    names = [t["name"] for t in mgr.get_tools()]
    assert names == ["plain_tool", "app_tool"]
    # $schema stripped on the way in
    assert "$schema" not in mgr.get_tools()[0]["parameters"]
    # ui:// tools tracked as MCP Apps with their server name
    assert mgr._app_tools == {"app_tool": {"uri": "ui://widget/main", "server": "srv"}}


@pytest.mark.asyncio
async def test_app_tool_call_is_limited_to_origin_server(monkeypatch):
    mgr = MCPManager([])
    mgr._tool_to_server = {
        "same_server_tool": "srv-a",
        "other_server_tool": "srv-b",
    }

    calls = []

    async def fake_handle_tool_call(name, arguments):
        calls.append((name, arguments))
        return json.dumps({"result": "ok"})

    monkeypatch.setattr(mgr, "handle_tool_call", fake_handle_tool_call)

    allowed = await mgr.handle_app_tool_call("srv-a", "same_server_tool", {"x": 1})
    blocked = await mgr.handle_app_tool_call("srv-a", "other_server_tool", {"x": 2})
    unknown = await mgr.handle_app_tool_call("srv-a", "paste_text", {"text": "secret"})

    assert json.loads(allowed) == {"result": "ok"}
    assert json.loads(blocked) == {"error": "Tool is not available to this MCP App"}
    assert json.loads(unknown) == {"error": "Tool is not available to this MCP App"}
    assert calls == [("same_server_tool", {"x": 1})]
