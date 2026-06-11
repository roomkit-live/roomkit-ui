"""Tests for MCP schema cleaning and stdio config parsing."""

import os

from roomkit_ui.mcp_manager import _clean_schema, _parse_stdio_config


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


def test_parse_stdio_env_merges_with_process_env():
    cfg = {"command": "server", "env": "FOO=bar\nBAZ = qux value "}
    _, _, env = _parse_stdio_config(cfg)
    assert env is not None
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "qux value"
    assert env["PATH"] == os.environ["PATH"]  # inherits process env


def test_parse_stdio_empty_command():
    cmd, args, env = _parse_stdio_config({})
    assert cmd == ""
    assert args == []
    assert env is None
