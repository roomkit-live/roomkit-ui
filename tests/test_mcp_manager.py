"""Tests for MCP schema cleaning, stdio config parsing, and tool registration."""

import asyncio
import json
import os
import sys

import pytest
from roomkit import ToolFailedError

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
    cmd, args, _ = _parse_stdio_config({"command": "no-such-mcp-server-xyz --stdio"})
    # Not found: the name is kept so the spawn error names it.
    assert cmd == "no-such-mcp-server-xyz"
    assert args == ["--stdio"]


def test_parse_stdio_quoted_path_with_spaces():
    cmd, args, env = _parse_stdio_config({"command": '"/Applications/My App/server" --port 1234'})
    assert cmd == "/Applications/My App/server"
    assert args == ["--port", "1234"]


def test_parse_stdio_separate_args_field():
    cmd, args, _ = _parse_stdio_config({"command": "no-such-npx-xyz", "args": "-y some-server"})
    assert cmd == "no-such-npx-xyz"
    assert args == ["-y", "some-server"]


def test_parse_stdio_env_only_includes_explicit_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    cfg = {"command": "server", "env": "FOO=bar\nBAZ = qux value "}
    _, _, env = _parse_stdio_config(cfg)
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "qux value"
    assert "OPENAI_API_KEY" not in env
    assert set(env) == {"FOO", "BAZ", "PATH"}


def test_parse_stdio_empty_command():
    cmd, args, _ = _parse_stdio_config({})
    assert cmd == ""
    assert args == []


def _dock_like_path(monkeypatch, tmp_path):
    """PATH as a Dock-launched .app sees it; tmp_path/bin is a user-install dir."""
    user_bin = tmp_path / "bin"
    user_bin.mkdir()
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr("roomkit_ui.cli_exec._EXTRA_PATH_DIRS", (str(user_bin),))
    return user_bin


def test_parse_stdio_resolves_the_command_on_the_user_install_dirs(monkeypatch, tmp_path):
    user_bin = _dock_like_path(monkeypatch, tmp_path)
    server = user_bin / "my-mcp-server"
    server.write_text("#!/bin/sh\n")
    server.chmod(0o755)

    cmd, args, env = _parse_stdio_config({"command": "my-mcp-server --stdio"})

    assert cmd == str(server)
    assert args == ["--stdio"]
    # The child needs it too: `#!/usr/bin/env node` looks node up on PATH.
    assert str(user_bin) in env["PATH"].split(os.pathsep)


def test_parse_stdio_keeps_a_path_the_server_declares(monkeypatch, tmp_path):
    _dock_like_path(monkeypatch, tmp_path)

    _, _, env = _parse_stdio_config({"command": "server", "env": "PATH=/opt/mine"})

    assert env["PATH"] == "/opt/mine"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang")
async def test_a_stdio_server_whose_interpreter_is_a_user_install_connects(monkeypatch, tmp_path):
    # npx, uvx and `#!/usr/bin/env node` servers failed from a Dock launch.
    user_bin = _dock_like_path(monkeypatch, tmp_path)
    interpreter = user_bin / "my-python"
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    interpreter.chmod(0o755)
    server = user_bin / "time-server"
    server.write_text(
        "#!/usr/bin/env my-python\n"
        "from mcp.server.mcpserver import MCPServer\n"
        "app = MCPServer('t')\n"
        "@app.tool()\n"
        "def now() -> str:\n"
        "    return 'noon'\n"
        "app.run('stdio')\n"
    )
    server.chmod(0o755)
    command, args, env = _parse_stdio_config({"command": "time-server"})

    # Spawned as _connect_one does, but entered and exited in this one task.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await asyncio.wait_for(session.initialize(), timeout=10)
        tools = await asyncio.wait_for(session.list_tools(), timeout=10)

    assert [t.name for t in tools.tools] == ["now"]


def test_register_tools_tracks_sessions_and_apps():
    # Real mcp.types.Tool objects, not SDK look-alikes: the 1.x→2.0 bump
    # renamed inputSchema→input_schema and stubs kept this suite green
    # while the app broke on the first live server.
    from mcp.types import Tool

    mgr = MCPManager([])
    session = object()
    tools = [
        Tool(
            name="plain_tool",
            description="does things",
            input_schema={"type": "object", "$schema": "x"},
        ),
        Tool(
            name="app_tool",
            description="",
            input_schema={},
            meta={"ui": {"resourceUri": "ui://widget/main"}},
        ),
    ]
    mgr._register_tools(session, tools, "srv")

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


def test_register_tools_keeps_first_duplicate_tool():
    mgr = MCPManager([])
    first_session = object()
    second_session = object()
    from mcp.types import Tool

    first = [
        Tool(
            name="duplicate_tool",
            description="first",
            input_schema={},
            meta={"ui": {"resourceUri": "ui://first/main"}},
        )
    ]
    second = [
        Tool(
            name="duplicate_tool",
            description="second",
            input_schema={},
            meta={"ui": {"resourceUri": "ui://second/main"}},
        )
    ]

    mgr._register_tools(first_session, first, "srv-a")
    mgr._register_tools(second_session, second, "srv-b")

    assert mgr._tool_to_session["duplicate_tool"] is first_session
    assert mgr.get_tool_server("duplicate_tool") == "srv-a"
    assert len(mgr.get_tools()) == 1
    assert mgr.get_tools()[0]["description"] == "first"
    assert mgr._app_tools == {"duplicate_tool": {"uri": "ui://first/main", "server": "srv-a"}}


class _PagedSession:
    """Answers tools/list from scripted pages: (tool names, next cursor) per call."""

    def __init__(self, pages: list[tuple[list[str], str | None]]) -> None:
        self.pages = pages
        self.cursors: list[str | None] = []

    async def list_tools(self, *, params=None):
        from mcp.types import ListToolsResult, Tool

        self.cursors.append(params.cursor if params is not None else None)
        names, cursor = self.pages[len(self.cursors) - 1]
        tools = [Tool(name=n, input_schema={}) for n in names]
        return ListToolsResult(tools=tools, next_cursor=cursor)


async def test_every_page_of_a_tool_listing_is_read():
    from roomkit_ui.mcp_manager import _list_all_tools

    session = _PagedSession([(["a", "b"], "p2"), (["c"], "p3"), (["d"], None)])

    tools = await _list_all_tools(session, "srv")

    assert [t.name for t in tools] == ["a", "b", "c", "d"]
    assert session.cursors == [None, "p2", "p3"]


@pytest.mark.parametrize(
    "pages",
    [
        [(["a"], "p2"), ([], "p3")],  # an empty page that still carries a cursor
        [(["a"], "p2"), (["b"], "p2")],  # a cursor handed out twice
    ],
)
async def test_a_listing_that_pages_without_end_keeps_what_it_read(pages, caplog):
    from roomkit_ui.mcp_manager import _list_all_tools

    session = _PagedSession(pages)

    tools = await _list_all_tools(session, "srv")

    assert [t.name for t in tools] == [n for names, _ in pages for n in names]
    assert len(session.cursors) == 2
    assert "pages its tools without end" in caplog.text


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


@pytest.mark.asyncio
async def test_tool_call_reads_the_20_result_shape():
    from mcp.types import CallToolResult, TextContent

    mgr = MCPManager([])

    class _Session:
        def __init__(self, result):
            self._result = result

        async def call_tool(self, name, arguments):
            return self._result

    ok = CallToolResult(content=[TextContent(type="text", text="fine")], is_error=False)
    bad = CallToolResult(content=[TextContent(type="text", text="boom")], is_error=True)

    mgr._tool_to_session = {"ok_tool": _Session(ok), "bad_tool": _Session(bad)}
    assert json.loads(await mgr.handle_tool_call("ok_tool", {})) == {"result": "fine"}
    # A returned {"error": ...} body reaches Gemini as a success (roomkit 0.95):
    # a failure has to be raised to be read as one.
    with pytest.raises(ToolFailedError) as failed:
        await mgr.handle_tool_call("bad_tool", {})
    assert failed.value.message == "boom"


class _RaisingSession:
    def __init__(self, exc):
        self._exc = exc

    async def call_tool(self, name, arguments):
        raise self._exc


@pytest.mark.asyncio
async def test_tool_call_failures_raise_with_the_words_the_model_may_read():
    from mcp.shared.exceptions import MCPError

    mgr = MCPManager([])
    mgr._tool_to_session = {
        "slow": _RaisingSession(TimeoutError()),
        "refused": _RaisingSession(MCPError(-32602, "Invalid params: city")),
        "broken": _RaisingSession(RuntimeError("https://user:pw@host/ is down")),
    }

    with pytest.raises(ToolFailedError, match="timed out"):
        await mgr.handle_tool_call("slow", {})
    with pytest.raises(ToolFailedError) as server_error:
        await mgr.handle_tool_call("refused", {})
    assert server_error.value.message == "Invalid params: city"
    # Anything else: the class, never a message that may carry a secret.
    with pytest.raises(ToolFailedError) as crash:
        await mgr.handle_tool_call("broken", {})
    assert "RuntimeError" in crash.value.message
    assert "pw" not in crash.value.message


@pytest.mark.asyncio
async def test_unknown_tool_keeps_the_envelope_roomkit_reads_as_unserved():
    from roomkit.tools.result import is_unknown_tool_answer

    assert is_unknown_tool_answer(await MCPManager([]).handle_tool_call("nope", {}))


@pytest.mark.asyncio
async def test_app_tool_call_gets_a_failure_as_the_envelope_the_bridge_reads():
    mgr = MCPManager([])
    mgr._tool_to_server = {"bad_tool": "srv-a"}
    mgr._tool_to_session = {"bad_tool": _RaisingSession(TimeoutError())}

    out = json.loads(await mgr.handle_app_tool_call("srv-a", "bad_tool", {}))

    assert "timed out" in out["error"]


async def test_close_all_shuts_a_real_stdio_server_down_promptly(tmp_path):
    # The server's stack used to be closed from a second task: anyio then
    # cancelled the owning task instead, close_all waited its 15 s timeout
    # and hung for good (plain asyncio and qasync alike), the child alive.
    server = tmp_path / "server.py"
    server.write_text(
        "from mcp.server.mcpserver import MCPServer\n"
        "app = MCPServer('t')\n"
        "@app.tool()\n"
        "def ping() -> str:\n"
        "    return 'pong'\n"
        "app.run('stdio')\n"
    )
    manager = MCPManager(
        [{"name": "t", "transport": "stdio", "command": sys.executable, "args": str(server)}]
    )
    await manager.connect_all()
    assert [t["name"] for t in manager.get_tools()] == ["ping"]

    await asyncio.wait_for(manager.close_all(), timeout=5)

    assert manager._tasks == []
