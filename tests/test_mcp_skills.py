"""Skills an MCP server publishes (SEP-2640): read through the app's own sessions,
and a program run on one's behalf only once the user says yes."""

import asyncio
import hashlib
import json
import sys
from typing import Any

import shiboken6
from roomkit.skills import SkillExecutionRequest
from roomkit.skills.mcp import SKILLS_EXTENSION

from roomkit_ui.mcp_manager import MCPManager
from roomkit_ui.mcp_skills import SkillServer, add_served_skills, skill_label
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.skill_approval import SkillApproval, SkillApprovals
from roomkit_ui.toolset import ToolSet

BODY = "Say hello, then smile."
SKILL_MD = f"---\nname: greet\ndescription: Greets people warmly.\n---\n\n{BODY}\n"

# A real mcp 2.x server: it declares its extensions on the 2026 protocol only.
_SERVER = f"""
import hashlib

from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver import MCPServer
from mcp.types import RequestParams

SKILL_MD = {SKILL_MD!r}
URI = "skill://greet/SKILL.md"


class Skills(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def methods(self):
        async def list_skills(ctx, params):
            data = SKILL_MD.encode()
            resource = {{
                "uri": URI,
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }}
            frontmatter = {{"name": "greet", "description": "Greets people warmly."}}
            entry = {{"uri": URI, "frontmatter": frontmatter, "resources": [resource]}}
            return {{"skills": [entry]}}

        return [MethodBinding("skills/list", RequestParams, list_skills)]


app = MCPServer("t", extensions=[Skills()])


@app.resource(URI, mime_type="text/markdown")
def skill_md() -> str:
    return SKILL_MD


@app.tool()
def ping() -> str:
    return "pong"


app.run("stdio")
"""


def _config(tmp_path, *, skills: bool = True) -> dict:
    server = tmp_path / "server.py"
    server.write_text(_SERVER)
    return {
        "name": "Greeter Tools",
        "transport": "stdio",
        "command": sys.executable,
        "args": str(server),
        "skills": skills,
    }


async def test_a_server_publishing_skills_serves_them_verified(tmp_path):
    from mcp_types.version import MODERN_PROTOCOL_VERSIONS

    manager = MCPManager([_config(tmp_path)])
    await manager.connect_all()
    try:
        servers = manager.skill_servers()
        assert [(s.label, s.name) for s in servers] == [("greeter_tools", "Greeter Tools")]
        # Opened on the 2026 protocol: on the initialize handshake alone the
        # server left its extensions out, and no skill ever came.
        assert manager._skill_sessions[0][1].protocol_version in MODERN_PROTOCOL_VERSIONS
        notices: list[str] = []
        registry = await add_served_skills(
            None, servers, approve_execution=None, execution_tools=[], notice=notices.append
        )

        assert registry.skill_names == ["greeter_tools:greet"]
        skill = await registry.load_skill("greeter_tools:greet")  # read now, checked
        assert skill.instructions.strip() == BODY
        assert notices == []
    finally:
        await asyncio.wait_for(manager.close_all(), timeout=5)


async def test_a_server_whose_skills_are_off_still_brings_its_tools(tmp_path):
    manager = MCPManager([_config(tmp_path, skills=False)])
    await manager.connect_all()
    try:
        assert manager.skill_servers() == []
        assert [t["name"] for t in manager.get_tools()] == ["ping"]
    finally:
        await asyncio.wait_for(manager.close_all(), timeout=5)


def test_each_server_gets_its_own_label():
    manager = MCPManager([])
    manager._skill_sessions = [("Docs", object()), ("Docs", object()), ("", object())]

    assert [s.label for s in manager.skill_servers()] == ["docs", "docs_2", "mcp"]
    assert skill_label("Hugging Face", set()) == "hugging_face"


# -- what the chat says ------------------------------------------------------------------


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


class _Server:
    """A connected server declaring the extension, serving *entries*."""

    server_extensions = {SKILLS_EXTENSION: {}}

    def __init__(self, entries: list[dict] | None = None, error: Exception | None = None):
        self._entries = entries or []
        self._error = error

    async def request(self, method: str, params: Any = None) -> dict:
        if self._error is not None:
            raise self._error
        return {"skills": self._entries}

    async def read_resource(self, uri: str) -> dict:
        return {"contents": [{"uri": uri, "text": SKILL_MD}]}


def _entry(name: str = "greet", *, dynamic: bool = False) -> dict:
    uri = f"skill://{name}/SKILL.md"
    data = SKILL_MD.replace("greet", name)
    resources: Any = (
        "dynamic"
        if dynamic
        else [{"uri": uri, "digest": _digest(data), "size": len(data.encode())}]
    )
    frontmatter = {"name": name, "description": "Greets people warmly."}
    return {"uri": uri, "frontmatter": frontmatter, "resources": resources}


async def test_a_server_whose_listing_fails_is_said_and_the_others_kept():
    notices: list[str] = []
    registry = await add_served_skills(
        None,
        [
            SkillServer("broken", "Broken", _Server(error=RuntimeError("gone"))),
            SkillServer("greeter", "Greeter", _Server([_entry()])),
        ],
        approve_execution=None,
        execution_tools=[],
        notice=notices.append,
    )

    assert registry.skill_names == ["greeter:greet"]
    assert notices == ["Skills from Broken unavailable: they could not be listed."]


async def test_a_skill_roomkit_does_not_take_is_named_in_the_chat():
    notices: list[str] = []
    registry = await add_served_skills(
        None,
        [SkillServer("greeter", "Greeter", _Server([_entry(), _entry("live", dynamic=True)]))],
        approve_execution=None,
        execution_tools=[],
        notice=notices.append,
    )

    assert registry.skill_names == ["greeter:greet"]
    assert notices == ["Skills from Greeter not offered (see the log for why): greeter:live"]


async def test_no_skill_at_all_gives_no_registry():
    registry = await add_served_skills(
        None,
        [SkillServer("empty", "Empty", _Server([]))],
        approve_execution=None,
        execution_tools=[],
        notice=lambda _text: None,
    )

    assert registry is None


# -- the user's yes ------------------------------------------------------------------------

_REQUEST = SkillExecutionRequest(
    name="hf:hf-cli",
    label="hf",
    uri="skill://hf-cli/SKILL.md",
    fingerprint="abc",
    room_id="r1",
    tool="gh",
)


async def test_calls_waiting_together_ask_the_user_once():
    asked: list[SkillApproval] = []
    approvals = SkillApprovals(asked.append, lambda _text: None)
    approvals.set_servers({"hf": "Hugging Face"})

    first = asyncio.create_task(approvals.approve(_REQUEST))
    second = asyncio.create_task(approvals.approve(_REQUEST))
    await asyncio.sleep(0)
    assert [(a.skill, a.server, a.tool) for a in asked] == [("hf:hf-cli", "Hugging Face", "gh")]
    asked[0].answer(True)

    assert await first is True
    assert await second is True


async def test_no_answer_in_time_refuses_and_the_chat_says_so():
    asked: list[SkillApproval] = []
    notices: list[str] = []
    approvals = SkillApprovals(asked.append, notices.append, timeout=0.01)

    assert await approvals.approve(_REQUEST) is False
    assert asked[0].settled
    assert notices == ["No answer: “gh” did not run for hf:hf-cli."]


async def test_the_session_end_refuses_a_question_still_open():
    approvals = SkillApprovals(lambda _approval: None, lambda _text: None)
    waiting = asyncio.create_task(approvals.approve(_REQUEST))
    await asyncio.sleep(0)

    approvals.cancel_all()

    assert await waiting is False


# -- end to end: the engine's skills, a CLI tool, roomkit's gate --------------------------

_GH = {"name": "gh", "description": "GitHub CLI.", "parameters": {"type": "object"}}


async def _turn(engine: Any, answer: bool) -> list[str]:
    """One turn whose model activates the served skill, then calls the CLI
    tool gh; the user answers *answer*.  Returns the CLI calls that ran."""
    from roomkit import ChannelCategory, RoomKit, SMSChannel, TextContent
    from roomkit.channels.ai import AIChannel
    from roomkit.models.delivery import InboundMessage
    from roomkit.providers.ai.base import AIResponse, AIToolCall
    from roomkit.providers.ai.mock import MockAIProvider
    from roomkit.providers.sms.mock import MockSMSProvider

    toolset = ToolSet(builtin=[], cli=[_GH], mcp=[])
    registry = await engine._load_all_skills({**_DEFAULTS, "skill_sources": "[]"}, toolset)
    engine.skill_approval_requested.connect(lambda approval: approval.answer(answer))

    def call(tool: str, **arguments: Any) -> AIResponse:
        return AIResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=[AIToolCall(id=f"tc-{tool}", name=tool, arguments=arguments)],
        )

    script = [
        call("activate_skill", name="greeter:greet"),
        call("gh", args="repo list"),
        AIResponse(content="done", finish_reason="stop"),
    ]
    ran: list[str] = []

    async def handler(name: str, arguments: dict) -> str:
        ran.append(name)
        return json.dumps({"result": "ok"})

    kit = RoomKit()
    kit.register_channel(
        AIChannel(
            "ai",
            provider=MockAIProvider(ai_responses=script),
            tool_handler=handler,
            config_provider=toolset.turn_config(),
            skills=registry,
            **toolset.channel_options(),
        )
    )
    kit.register_channel(SMSChannel("sms", provider=MockSMSProvider()))
    await kit.create_room(room_id="r1")
    await kit.attach_channel("r1", "ai", category=ChannelCategory.INTELLIGENCE)
    await kit.attach_channel("r1", "sms")
    await kit.process_inbound(
        InboundMessage(channel_id="sms", sender_id="u", content=TextContent(body="hi"))
    )
    await kit.close()
    return ran


class _Manager:
    def skill_servers(self) -> list[SkillServer]:
        return [SkillServer("greeter", "Greeter", _Server([_entry()]))]


async def test_a_cli_tool_runs_for_a_served_skill_once_the_user_says_yes(qapp):
    from roomkit_ui.engine import Engine

    engine = Engine()
    engine._mcp = _Manager()

    assert await _turn(engine, True) == ["gh"]


async def test_a_cli_tool_the_user_refuses_does_not_run(qapp):
    from roomkit_ui.engine import Engine

    engine = Engine()
    engine._mcp = _Manager()

    assert await _turn(engine, False) == []


# -- the question on screen ----------------------------------------------------------------


def _approval() -> SkillApproval:
    future = asyncio.get_running_loop().create_future()
    return SkillApproval("hf:hf-cli", "Hugging Face", "gh", future)


async def test_the_question_names_the_skill_its_server_and_the_tool(qapp):
    from roomkit_ui.widgets.skill_approval_dialog import show_skill_approval

    approval = _approval()
    box = show_skill_approval(None, approval)
    try:
        assert "hf:hf-cli" in box.text() and "Hugging Face" in box.text() and "gh" in box.text()
        next(b for b in box.buttons() if b.text() == "Allow").click()
        assert approval.future.result() is True
    finally:
        if shiboken6.isValid(box):
            shiboken6.delete(box)


async def test_refuse_is_the_answer_to_escape(qapp):
    from roomkit_ui.widgets.skill_approval_dialog import show_skill_approval

    approval = _approval()
    box = show_skill_approval(None, approval)
    try:
        assert box.escapeButton().text() == "Refuse"
        box.escapeButton().click()
        assert approval.future.result() is False
    finally:
        if shiboken6.isValid(box):
            shiboken6.delete(box)


async def test_a_question_settled_elsewhere_closes_its_dialog(qapp):
    from roomkit_ui.widgets.skill_approval_dialog import show_skill_approval

    approval = _approval()
    box = show_skill_approval(None, approval)
    try:
        assert box.isVisible()
        approval.answer(False)  # no answer in time, or the session ended
        await asyncio.sleep(0)
        assert not shiboken6.isValid(box) or not box.isVisible()
    finally:
        if shiboken6.isValid(box):
            shiboken6.delete(box)


# -- settings ------------------------------------------------------------------------------


def test_a_server_uses_its_skills_unless_turned_off(qapp):
    from roomkit_ui.widgets.settings.mcp_page import _MCPPage

    page = _MCPPage({**_DEFAULTS, "mcp_servers": "[]"})
    try:
        page._add_server()
        page._name_edit.setText("Docs")
        assert page._skills_check.isChecked()
        page._skills_check.setChecked(False)

        saved = json.loads(page.get_settings()["mcp_servers"])
        assert saved[0]["skills"] is False
    finally:
        shiboken6.delete(page)
