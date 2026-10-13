"""VC hooks: the assistant bubble grows sentence by sentence, and a failed
turn says so in the chat.

roomkit runs BEFORE_TTS once per sentence of a streamed reply (and, since
0.95, for Gradium too), while ChatBubble.update_stream() wants the growing
text: emitting each sentence alone showed only the one being spoken.

A reply ends when roomkit says so: AFTER_TTS, or ON_BARGE_IN when the
user's speech cut it.  Speech that does not cut it (barge-in off, an "ok")
used to end it in the chat while the voice went on, and its AFTER_TTS then
showed the whole reply a second time.
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
    reply_interrupted = Signal(int)
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
        self.cuts = []  # how much of each cut reply played (ms)
        self.reply_interrupted.connect(self.cuts.append)


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


async def test_a_user_turn_leaves_the_reply_being_spoken_open():
    """Barge-in off or an "ok": the voice goes on, and so does its bubble."""
    engine, kit = _setup()
    before, user = _hook(kit, "before_tts"), _hook(kit, "on_transcription")
    after = _hook(kit, "after_tts")

    await before("All right.", None)
    await user(SimpleNamespace(text="ok thanks"), None)
    await before("I'm still here.", None)
    assert engine.emitted[-1] == ("All right. I'm still here.", "assistant", False)

    await after("All right. I'm still here.", None)
    assert engine.emitted[-1] == ("All right. I'm still here.", "assistant", True)
    assert engine.cuts == []


async def test_a_tts_error_closes_the_reply():
    engine, kit = _setup()
    before = _hook(kit, "before_tts")

    await before("Cut off.", None)
    await kit.events["tts_error"](SimpleNamespace(data={"provider": "gradium"}))
    await before("After the error.", None)
    assert engine.emitted[-1] == ("After the error.", "assistant", False)


async def test_a_barge_in_cuts_the_reply_and_its_late_end_shows_nothing_twice():
    """roomkit still runs AFTER_TTS for the playback it cut, whole text included."""
    engine, kit = _setup()
    before, after = _hook(kit, "before_tts"), _hook(kit, "after_tts")
    barge_in = _hook(kit, "on_barge_in")

    await before("It will be sunny tomorrow.", None)
    await barge_in(
        SimpleNamespace(interrupted_text="It will be sunny tomorrow.", audio_position_ms=900), None
    )
    assert engine.cuts == [900]  # the chat keeps what 900 ms of voice said

    shown = list(engine.emitted)
    await after("It will be sunny tomorrow. Then it will rain.", None)
    assert engine.emitted == shown  # no final: the chat closed that bubble already

    await before("Yes?", None)
    await after("Yes?", None)
    assert engine.emitted[-2:] == [("Yes?", "assistant", False), ("Yes?", "assistant", True)]


async def test_a_cut_reply_that_never_ends_leaves_the_next_final_alone():
    engine, kit = _setup()
    before, after = _hook(kit, "before_tts"), _hook(kit, "after_tts")

    await before("Cut off.", None)
    await _hook(kit, "on_barge_in")(
        SimpleNamespace(interrupted_text="Cut off.", audio_position_ms=300), None
    )
    await before("Next reply.", None)
    await after("Next reply.", None)

    assert engine.emitted[-1] == ("Next reply.", "assistant", True)


async def test_a_barge_in_before_the_first_sentence_cuts_nothing_in_the_chat():
    engine, kit = _setup()
    await _hook(kit, "on_barge_in")(
        SimpleNamespace(interrupted_text="", audio_position_ms=0), None
    )
    await _hook(kit, "after_tts")("Late words.", None)

    assert engine.cuts == []
    assert engine.emitted[-1] == ("Late words.", "assistant", True)


# -- a turn the assistant could not answer -------------------------------------


async def test_a_failed_turn_says_why_in_the_chat():
    engine, kit = _setup()
    notices = []
    engine.session_notice.connect(notices.append)

    await _hook(kit, "on_error")(
        SimpleNamespace(metadata={"error": "anthropic: 401 invalid x-api-key"}), None
    )

    assert notices == ["The assistant could not answer: anthropic: 401 invalid x-api-key"]


async def test_a_prompt_too_long_for_llama_cpp_says_what_to_raise():
    engine, kit = _setup()
    notices = []
    engine.session_notice.connect(notices.append)
    error = (
        "llamacpp (400): Error code: 400 - {'error': {'code': 400, 'message': 'request "
        "(23074 tokens) exceeds the available context size (16128 tokens), try increasing "
        "it', 'type': 'exceed_context_size_error'}}"
    )

    await _hook(kit, "on_error")(SimpleNamespace(metadata={"error": error}), None)

    assert notices[0].startswith(
        "This conversation needs 23,074 tokens, more than the 16,128 the local model's "
        "context holds. Raise its Context"
    )
    assert "Tool search" in notices[0]


async def test_a_local_tool_refusal_is_left_to_the_settings_hint():
    engine, kit = _setup()
    notices = []
    engine.session_notice.connect(notices.append)

    await _hook(kit, "on_error")(
        SimpleNamespace(metadata={"error": "qwen3:0.6b does not support tools"}), None
    )

    assert notices == []
