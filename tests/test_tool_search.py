"""Tool Search: when the model finds its tools with find_tools, set in Settings."""

import pytest
import shiboken6
from roomkit.providers.ai.base import AITool
from vc_harness import StreamingInputTTS, open_session, until

from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.toolset import (
    DEFAULT_TOOL_SEARCH_THRESHOLD,
    DEFAULT_TOOL_SEARCH_TOKENS,
    DEFAULT_TOOL_SEARCH_WINDOW_PCT,
    tool_search_options,
)
from roomkit_ui.widgets.settings.integrations_page import IntegrationsPage

_TOOLS = [
    AITool(
        name=f"tool_{i}",
        description=f"Does thing number {i} for the user.",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    for i in range(6)
]


def test_the_defaults_are_roomkits():
    from roomkit.channels import _tool_search_constants as roomkit

    assert DEFAULT_TOOL_SEARCH_THRESHOLD == roomkit.DEFAULT_TOOL_SEARCH_THRESHOLD
    assert DEFAULT_TOOL_SEARCH_TOKENS == roomkit.DEFAULT_TOOL_SEARCH_THRESHOLD_TOKENS
    assert DEFAULT_TOOL_SEARCH_WINDOW_PCT == roomkit.DEFAULT_TOOL_SEARCH_THRESHOLD_PCT
    assert tool_search_options(_DEFAULTS, realtime=False) == {
        "tool_search": None,
        "tool_search_threshold": 20,
        "tool_search_threshold_tokens": 8000,
        "tool_search_threshold_pct": 10.0,
    }


@pytest.mark.parametrize(("mode", "forced"), [("auto", None), ("on", True), ("off", False)])
def test_the_mode_forces_it_or_leaves_roomkit_to_decide(mode, forced):
    assert tool_search_options({"tool_search_mode": mode}, realtime=True)["tool_search"] is forced


@pytest.mark.parametrize(("mode", "forced"), [("auto", False), ("on", True), ("off", False)])
def test_automatic_leaves_a_local_model_every_tool(mode, forced):
    options = tool_search_options({"tool_search_mode": mode}, realtime=False, local_model=True)

    assert options["tool_search"] is forced


def test_a_realtime_channel_gets_the_tool_count_only():
    options = tool_search_options({"tool_search_threshold": "12"}, realtime=True)

    assert options == {"tool_search": None, "tool_search_threshold": 12}


@pytest.mark.parametrize("bad", ["", "many", 0, -3, None])
def test_a_value_that_is_no_positive_number_falls_back_to_roomkits(bad):
    options = tool_search_options(
        {
            "tool_search_mode": "sometimes",
            "tool_search_threshold": bad,
            "tool_search_threshold_tokens": bad,
            "tool_search_window_pct": bad,
        },
        realtime=False,
    )

    assert options == tool_search_options({}, realtime=False)


def test_the_window_share_is_at_most_all_of_it():
    options = tool_search_options({"tool_search_window_pct": 250}, realtime=False)

    assert options["tool_search_threshold_pct"] == 100.0


def test_both_channels_take_their_options():
    from roomkit import RealtimeVoiceChannel
    from roomkit.channels.ai import AIChannel
    from roomkit.providers.ai.mock import MockAIProvider
    from roomkit.voice.backends.mock import MockVoiceBackend
    from roomkit.voice.realtime.mock import MockRealtimeProvider

    settings = {"tool_search_mode": "on", "tool_search_threshold": 8}
    RealtimeVoiceChannel(
        "voice",
        provider=MockRealtimeProvider(),
        transport=MockVoiceBackend(),
        **tool_search_options(settings, realtime=True),
    )
    AIChannel(
        "ai",
        provider=MockAIProvider(responses=["ok"]),
        **tool_search_options(settings, realtime=False),
    )


async def _tools_the_model_sees(settings: dict, *, local_model: bool = False) -> set[str]:
    options = tool_search_options(settings, realtime=False, local_model=local_model)
    vc = await open_session(
        tts=StreamingInputTTS(),
        reply=["Hi!"],
        ai_options={"tools": _TOOLS, **options},
    )
    try:
        await vc.speak()
        await until(lambda: vc.ai.contexts)
        return {tool.name for tool in vc.ai.contexts[0].tools}
    finally:
        await vc.kit.close()


async def test_never_puts_every_tool_in_the_prompt(qapp):
    seen = await _tools_the_model_sees({"tool_search_mode": "off"})

    # Beside roomkit's own (read_stored_result reads back an evicted result).
    assert {tool.name for tool in _TOOLS} <= seen
    assert "find_tools" not in seen


async def test_a_small_budget_hides_the_tools_behind_find_tools(qapp):
    seen = await _tools_the_model_sees({"tool_search_threshold_tokens": 50})

    assert "find_tools" in seen
    assert not seen & {tool.name for tool in _TOOLS}


async def test_a_local_model_sees_every_tool_past_the_thresholds(qapp):
    seen = await _tools_the_model_sees({"tool_search_threshold_tokens": 50}, local_model=True)

    assert {tool.name for tool in _TOOLS} <= seen
    assert "find_tools" not in seen


async def test_below_the_thresholds_the_tools_stay_in_the_prompt(qapp):
    seen = await _tools_the_model_sees({})

    assert {tool.name for tool in _TOOLS} <= seen
    assert "find_tools" not in seen


# -- settings ----------------------------------------------------------------------------


def test_the_section_saves_what_the_engine_reads(qapp):
    page = IntegrationsPage(
        {
            **_DEFAULTS,
            "tool_search_mode": "on",
            "tool_search_threshold": 12,
            "tool_search_threshold_tokens": 4000,
            "tool_search_window_pct": 5,
        }
    )
    try:
        out = page.get_settings()
        assert out["tool_search_mode"] == "on"
        assert out["tool_search_threshold"] == 12
        assert out["tool_search_threshold_tokens"] == 4000
        assert out["tool_search_window_pct"] == 5
    finally:
        shiboken6.delete(page)


@pytest.mark.parametrize(
    ("mode", "count", "budget"),
    [("auto", True, True), ("on", True, False), ("off", False, False)],
)
def test_only_the_thresholds_a_mode_uses_are_editable(qapp, mode, count, budget):
    page = IntegrationsPage({**_DEFAULTS, "tool_search_mode": mode})
    try:
        section = page.tool_search
        # Forced on, the count still caps how many tools a realtime model sees.
        assert section.threshold.isEnabled() is count
        assert section.tokens.isEnabled() is budget
        assert section.window_pct.isEnabled() is budget
    finally:
        shiboken6.delete(page)


# -- the engine hands them to roomkit ---------------------------------------------------


@pytest.mark.parametrize(("mode", "searches"), [("on", True), ("off", False)])
async def test_a_realtime_session_runs_the_chosen_mode(qapp, mode, searches):
    from roomkit.voice.realtime.mock import MockRealtimeProvider, MockRealtimeTransport

    from roomkit_ui.builtin_tools import BUILTIN_TOOLS
    from roomkit_ui.engine import Engine
    from roomkit_ui.engine_realtime import _RealtimeMedia
    from roomkit_ui.toolset import ToolSet

    def build():
        return _RealtimeMedia(
            provider=MockRealtimeProvider(),
            voice="Aoede",
            model="mock",
            transport=MockRealtimeTransport(),
            pipeline=None,
            aec=None,
            sample_rate=24000,
        )

    engine = Engine()
    try:
        await engine._open_realtime_session(
            build(),
            build,
            "You are helpful.",
            ToolSet(builtin=[dict(tool) for tool in BUILTIN_TOOLS], cli=[], mcp=[]),
            settings={"conversation_memory": False, "tool_search_mode": mode},
            provider_config=None,
            skills=None,
        )

        assert (engine._channel._tool_search_support is not None) is searches
    finally:
        await engine._cleanup()


async def test_a_voice_channel_session_runs_the_chosen_thresholds(qapp, monkeypatch):
    from roomkit.providers.ai.mock import MockAIProvider

    from roomkit_ui.engine import Engine
    from roomkit_ui.toolset import ToolSet

    engine = Engine()

    async def no_tools(_settings, _provider):
        return ToolSet(builtin=[], cli=[], mcp=[]), None

    monkeypatch.setattr(engine, "_load_vc_tools", no_tools)
    channel, _, _ = await engine._build_vc_ai_channel(
        {**_DEFAULTS, "tool_search_mode": "off", "tool_search_threshold_tokens": 3000},
        MockAIProvider(responses=["ok"]),
        "anthropic",
        "Be brief.",
    )

    assert channel._tool_search is False
    assert channel._tool_search_threshold_tokens == 3000
    assert channel._tool_search_threshold_pct == 10.0


@pytest.mark.parametrize(
    ("llm", "searches"), [("anthropic", None), ("local", False), ("llamacpp", False)]
)
async def test_a_voice_channel_on_a_local_model_does_not_search(qapp, monkeypatch, llm, searches):
    from roomkit.providers.ai.mock import MockAIProvider

    from roomkit_ui.engine import Engine
    from roomkit_ui.toolset import ToolSet

    engine = Engine()

    async def no_tools(_settings, _provider):
        return ToolSet(builtin=[], cli=[], mcp=[]), None

    monkeypatch.setattr(engine, "_load_vc_tools", no_tools)
    channel, _, _ = await engine._build_vc_ai_channel(
        dict(_DEFAULTS), MockAIProvider(responses=["ok"]), llm, "Be brief."
    )

    assert channel._tool_search is searches
