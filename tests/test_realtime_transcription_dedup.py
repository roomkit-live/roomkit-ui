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
        self._realtime_provider_name = ""
        self._xai_final_handle = None
        self._xai_pending_final = None
        self._spk_rms_queue = []
        self.emitted = []
        self.transcription.connect(
            lambda text, role, final, spk: self.emitted.append((text, role, final))
        )


def _transcription_hook(engine):
    kit = _FakeKit()
    register_realtime_hooks(kit, engine)
    keys = [k for k in kit.hooks if "transcription" in k.lower() and "partial" not in k.lower()]
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


# -- xAI streaming finals (cumulative text, one bubble) -----------------------


def _xai_engine():
    engine = _FakeEngine()
    engine._realtime_provider_name = "xai"
    engine._xai_final_handle = None
    engine._xai_pending_final = None
    return engine


async def test_growing_finals_collapse_into_one_bubble(qapp, monkeypatch):
    import asyncio

    import roomkit_ui.hooks as hooks_mod

    monkeypatch.setattr(hooks_mod, "_XAI_FINAL_DEBOUNCE_S", 0.05)
    engine = _xai_engine()
    hook = _transcription_hook(engine)

    r1 = await hook(_event("Quelle aventure ?"), None)
    r2 = await hook(_event("Quelle aventure ? De quelle aventure ?"), None)
    r3 = await hook(_event("Quelle aventure ? De quelle aventure tu veux qu'on parle ?"), None)

    # Every streaming update is blocked (never reaches chat or room)…
    assert {r.action for r in (r1, r2, r3)} == {"block"}
    assert engine.emitted == []

    # …and after the stream goes quiet, exactly one final with the full text.
    await asyncio.sleep(0.15)
    assert engine.emitted == [
        ("Quelle aventure ? De quelle aventure tu veux qu'on parle ?", "user", True)
    ]


async def test_assistant_reply_flushes_the_pending_user_final_first(qapp, monkeypatch):
    import roomkit_ui.hooks as hooks_mod

    monkeypatch.setattr(hooks_mod, "_XAI_FINAL_DEBOUNCE_S", 30.0)  # never fires on its own
    engine = _xai_engine()
    hook = _transcription_hook(engine)

    await hook(_event("Quelle aventure ?"), None)
    await hook(_event("Réponse de l'assistant.", role="assistant"), None)

    # User bubble lands before the assistant's, in order.
    assert engine.emitted == [
        ("Quelle aventure ?", "user", True),
        ("Réponse de l'assistant.", "assistant", True),
    ]
    assert engine._xai_final_handle is None


async def test_non_xai_providers_keep_immediate_finals(qapp):
    engine = _FakeEngine()
    engine._realtime_provider_name = "gemini"
    engine._xai_final_handle = None
    engine._xai_pending_final = None
    hook = _transcription_hook(engine)

    await hook(_event("Salut !"), None)
    assert engine.emitted == [("Salut !", "user", True)]
