"""Assistant text rolls out word by word, whatever the provider's cadence.

Gemini trickles its transcript, Grok/OpenAI hand it over in a few big
chunks with an early final.  Snapping updates and finals into place is
what killed the rolling-text feel — the reveal now owns the pacing and a
final waits for the animation before rendering markdown.
"""

import time

from PySide6.QtWidgets import QApplication

import roomkit_ui.widgets.chat_bubble as bubble_mod
from roomkit_ui.widgets.chat_view import ChatView

LONG = "Salut ! Ça va super bien merci et je suis prêt à plonger dans l'action avec toi."


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
        bubble = view._layout.itemAt(view._layout.count() - 3).widget()

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
        bubble = view._current_bubble
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
        bubble = view._layout.itemAt(view._layout.count() - 3).widget()
        assert bubble.finalized is True
        assert bubble.text() == "Salut, comment ça va ?"
    finally:
        view.deleteLater()
