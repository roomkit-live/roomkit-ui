"""VC hooks: the assistant bubble grows sentence by sentence, and a failed
turn says so in the chat.

roomkit runs BEFORE_TTS once per sentence of a streamed reply (and, since
0.95, for Gradium too), while ChatBubble.update_stream() wants the growing
text: emitting each sentence alone showed only the one being spoken.
"""

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_vc_hooks


class _FakeKit:
    def __init__(self):
        self.hooks = {}
        self.events = {}

    def hook(self, trigger, execution):
        def register(fn):
            self.hooks[str(trigger)] = fn
            return fn

        return register

    def on(self, name):
        def register(fn):
            self.events[name] = fn
            return fn

        return register


class _FakeEngine(QObject):
    transcription = Signal(str, str, bool, str)
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    mic_audio_level = Signal(float)
    speaker_identified = Signal(str, float)
    session_notice = Signal(str)

    def __init__(self):
        super().__init__()
        self._state = EngineState.ACTIVE
        self._mic_muted = False
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        self._speakers = None
        self._partial_buffers = {}
        self._spk_rms_queue = []
        self.emitted = []
        self.transcription.connect(
            lambda text, role, final, spk: self.emitted.append((text, role, final))
        )


def _hook(kit, name):
    return next(fn for key, fn in kit.hooks.items() if key.lower().endswith(name))


def _setup():
    engine = _FakeEngine()
    kit = _FakeKit()
    register_vc_hooks(kit, engine)
    return engine, kit


async def test_sentences_of_one_reply_accumulate_in_the_bubble():
    engine, kit = _setup()
    before = _hook(kit, "before_tts")

    await before("Hello there.", None)
    await before(" How can I help?", None)

    assert engine.emitted == [
        ("Hello there.", "assistant", False),
        ("Hello there. How can I help?", "assistant", False),
    ]


async def test_after_tts_closes_the_reply_so_the_next_one_starts_fresh():
    engine, kit = _setup()
    before, after = _hook(kit, "before_tts"), _hook(kit, "after_tts")

    await before("First reply.", None)
    await after("First reply.", None)
    await before("Second reply.", None)

    assert engine.emitted[-1] == ("Second reply.", "assistant", False)


async def test_a_user_turn_or_a_tts_error_also_closes_the_reply():
    engine, kit = _setup()
    before, user = _hook(kit, "before_tts"), _hook(kit, "on_transcription")

    await before("Cut off.", None)
    await user(SimpleNamespace(text="wait"), None)
    await before("New answer.", None)
    assert engine.emitted[-1] == ("New answer.", "assistant", False)

    await kit.events["tts_error"](SimpleNamespace(data={"provider": "gradium"}))
    await before("After the error.", None)
    assert engine.emitted[-1] == ("After the error.", "assistant", False)


# -- a turn the assistant could not answer -------------------------------------


async def test_a_failed_turn_says_why_in_the_chat():
    engine, kit = _setup()
    notices = []
    engine.session_notice.connect(notices.append)

    await _hook(kit, "on_error")(
        SimpleNamespace(metadata={"error": "anthropic: 401 invalid x-api-key"}), None
    )

    assert notices == ["The assistant could not answer: anthropic: 401 invalid x-api-key"]


async def test_a_local_tool_refusal_is_left_to_the_settings_hint():
    engine, kit = _setup()
    notices = []
    engine.session_notice.connect(notices.append)

    await _hook(kit, "on_error")(
        SimpleNamespace(metadata={"error": "qwen3:0.6b does not support tools"}), None
    )

    assert notices == []
