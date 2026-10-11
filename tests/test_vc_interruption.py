"""Voice-channel barge-in: off, any speech, or words only.

"Words only" is roomkit's SEMANTIC strategy with its phrase detector: an
acknowledgement ("ok", "d'accord", "merci") lets the assistant go on, other
words stop it. These run the policy build_interruption() hands the channel
through roomkit's own InterruptionHandler — the object the VoiceChannel asks
when the user speaks over the assistant.
"""

import pytest
import shiboken6
from roomkit.voice.interruption import InterruptionHandler, InterruptionStrategy

from roomkit_ui.engine_vc_helpers import build_interruption
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.ai_page import _AIPage


def _handler(mode: str, *, stt_streams: bool) -> InterruptionHandler:
    return InterruptionHandler(
        build_interruption({"vc_interruption_mode": mode}, stt_streams=stt_streams)
    )


def _judge(handler: InterruptionHandler, words: str, *, duration_ms: int = 900, streams=True):
    return handler.evaluate(
        playback_position_ms=2000,
        speech_duration_ms=duration_ms,
        speech_text=words,
        transcript_expected=streams,
    )


@pytest.mark.parametrize(
    ("mode", "strategy"),
    [
        ("off", InterruptionStrategy.DISABLED),
        ("", InterruptionStrategy.DISABLED),
        ("immediate", InterruptionStrategy.IMMEDIATE),
        ("semantic", InterruptionStrategy.SEMANTIC),
    ],
)
def test_each_mode_maps_to_its_strategy(mode, strategy):
    config = build_interruption({"vc_interruption_mode": mode}, stt_streams=True)

    assert config.strategy == strategy


def test_no_setting_means_off_never_a_roomkit_default():
    assert build_interruption({}, stt_streams=True).strategy == InterruptionStrategy.DISABLED


@pytest.mark.parametrize("words", ["d'accord", "Ok, merci.", "mm-hmm", "yeah, right"])
def test_an_acknowledgement_lets_the_assistant_go_on(words):
    decision = _judge(_handler("semantic", stt_streams=True), words)

    assert not decision.should_interrupt
    assert decision.is_backchannel


@pytest.mark.parametrize("words", ["attends, une question", "ok, and what about Calgary?"])
def test_other_words_stop_it(words):
    assert _judge(_handler("semantic", stt_streams=True), words).should_interrupt


def test_with_a_streaming_stt_sound_without_words_never_cuts_in():
    handler = _handler("semantic", stt_streams=True)

    # Before the wait for words is over, nothing is decided yet...
    early = _judge(handler, "", duration_ms=800)
    assert early.awaiting_transcript and not early.should_interrupt
    # ...and once it is, a wordless sound (echo, a cough) is let through.
    late = _judge(handler, "", duration_ms=2500)
    assert not late.should_interrupt


def test_without_a_streaming_stt_lasting_speech_still_cuts_in():
    """A Whisper-type STT has no words until the speech ends: "words only"
    would leave nothing able to stop the assistant."""
    handler = _handler("semantic", stt_streams=False)

    assert not _judge(handler, "", duration_ms=100, streams=False).should_interrupt
    assert _judge(handler, "", duration_ms=400, streams=False).should_interrupt


def test_immediate_cuts_at_the_first_sound():
    assert _judge(_handler("immediate", stt_streams=False), "", duration_ms=0).should_interrupt


def test_off_queues_the_speech_for_after_the_reply():
    decision = _judge(_handler("off", stt_streams=True), "stop")

    assert not decision.should_interrupt
    assert decision.queue_speech


# -- settings page ---------------------------------------------------------------


@pytest.fixture
def ai_page(qapp):
    pages: list[_AIPage] = []

    def _build(**overrides) -> _AIPage:
        pages.append(_AIPage({**_DEFAULTS, **overrides}))
        return pages[-1]

    yield _build
    for page in pages:
        shiboken6.delete(page)


@pytest.mark.parametrize("mode", ["off", "immediate", "semantic"])
def test_the_page_keeps_the_saved_mode(ai_page, mode):
    assert ai_page(vc_interruption_mode=mode).get_settings()["vc_interruption_mode"] == mode


def test_an_unknown_saved_mode_shows_as_off(ai_page):
    assert ai_page(vc_interruption_mode="bogus").get_settings()["vc_interruption_mode"] == "off"
