"""Each utterance names its own speaker, so primary-speaker mode holds.

Since roomkit 0.93 a voice the diarization stage matches to nobody fires no
ON_SPEAKER_CHANGE. The hooks kept the last identified speaker as the
utterance's: after the primary spoke, a voice nobody enrolled inherited the
primary's name, and primary-speaker mode let the assistant answer it.

The channel now runs with ``pipeline_speakers``: each transcription carries
the voice heard the longest over its own utterance. These run the engine's
own VoiceChannel construction on roomkit's mocks, diarization scripted.
"""

from roomkit.voice.pipeline.aec.mock import MockAECProvider
from roomkit.voice.pipeline.diarization.base import DiarizationResult
from roomkit.voice.pipeline.diarization.mock import MockDiarizationProvider
from roomkit.voice.tts.mock import MockTTSProvider
from vc_harness import FakeEngine, TokenAI, open_session, until, utterance

from roomkit_ui.engine_vc import _build_voice_channel


def _heard(*speakers: str) -> MockDiarizationProvider:
    """One verdict per utterance, on its closing frame (sherpa-onnx's moment)."""
    results: list[DiarizationResult | None] = []
    for speaker in speakers:
        results += [None, None, DiarizationResult(speaker, 1.0, is_new_speaker=False)]
    return MockDiarizationProvider(results=results)


async def _conversation(*speakers: str, primary: str = "") -> tuple[FakeEngine, TokenAI]:
    """The utterances of *speakers* in turn: the chat as the user saw it, and the LLM."""
    engine = FakeEngine()
    engine._primary_speaker_mode = bool(primary)
    engine._primary_speaker_name = primary
    vc = await open_session(
        tts=MockTTSProvider(),
        reply=["Sure."],
        transcripts=[f"utterance {i}" for i in range(len(speakers))],
        vad_events=utterance() * len(speakers),
        # An AEC ends each playback at once: no 2 s echo drain between turns.
        pipeline={"diarization": _heard(*speakers), "aec": MockAECProvider()},
        build_channel=_build_voice_channel,
        engine=engine,
    )
    try:
        for i in range(len(speakers)):
            await vc.speak()
            await until(lambda n=i + 1: len(_said(engine)) == n)
            # An utterance let through is answered before the next one comes.
            answered = sum(role == "user" for _, role, _ in _said(engine))
            await until(lambda n=answered: len(engine.finals("assistant")) == n)
    finally:
        await vc.kit.close()
    return engine, vc.ai


def _said(engine: FakeEngine) -> list[tuple[str, str, str]]:
    """(text, role, speaker) of each final user-side bubble."""
    return [
        (text, role, spk)
        for text, role, final, spk in engine.chat
        if final and role != "assistant"
    ]


async def test_an_unknown_voice_after_the_primary_is_not_answered():
    engine, ai = await _conversation("Alice", "unknown", primary="Alice")

    assert _said(engine) == [
        ("utterance 0", "user", "Alice"),
        ("utterance 1", "other", "Unknown"),  # the primary's name stuck to it before
    ]
    assert len(ai.contexts) == 1


async def test_another_enrolled_voice_is_shown_but_not_answered():
    engine, ai = await _conversation("Bob", "Alice", primary="Alice")

    assert _said(engine) == [("utterance 0", "other", "Bob"), ("utterance 1", "user", "Alice")]
    assert len(ai.contexts) == 1


async def test_without_primary_mode_every_voice_is_answered_under_its_name():
    engine, ai = await _conversation("Alice", "unknown", "Bob")

    assert _said(engine) == [
        ("utterance 0", "user", "Alice"),
        ("utterance 1", "user", "Unknown"),
        ("utterance 2", "user", "Bob"),
    ]
    assert len(ai.contexts) == 3
    # Several people spoke: the model reads who said what, by enrolled name.
    turns = [str(m.content) for m in ai.contexts[-1].messages if m.role == "user"]
    assert any("Alice" in t and "utterance 0" in t for t in turns), turns
    assert any("Unknown speaker" in t and "utterance 1" in t for t in turns), turns
    assert any("Bob" in t and "utterance 2" in t and "Speaker Bob" not in t for t in turns), turns


async def test_without_diarization_nobody_is_named():
    engine = FakeEngine()
    vc = await open_session(
        tts=MockTTSProvider(), reply=["Sure."], engine=engine, build_channel=_build_voice_channel
    )
    try:
        await vc.speak()
        await until(lambda: engine.finals("assistant"))
    finally:
        await vc.kit.close()

    assert engine.finals("user") == [("Hello", "")]
