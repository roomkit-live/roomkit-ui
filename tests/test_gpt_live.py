"""OpenAI GPT-Live: built like roomkit's example, tools served by the hosted backend."""

import importlib.util
import re
from pathlib import Path

import pytest
from roomkit import RealtimeVoiceChannel, RoomKit
from roomkit.providers.openai.live import HostedReasoning, OpenAILiveProvider
from roomkit.voice.realtime.mock import MockRealtimeTransport

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.realtime_providers import (
    build_realtime_provider,
    realtime_sample_rate,
    transport_audio_profile,
)
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.toolset import ToolSet
from roomkit_ui.widgets.settings.realtime_section import PROVIDERS, RealtimeSection

ROOT = Path(__file__).resolve().parent.parent

# -- provider -----------------------------------------------------------------


def test_gpt_live_needs_the_openai_key():
    with pytest.raises(ValueError, match="OpenAI API key"):
        build_realtime_provider("openai_live", {})


def test_gpt_live_defaults_mirror_roomkits_example():
    provider, voice, model = build_realtime_provider("openai_live", {"openai_api_key": "k"})

    assert isinstance(provider, OpenAILiveProvider)
    assert provider.full_duplex
    assert (model, voice) == ("gpt-live-1", "marin")
    backend = provider.delegation
    assert isinstance(backend, HostedReasoning)
    assert (backend.model, backend.reasoning_effort) == ("gpt-5.6-terra", "low")
    assert "live voice conversation" in backend.instructions


def test_gpt_live_settings_reach_the_provider():
    provider, voice, _ = build_realtime_provider(
        "openai_live",
        {
            "openai_api_key": "k",
            "openai_live_voice": "cedar",
            "openai_live_backend_model": "gpt-5.5",
            "openai_live_backend_effort": "high",
        },
    )

    assert voice == "cedar"
    assert provider.delegation.model == "gpt-5.5"
    assert provider.delegation.reasoning_effort == "high"


# -- audio: roomkit's examples/realtime_voice_local_openai_live.py --------------------


def test_gpt_live_runs_the_aec_at_transport_level_with_webrtc_ns():
    aec = object()
    transport_aec, denoiser, prebuffer = transport_audio_profile("openai_live", aec, 24000)

    assert transport_aec is aec
    assert type(denoiser).__name__ == "WebRTCNoiseSuppressorProvider"
    assert prebuffer == 120  # LocalAudioBackend's default, which the example keeps
    assert realtime_sample_rate("openai_live") == 24000


def test_gpt_live_without_an_aec_keeps_the_noise_suppressor():
    transport_aec, denoiser, prebuffer = transport_audio_profile("openai_live", None, 24000)

    assert transport_aec is None  # the mic is muted during playback instead
    assert denoiser is not None
    assert prebuffer == 120


# -- tools: the channel's options with a full-duplex, hosted-backend provider ----------


class _CapturingLive(OpenAILiveProvider):
    """Records what the channel hands to connect(), without opening a socket."""

    async def connect(self, session, **kwargs):
        self.connected_with = kwargs
        session.state = "active"


def _mcp_tools(count: int) -> list[dict]:
    return [
        {"name": f"mcp_{i}", "description": "x", "parameters": {"type": "object"}}
        for i in range(count)
    ]


async def _declared(mcp_count: int) -> tuple[list[str], _CapturingLive, RealtimeVoiceChannel]:
    toolset = ToolSet(builtin=list(BUILTIN_TOOLS), cli=[], mcp=_mcp_tools(mcp_count))
    provider = _CapturingLive(api_key="k", delegation=HostedReasoning(model="gpt-5.6-terra"))
    channel = RealtimeVoiceChannel(
        "voice",
        provider=provider,
        transport=MockRealtimeTransport(),
        tools=toolset.all,
        tool_handler=lambda *args: None,
        input_sample_rate=24000,
        output_sample_rate=24000,
        **toolset.channel_options(),
    )
    kit = RoomKit()
    kit.register_channel(channel)
    room = await kit.create_room()
    await kit.attach_channel(room.id, "voice")
    try:
        await channel.start_session(room.id, "local-user", None)
    finally:
        await kit.close()
    names = [t["name"] for t in provider.connected_with["tools"]]
    return names, provider, channel


async def test_a_small_catalogue_reaches_the_backend_whole_and_unbounded():
    names, provider, channel = await _declared(3)

    assert names == [t["name"] for t in BUILTIN_TOOLS] + ["mcp_0", "mcp_1", "mcp_2"]
    backend = provider.delegation.to_config(provider.connected_with["tools"])
    assert len(backend["responses"]["tools"]) == len(names)
    assert channel._tool_timeouts.default is None  # the app's own MCP/CLI bounds hold


async def test_a_large_catalogue_goes_behind_tool_search_with_the_builtins_pinned():
    names, _, _ = await _declared(30)

    # GPT-Live declares once (no mid-session reconfigure): Tool Search runs
    # through list_tools/call_tool, and the pinned built-ins stay declared.
    assert {"find_tools", "list_tools", "call_tool"} <= set(names)
    assert {t["name"] for t in BUILTIN_TOOLS} <= set(names)
    assert not any(name.startswith("mcp_") for name in names)


# -- settings ------------------------------------------------------------------------


@pytest.fixture
def section(qapp):
    sections: list[RealtimeSection] = []

    def _build(**overrides) -> RealtimeSection:
        sections.append(RealtimeSection({**_DEFAULTS, **overrides}))
        return sections[-1]

    yield _build
    for s in sections:
        s.deleteLater()


def test_gpt_live_is_offered_and_shares_the_openai_key(section):
    page = section(provider="openai_live")

    assert ("OpenAI GPT-Live (full-duplex)", "openai_live") in PROVIDERS
    assert not page.openai_api_key.isHidden()
    assert not page._gpt_live.voice.isHidden()
    assert page.openai_voice.isHidden()  # OpenAI Realtime's own rows


def test_the_openai_realtime_rows_hide_gpt_live(section):
    page = section(provider="openai")

    assert not page.openai_api_key.isHidden()
    assert page._gpt_live.voice.isHidden()


def test_gpt_live_combos_come_from_its_catalogs_and_round_trip(section):
    page = section(provider="openai_live", openai_live_voice="cedar")
    fields = page._gpt_live
    voices = [fields.voice.itemData(i) for i in range(fields.voice.count())]

    assert "marin" in voices and "bossa" in voices  # GPT-Live's voices, not Realtime's
    assert fields.model.findText("gpt-live-1") >= 0
    out = page.get_settings()
    assert out["provider"] == "openai_live"
    assert out["openai_live_voice"] == "cedar"
    assert out["openai_live_model"] == "gpt-live-1"
    assert out["openai_live_backend_model"] == "gpt-5.6-terra"
    assert out["openai_live_backend_effort"] == "low"


# -- frozen builds -------------------------------------------------------------------


def test_the_builds_bundle_tiktokens_encoding_plugin():
    # tiktoken finds its encodings by scanning the tiktoken_ext namespace
    # package, which PyInstaller cannot follow.
    assert importlib.util.find_spec("tiktoken_ext.openai_public") is not None
    script = (ROOT / "scripts" / "build_app.sh").read_text()
    assert re.search(r"--hidden-import=tiktoken_ext\.openai_public\b", script)
