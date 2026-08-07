"""Realtime partials reach the chat — the trigger VC had and realtime lacked.

Partial transcriptions travel ON_PARTIAL_TRANSCRIPTION, a separate
trigger; register_realtime_hooks never listened to it because no realtime
provider emitted partials — until the providers started streaming deltas
(xAI input, Deepgram sentence-by-sentence).  Without the hook the chat
showed nothing while the agent spoke and the whole reply appeared late.
"""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_realtime_hooks


class _FakeKit:
    def __init__(self):
        self.hooks = {}

    def hook(self, trigger, execution):
        def register(fn):
            self.hooks[str(trigger)] = fn
            return fn

        return register


class _FakeEngine(QObject):
    transcription = Signal(str, str, bool, str)
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    mic_audio_level = Signal(float)

    def __init__(self):
        super().__init__()
        self._state = EngineState.ACTIVE
        self._mic_muted = False
        self._current_speaker_id = ""
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        self._partial_buffers = {}
        self._partial_speakers = {}
        self._spk_rms_queue = []
        self.emitted = []
        self.transcription.connect(
            lambda text, role, final, spk: self.emitted.append((text, role, final))
        )


def _hooks(engine):
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    partial = next(k for k in kit.hooks if "partial" in k.lower())
    final = next(
        k for k in kit.hooks if "transcription" in k.lower() and "partial" not in k.lower()
    )
    return kit.hooks[partial], kit.hooks[final]


def _event(text, role):
    return SimpleNamespace(text=text, role=role, is_final=False)


async def test_assistant_deltas_stream_into_the_chat(qapp):
    """The Deepgram shape: the reply arrives as sentence deltas."""
    engine = _FakeEngine()
    partial, final = _hooks(engine)

    await partial(_event("Salut!", "assistant"), None)
    await partial(_event(" Je suis là.", "assistant"), None)
    assert engine.emitted == [
        ("Salut!", "assistant", False),
        ("Salut! Je suis là.", "assistant", False),
    ]

    await final(SimpleNamespace(text="Salut! Je suis là.", role="assistant", is_final=True), None)
    assert engine.emitted[-1] == ("Salut! Je suis là.", "assistant", True)
    assert "assistant" not in engine._partial_buffers  # buffer cleared by the final


async def test_user_partials_carry_the_sticky_speaker(qapp):
    engine = _FakeEngine()
    engine._current_speaker_id = "sylvain"
    partial, _ = _hooks(engine)

    await partial(_event("Bonjour", "user"), None)
    assert engine.emitted == [("Bonjour", "user", False)]
    assert engine._partial_speakers["user"] == "sylvain"


async def test_partials_are_dropped_outside_active_sessions(qapp):
    engine = _FakeEngine()
    engine._state = EngineState.CONNECTING
    partial, _ = _hooks(engine)

    await partial(_event("early", "assistant"), None)
    assert engine.emitted == []
