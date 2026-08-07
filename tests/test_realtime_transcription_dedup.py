"""The realtime transcription hook suppresses wire-duplicated finals.

xAI's realtime server can emit the input-transcription-completed event
twice for one utterance — the user saw every sentence appear twice in the
chat.  Blocking in the hook keeps the duplicate out of the chat AND out of
the room timeline the model reads.  A genuine repetition is safe: a human
re-saying the same words takes seconds, the wire duplicate milliseconds.
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
        self._last_finals = {}
        self._spk_rms_queue = []
        self.emitted = []
        self.transcription.connect(
            lambda text, role, final, spk: self.emitted.append((text, role, final))
        )


def _transcription_hook(engine):
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    keys = [
        k for k in kit.hooks if "transcription" in k.lower() and "partial" not in k.lower()
    ]
    assert keys, f"no transcription hook registered — got {list(kit.hooks)}"
    return kit.hooks[keys[0]]


def _event(text, role="user", final=True):
    return SimpleNamespace(text=text, role=role, is_final=final)


async def test_wire_duplicate_final_is_blocked(qapp):
    engine = _FakeEngine()
    hook = _transcription_hook(engine)

    result = await hook(_event("Salut, comment ça va ?"), None)
    duplicate = await hook(_event("Salut, comment ça va ?"), None)

    assert result.action != "block"
    assert duplicate.action == "block"
    assert engine.emitted == [("Salut, comment ça va ?", "user", True)]


async def test_different_finals_pass(qapp):
    engine = _FakeEngine()
    hook = _transcription_hook(engine)

    await hook(_event("Première phrase."), None)
    await hook(_event("Deuxième phrase."), None)

    assert len(engine.emitted) == 2


async def test_slow_genuine_repetition_passes(qapp, monkeypatch):
    engine = _FakeEngine()
    hook = _transcription_hook(engine)

    await hook(_event("Oui."), None)
    # A human repeat lands seconds later — age the guard past its window.
    text, ts = engine._last_finals["user"]
    engine._last_finals["user"] = (text, ts - 5.0)
    await hook(_event("Oui."), None)

    assert len(engine.emitted) == 2


async def test_assistant_finals_are_never_deduped(qapp):
    engine = _FakeEngine()
    hook = _transcription_hook(engine)

    await hook(_event("Bien sûr !", role="assistant"), None)
    await hook(_event("Bien sûr !", role="assistant"), None)

    assert len(engine.emitted) == 2
