"""ON_SPEAKER_CHANGE reaches the float signal even when the change has no score.

Since roomkit 0.92 a diarizing STT labels transcripts itself, and its
SpeakerChangeEvent carries ``confidence=None``. Emitted as-is on
``Signal(str, float)``, PySide prints "Cannot copy-convert NoneType" on every
speaker change.
"""

from types import SimpleNamespace

from roomkit.voice.base import VoiceSession
from roomkit.voice.events import SpeakerChangeEvent

from roomkit_ui.hooks import register_vc_hooks


class _FakeKit:
    def __init__(self):
        self.hooks = {}

    def hook(self, trigger, execution):
        def register(fn):
            self.hooks[str(trigger).lower()] = fn
            return fn

        return register

    def on(self, name):
        return lambda fn: fn


def _engine(sent):
    signal = SimpleNamespace(emit=lambda *args: sent.append(args))
    return SimpleNamespace(speaker_identified=signal)


def _speaker_hook(engine):
    kit = _FakeKit()
    register_vc_hooks(kit, engine)
    return next(fn for key, fn in kit.hooks.items() if key.endswith("on_speaker_change"))


def _event(speaker_id, confidence, **kwargs):
    session = VoiceSession(id="s1", room_id="main", participant_id="u", channel_id="voice")
    return SpeakerChangeEvent(
        session=session,
        speaker_id=speaker_id,
        confidence=confidence,
        is_new_speaker=False,
        **kwargs,
    )


async def test_a_change_without_a_score_emits_zero_confidence():
    sent: list[tuple] = []
    engine = _engine(sent)

    await _speaker_hook(engine)(_event("Alice", None, source="stt"), None)

    assert sent == [("Alice", 0.0)]


async def test_a_scored_change_keeps_its_confidence():
    sent: list[tuple] = []

    await _speaker_hook(_engine(sent))(_event("Bob", 0.82), None)

    assert sent == [("Bob", 0.82)]
