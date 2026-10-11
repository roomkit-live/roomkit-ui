"""Palette changes refresh existing widgets without resetting their state."""

import shiboken6
from PySide6.QtWidgets import QLabel

from roomkit_ui.theme import get_colors
from roomkit_ui.theme_live import apply_theme, themed_style
from roomkit_ui.widgets.chat_bubble import ChatBubble


def test_a_replaced_binding_only_renders_the_current_style(qapp):
    label = QLabel()
    called = []

    def first(colors):
        called.append("first")
        return f"color: {colors['TEXT_PRIMARY']};"

    def second(colors):
        called.append("second")
        return f"color: {colors['ACCENT_RED']};"

    try:
        themed_style(label, first)
        themed_style(label, second)
        called.clear()
        apply_theme("light")
        assert called == ["second"]
        assert get_colors("light")["ACCENT_RED"] in label.styleSheet()
    finally:
        shiboken6.delete(label)
    called.clear()
    apply_theme("dark")
    assert called == []  # closing a page disconnects its palette bindings


def test_chat_markdown_updates_without_restarting_streaming_or_changing_text(qapp):
    bubble = ChatBubble("Use `code`.")
    try:
        bubble.finalize()
        original = bubble._raw_text
        for theme in ("light", "dark"):
            apply_theme(theme)
            assert bubble._raw_text == original
            assert bubble.finalized
            assert not bubble._stream_timer.isActive()
            assert get_colors(theme)["CODE_BG"] in bubble._label.text()
    finally:
        shiboken6.delete(bubble)
