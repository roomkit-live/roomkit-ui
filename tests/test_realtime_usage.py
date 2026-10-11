"""Realtime sessions report token usage to the info bar, without a cost."""

import pytest
from roomkit import RealtimeVoiceChannel, RoomKit
from roomkit.voice.realtime.mock import MockRealtimeProvider, MockRealtimeTransport

from roomkit_ui.engine import Engine
from roomkit_ui.engine_state import EngineState


@pytest.fixture
def engine(qapp):
    eng = Engine()
    eng._state = EngineState.ACTIVE
    payloads: list[dict] = []
    eng.session_cost.connect(payloads.append)
    eng.payloads = payloads
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


async def test_mock_provider_reports_reach_the_session_totals(engine):
    provider = MockRealtimeProvider()
    engine._register_callbacks(provider, transport=None)
    channel = RealtimeVoiceChannel("voice", provider=provider, transport=MockRealtimeTransport())
    kit = RoomKit()
    kit.register_channel(channel)
    room = await kit.create_room()
    await kit.attach_channel(room.id, channel.channel_id)
    session = await channel.start_session(room.id, "caller", object())
    try:
        await provider.simulate_usage(session, 1200, 40, details={"cached_tokens": 900})
        await provider.simulate_usage(session, 1500, 60)
    finally:
        await kit.close()

    assert engine.payloads[-1] == {"cost_usd": None, "input_tokens": 2700, "output_tokens": 100}


def _gpt_live_backend(input_tokens: int, output_tokens: int) -> dict:
    return {
        "model": "gpt-5.6-terra",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
    }


def test_gpt_live_backend_tokens_count_once_though_the_seconds_repeat_them(engine):
    on_usage = engine._realtime_usage_handler()
    first = _gpt_live_backend(300, 20)

    on_usage(None, {"backend": first})
    on_usage(None, {"backend": dict(first), "live_seconds": 4.2})  # seconds tick
    on_usage(None, {"live_seconds": 6.0})  # turn ended, map cleared
    on_usage(None, {"backend": _gpt_live_backend(500, 30), "live_seconds": 6.0})

    assert engine.payloads[-1] == {"cost_usd": None, "input_tokens": 800, "output_tokens": 50}
    assert len(engine.payloads) == 2  # seconds alone add no tokens: nothing to show


def test_a_report_after_the_session_ended_is_ignored(engine):
    on_usage = engine._realtime_usage_handler()
    engine._state = EngineState.IDLE

    on_usage(None, {"input_tokens": 10, "output_tokens": 5})

    assert engine.payloads == []


def test_garbage_counts_are_zero(engine):
    on_usage = engine._realtime_usage_handler()

    on_usage(None, {"input_tokens": "abc", "output_tokens": None})
    on_usage(None, {"input_tokens": "7", "output_tokens": 3})

    assert engine.payloads == [{"cost_usd": None, "input_tokens": 7, "output_tokens": 3}]
