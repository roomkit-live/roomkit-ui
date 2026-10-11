"""The no-MCP retry runs on fresh media, and only when the tools were refused.

A failed attempt's kit.close() closes the channel and with it the provider
and the transport (the transport's AEC too): the retry reused all three,
so a retried Deepgram session ran without its transport AEC. And any start
failure — a bad key, the network — triggered the retry: a transient failure
followed by success disabled MCP behind "incompatible with this provider".

These run roomkit's RealtimeVoiceChannel over its mock provider and
transport.
"""

import pytest
from roomkit.voice.realtime.mock import MockRealtimeProvider, MockRealtimeTransport

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.engine import Engine
from roomkit_ui.engine_realtime import _RealtimeMedia
from roomkit_ui.toolset import ToolSet

_MCP_TOOL = {
    "type": "function",
    "name": "mcp_lookup",
    "description": "Looks things up",
    "parameters": {"type": "object", "properties": {}},
}
_TOOLSET = ToolSet(builtin=[dict(BUILTIN_TOOLS[0])], cli=[], mcp=[_MCP_TOOL])


class _GeminiSetupError(Exception):
    """What google-genai raises when Live closes the setup: an APIError with a code."""

    code = 1007


class _Provider(MockRealtimeProvider):
    """Refuses a session per *refuse(tools)*, which returns the error or None."""

    def __init__(self, refuse):
        super().__init__()
        self._refuse = refuse
        self.closed = False

    async def connect(self, session, *, tools=None, **kwargs):
        error = self._refuse([t["name"] for t in tools or []])
        if error is not None:
            raise error
        await super().connect(session, tools=tools, **kwargs)

    async def close(self):
        self.closed = True
        await super().close()


@pytest.fixture
def engine(qapp):
    eng = Engine()
    eng.notices = []
    eng.mcp_status.connect(eng.notices.append)
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


def _builder(refuse):
    built: list[_RealtimeMedia] = []

    def build():
        media = _RealtimeMedia(
            provider=_Provider(refuse),
            voice="Aoede",
            model="mock",
            transport=MockRealtimeTransport(),
            pipeline=None,
            aec=None,
            sample_rate=24000,
        )
        built.append(media)
        return media

    return build, built


async def _open(engine, build):
    return await engine._open_realtime_session(
        build(),
        build,
        "You are helpful.",
        _TOOLSET,
        settings={"conversation_memory": False},
        provider_config=None,
        skills=None,
    )


async def test_a_refused_mcp_schema_retries_on_a_fresh_provider_and_transport(engine):
    def refuse(names):
        return _GeminiSetupError("1007 Invalid argument") if "mcp_lookup" in names else None

    build, built = _builder(refuse)

    media, tools = await _open(engine, build)

    assert len(built) == 2
    first, retry = built
    assert first.provider.closed  # closed with the failed attempt's kit
    assert media is retry and not retry.provider.closed
    assert retry.transport is not first.transport
    assert [t["name"] for t in tools] == [BUILTIN_TOOLS[0]["name"]]
    assert engine.notices and "1007" in engine.notices[-1]
    await engine._cleanup()


async def test_a_failure_that_is_not_a_refusal_keeps_mcp_and_says_what_failed(engine):
    build, built = _builder(lambda names: ConnectionError("network unreachable"))

    with pytest.raises(ConnectionError, match="network unreachable"):
        await _open(engine, build)

    assert len(built) == 1  # no retry: shedding MCP cannot cure the network
    assert engine.notices == []


async def test_when_the_retry_fails_too_the_first_error_is_raised(engine):
    calls: list[list[str]] = []

    def refuse(names):
        calls.append(names)
        if "mcp_lookup" in names:
            return _GeminiSetupError("1007 Invalid argument: function_declarations")
        return RuntimeError("quota exceeded")

    build, _ = _builder(refuse)

    with pytest.raises(_GeminiSetupError, match="function_declarations"):
        await _open(engine, build)

    assert len(calls) == 2
    assert engine.notices == []


def test_each_attempt_builds_its_own_provider_transport_and_aec(engine):
    settings = {"provider": "deepgram", "deepgram_api_key": "key", "aec_mode": "webrtc"}

    first = engine._build_realtime_media(settings, "deepgram", "webrtc", None, None)
    retry = engine._build_realtime_media(settings, "deepgram", "webrtc", None, None)

    assert retry.provider is not first.provider
    assert retry.transport is not first.transport
    assert retry.aec is not None and retry.aec is not first.aec  # Deepgram's transport AEC
    assert engine._transport is retry.transport
