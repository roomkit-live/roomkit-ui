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
    reply_interrupted = Signal(int)
    mic_audio_level = Signal(float)

    def __init__(self):
        super().__init__()
        self._state = EngineState.ACTIVE
        self._mic_muted = False
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        self._partial_buffers = {}
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


async def test_partials_are_dropped_outside_active_sessions(qapp):
    engine = _FakeEngine()
    engine._state = EngineState.CONNECTING
    partial, _ = _hooks(engine)

    await partial(_event("early", "assistant"), None)
    assert engine.emitted == []


async def test_a_barge_in_cuts_the_reply_in_the_chat(qapp):
    """Realtime speech alone no longer cuts it there: roomkit's barge-in does."""
    engine = _FakeEngine()
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    cuts = []
    engine.reply_interrupted.connect(cuts.append)

    barge_in = next(fn for key, fn in kit.hooks.items() if key.lower().endswith("on_barge_in"))
    await barge_in(SimpleNamespace(interrupted_text="Hi!", audio_position_ms=0), None)

    assert cuts == [-1]  # roomkit 0.97 reports 0 there: the chat estimates it


def _hook(kit, name):
    return next(fn for key, fn in kit.hooks.items() if key.lower().endswith(name))


def _final(text, role):
    return SimpleNamespace(text=text, role=role, is_final=True)


async def test_a_measured_cut_says_how_much_played(qapp):
    engine = _FakeEngine()
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    cuts = []
    engine.reply_interrupted.connect(cuts.append)

    await _hook(kit, "on_barge_in")(SimpleNamespace(audio_position_ms=1200), None)

    assert cuts == [1200]


async def test_the_late_words_of_a_cut_reply_open_no_second_entry(qapp):
    """Gemini: its final, the whole reply, comes after the barge-in."""
    engine = _FakeEngine()
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    partial = _hook(kit, "on_partial_transcription")
    final = _hook(kit, "on_transcription")
    await partial(_event("I meant the messages", "assistant"), None)

    await _hook(kit, "on_barge_in")(SimpleNamespace(audio_position_ms=0), None)
    await partial(_event(" I repeated.", "assistant"), None)
    await final(_final("I meant the messages I repeated.", "assistant"), None)

    assert engine.emitted == [("I meant the messages", "assistant", False)]

    # The next reply shows again.
    await final(_final("Sure, can we move on?", "user"), None)
    await final(_final("Absolutely.", "assistant"), None)
    assert engine.emitted[-1] == ("Absolutely.", "assistant", True)


async def test_a_cut_reply_whose_final_never_comes_leaves_the_next_one_alone(qapp):
    engine = _FakeEngine()
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    await _hook(kit, "on_partial_transcription")(_event("I meant", "assistant"), None)
    await _hook(kit, "on_barge_in")(SimpleNamespace(audio_position_ms=0), None)

    await _hook(kit, "on_speech_end")(SimpleNamespace(), None)
    await _hook(kit, "on_partial_transcription")(_event("Absolutely", "assistant"), None)

    assert engine.emitted[-1] == ("Absolutely", "assistant", False)


async def test_a_cut_after_the_final_holds_nothing_back(qapp):
    """OpenAI writes its whole reply before it is spoken: the final is in."""
    engine = _FakeEngine()
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    final = _hook(kit, "on_transcription")
    await final(_final("It will be sunny tomorrow.", "assistant"), None)

    await _hook(kit, "on_barge_in")(SimpleNamespace(audio_position_ms=0), None)
    await final(_final("And the day after?", "user"), None)
    await final(_final("It will rain.", "assistant"), None)

    assert engine.emitted[-1] == ("It will rain.", "assistant", True)
