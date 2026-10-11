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


def test_code_and_logs_name_the_fixed_font_qt_knows(qapp):
    # "monospace" is a CSS name: Qt on macOS looked it up and warned.
    from roomkit_ui.theme import fixed_font_family
    from roomkit_ui.widgets.chat_bubble import _markdown_to_html
    from roomkit_ui.widgets.settings.components_page import _ComponentsPage

    family = fixed_font_family()
    html = _markdown_to_html(
        "Run `ls`:\n\n```\nls -la\n```",
        {"CODE_BG": "#000", "ACCENT_BLUE": "#00f", "BUBBLE_AI_TEXT": "#fff"},
    )
    page = _ComponentsPage({})
    try:
        # Whatever Qt names it here (Menlo on macOS; fontconfig's "monospace" on
        # Linux, which Qt resolves without a lookup).
        assert html.count(f"font-family:'{family}'") == 3  # inline code, the block, its code
        assert _families(page._log.styleSheet()) == [f'"{family}"']
    finally:
        shiboken6.delete(page)
