"""Diarization is said to be voice-channel only, instead of failing silently.

Under roomkit 0.96.1 a realtime session cannot run it: RealtimeVoiceChannel
leaves the pipeline's speaker changes unheard (no handler, no
ON_SPEAKER_CHANGE), the 16 kHz pipeline the models need reached the provider
as if it were the 24 kHz transport audio, and gating dropped frames before
diarization could hear the primary speaker again.
"""

import asyncio

import pytest

from roomkit_ui.engine import Engine
from roomkit_ui.engine_realtime import REALTIME_DIARIZATION_NOTICE
from roomkit_ui.toolset import ToolSet

_SETTINGS = {
    "conversation_mode": "realtime",
    "provider": "gemini",
    "api_key": "test-key",
    "aec_mode": "webrtc",
    "diarization_enabled": True,
    "diarization_model": "speaker-model",
    "vc_vad_model": "ten-vad",
    "primary_speaker_mode": True,
}


@pytest.fixture
def engine(qapp, monkeypatch):
    eng = Engine()
    eng.notices = []
    eng.session_notice.connect(eng.notices.append)
    eng.tools_reached = asyncio.Event()

    async def tools(settings):
        eng.tools_reached.set()
        await asyncio.Event().wait()  # held here until stop() cancels the start
        return ToolSet(builtin=[], cli=[], mcp=[])

    monkeypatch.setattr(eng, "_setup_tools", tools)
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


async def test_a_realtime_session_says_diarization_is_off(engine):
    start = asyncio.create_task(engine.start(_SETTINGS))
    await asyncio.wait_for(engine.tools_reached.wait(), timeout=5)

    assert REALTIME_DIARIZATION_NOTICE in engine.notices
    assert engine._diarization is None
    assert engine._primary_speaker_mode is False
    await asyncio.wait_for(engine.stop(), timeout=5)
    await start


def test_the_realtime_pipeline_stays_at_the_provider_rate(engine):
    media = engine._build_realtime_media(_SETTINGS, "gemini", "webrtc")

    assert media.pipeline is not None  # the AEC stage
    assert media.pipeline.vad is None
    assert media.pipeline.diarization is None
    assert media.pipeline.contract is None  # no 16 kHz internal format
