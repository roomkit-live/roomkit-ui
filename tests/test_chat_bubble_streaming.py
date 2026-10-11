"""Assistant text rolls out word by word, whatever the provider's cadence.

Gemini trickles its transcript, Grok/OpenAI hand it over in a few big
chunks with an early final.  Snapping updates and finals into place is
what killed the rolling-text feel — the reveal now owns the pacing and a
final waits for the animation before rendering markdown.
"""

import time

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

import roomkit_ui.widgets.chat_bubble as bubble_mod
from roomkit_ui.widgets.chat_view import ChatView

LONG = "Salut ! Ça va super bien merci et je suis prêt à plonger dans l'action avec toi."
REPLY = "Hi! I'm doing great, thanks, and ready to jump into the action with you."


def _pump_until(condition, timeout_s=3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return False


def _fast(monkeypatch):
    monkeypatch.setattr(bubble_mod, "_STREAM_WORD_MS", 5)
    monkeypatch.setattr(bubble_mod, "_STREAM_CATCHUP_MS", 5)


def test_final_only_assistant_text_still_rolls_out(qapp, monkeypatch):
    """The Grok shape: full transcript arrives as one final, no partials."""
    _fast(monkeypatch)
    view = ChatView()
    try:
        view.add_transcription(LONG, "assistant", True)
        bubble = view._bubbles()[-1]

        # Not snapped into place: the reveal is running, words still pending.
        assert bubble.finalized is False
        assert len(bubble._label.text().split()) < len(LONG.split())

        # The animation completes, then the real finalization runs (markdown).
        assert _pump_until(lambda: bubble.finalized)
        assert bubble.text() == LONG
    finally:
        view.deleteLater()


def test_growing_partials_extend_the_reveal_without_snapping(qapp, monkeypatch):
    _fast(monkeypatch)
    view = ChatView()
    try:
        view.add_transcription("Salut ! Ça va", "assistant", False)
        bubble = view._reply
        view.add_transcription(LONG, "assistant", False)

        # The fuller update must not snap the whole text into the label.
        assert len(bubble._label.text().split()) < len(LONG.split())

        view.add_transcription(LONG, "assistant", True)
        assert _pump_until(lambda: bubble.finalized)
        assert bubble.text() == LONG
    finally:
        view.deleteLater()


def test_user_bubbles_finalize_immediately(qapp):
    view = ChatView()
    try:
        view.add_transcription("Salut, comment ça va ?", "user", True)
        bubble = view._bubbles()[-1]
        assert bubble.finalized is True
        assert bubble.text() == "Salut, comment ça va ?"
    finally:
        view.deleteLater()


def _assistant_bubbles(view):
    return [b for b in view._bubbles() if b.role == "assistant"]


def test_a_cut_keeps_what_the_voice_had_said_with_a_marker(qapp, monkeypatch):
    """Not the words it was going to say: those of the audio that played."""
    monkeypatch.setattr(bubble_mod, "_STREAM_WORD_MS", 10_000)  # reveal frozen mid-way
    view = ChatView()
    try:
        view.add_transcription(REPLY, "assistant", True)
        assistant = view._bubbles()[-1]
        assert assistant.finalized is False  # still revealing

        heard = len("Hi! I'm doing great,") * bubble_mod._SPOKEN_MS_PER_CHAR
        view.interrupt_reply(heard)

        assert assistant.finalized is True  # snapped, not left rolling
        assert assistant.text() == "Hi! I'm doing great…"
        assert assistant._interrupted_label.isHidden() is False
    finally:
        view.deleteLater()


def test_a_cut_not_measured_keeps_what_the_time_spoken_said(qapp, monkeypatch):
    """Realtime: roomkit does not say how much played.  Gemini writes ahead of
    its voice and the reveal catches up past it: the time spoken stands for it."""
    _fast(monkeypatch)
    view = ChatView()
    try:
        view.add_transcription(REPLY, "assistant", False)
        reply = view._reply
        assert _pump_until(lambda: reply._label.text() == REPLY)  # all shown
        reply._stream_started = time.monotonic() - 1.5  # its voice began 1.5 s ago

        view.interrupt_reply(-1)

        assert reply.text() == "Hi! I'm doing great…"  # 1.5 s ≈ 25 characters
        assert reply._interrupted_label.isHidden() is False
    finally:
        view.deleteLater()


def test_what_a_voice_said_ends_on_a_whole_word():
    ms = bubble_mod._SPOKEN_MS_PER_CHAR
    text = "Tomorrow, it will be sunny. Then it will rain."

    assert bubble_mod._said_in(text, 0) == "Tomorrow…"  # never "…" alone
    assert bubble_mod._said_in(text, ms * len("Tomorrow, it")) == "Tomorrow, it…"
    assert bubble_mod._said_in(text, ms * len("Tomorrow, i")) == "Tomorrow…"  # no stray comma
    said = "Tomorrow, it will be sunny."
    assert bubble_mod._said_in(text, ms * len(said)) == said
    assert bubble_mod._said_in(text, ms * 1000) == text


def test_speech_over_a_reply_neither_cuts_nor_splits_it(qapp, monkeypatch):
    """Barge-in off: "Ok thanks." while the voice goes on, then the reply's final.

    The chat took the speech for a cut ("— interrupted") and the final
    opened a second bubble with the whole reply.
    """
    monkeypatch.setattr(bubble_mod, "_STREAM_WORD_MS", 10_000)  # reveal frozen mid-way
    view = ChatView()
    try:
        view.add_transcription("All right, I understand.", "assistant", False)
        reply = view._reply

        view.add_transcription("Ok thanks.", "user", False)
        assert reply.finalized is False
        assert reply._interrupted_label.isHidden() is True

        view.add_transcription(REPLY, "assistant", True)

        assert _assistant_bubbles(view) == [reply]
        assert reply.text() == REPLY
        assert reply._interrupted_label.isHidden() is True
        assert [b.text() for b in view._bubbles() if b.role == "user"] == ["Ok thanks."]
    finally:
        view.deleteLater()


def test_a_user_final_over_a_reply_keeps_both_entries(qapp, monkeypatch):
    _fast(monkeypatch)
    view = ChatView()
    try:
        view.add_transcription("Hi!", "assistant", False)
        view.add_transcription("Yes.", "user", True)
        view.add_transcription("Hi! How are you?", "assistant", True)

        (reply,) = _assistant_bubbles(view)
        assert _pump_until(lambda: reply.finalized)
        assert reply.text() == "Hi! How are you?"
    finally:
        view.deleteLater()


def test_the_words_after_a_cut_open_a_new_entry(qapp, monkeypatch):
    monkeypatch.setattr(bubble_mod, "_STREAM_WORD_MS", 10_000)
    view = ChatView()
    try:
        view.add_transcription("Tomorrow it will", "assistant", False)
        view.interrupt_reply()
        view.add_transcription("Yes?", "assistant", False)

        first, second = _assistant_bubbles(view)
        assert first._interrupted_label.isHidden() is False
        assert second.text() == "Yes?"
    finally:
        view.deleteLater()


def test_a_cut_after_the_reply_was_fully_shown_marks_nothing(qapp, monkeypatch):
    _fast(monkeypatch)
    view = ChatView()
    try:
        view.add_transcription("Done.", "assistant", True)
        (reply,) = _assistant_bubbles(view)
        assert _pump_until(lambda: reply.finalized)

        view.interrupt_reply()

        assert reply._interrupted_label.isHidden() is True
    finally:
        view.deleteLater()


def test_a_cut_after_a_reset_mid_reveal_leaves_the_deleted_bubble_alone(qapp, monkeypatch):
    """Reset deletes the revealing bubble; a barge-in must not try to snap it."""
    monkeypatch.setattr(bubble_mod, "_STREAM_WORD_MS", 10_000)  # reveal frozen mid-way
    view = ChatView()
    try:
        view.add_transcription(REPLY, "assistant", True)
        view.reset()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        view.interrupt_reply()  # must not raise
    finally:
        view.deleteLater()


def test_normal_completion_shows_no_interrupted_marker(qapp, monkeypatch):
    _fast(monkeypatch)
    view = ChatView()
    try:
        view.add_transcription(LONG, "assistant", True)
        bubble = view._bubbles()[-1]
        assert _pump_until(lambda: bubble.finalized)
        assert bubble._interrupted_label.isHidden() is True
    finally:
        view.deleteLater()
