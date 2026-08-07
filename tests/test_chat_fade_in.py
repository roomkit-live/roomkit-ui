"""New chat rows fade in; the effect is dropped once the animation lands."""

from PySide6.QtWidgets import QApplication

from roomkit_ui.widgets.chat_view import ChatView


def test_new_bubble_starts_transparent_and_lands_opaque(qapp):
    view = ChatView()
    try:
        view.add_transcription("Salut !", "user", True)
        bubble = None
        for i in range(view._layout.count()):
            w = view._layout.itemAt(i).widget()
            if w is not None and type(w).__name__ == "ChatBubble":
                bubble = w
        assert bubble is not None
        effect = bubble.graphicsEffect()
        assert effect is not None and effect.opacity() < 1.0

        # Let the 220 ms animation finish; the effect must then be removed
        # (a lingering opacity effect costs a render pass per paint).
        import time

        for _ in range(60):
            QApplication.processEvents()
            time.sleep(0.01)
            if bubble.graphicsEffect() is None:
                break
        assert bubble.graphicsEffect() is None
    finally:
        view.deleteLater()


def test_info_rows_fade_too(qapp):
    view = ChatView()
    try:
        view.add_info("MCP connecté")
        faded = [
            view._layout.itemAt(i).widget()
            for i in range(view._layout.count())
            if view._layout.itemAt(i).widget() is not None
            and view._layout.itemAt(i).widget().graphicsEffect() is not None
        ]
        assert faded  # the fresh status row carries the entrance effect
    finally:
        view.deleteLater()
