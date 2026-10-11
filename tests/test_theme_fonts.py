"""The window and the chat use Qt's application font: no family named.

A named family can only be named wrong: "-apple-system" and "SF Pro Text"
are CSS and marketing names Qt does not know.  It skipped them for Helvetica
Neue on macOS, after a font-alias lookup it warned about at every start.
"""

import re

import shiboken6

from roomkit_ui.theme import get_stylesheet
from roomkit_ui.widgets.chat_bubble import ChatBubble


def _families(qss: str) -> list[str]:
    return [f.strip() for f in re.findall(r"font-family:\s*([^;]+);", qss)]


def test_the_window_names_no_font_family():
    for theme in ("dark", "light"):
        assert _families(get_stylesheet(theme)) == []


def test_the_chat_names_no_font_family(qapp):
    for role in ("user", "assistant"):
        bubble = ChatBubble("hello", role=role)
        try:
            assert _families(bubble._label.styleSheet()) == []
        finally:
            shiboken6.delete(bubble)
