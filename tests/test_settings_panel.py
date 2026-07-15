"""Guards the settings panel's index alignment.

The sidebar labels, the _pages tuple and the hardcoded *_TAB constants are
three parallel structures kept in sync by hand. Inserting a tab shifts every
index below it, and nothing but these assertions would notice.
"""

import pytest

from roomkit_ui.widgets.settings.cli_tools_page import _CliToolsPage
from roomkit_ui.widgets.settings.panel import SettingsPanel


@pytest.fixture
def panel(qapp):
    p = SettingsPanel()
    yield p
    p.deleteLater()


def test_every_sidebar_label_has_a_page(panel):
    assert panel._sidebar.count() == len(panel._pages)
    assert panel._stack.count() == len(panel._pages)


def test_the_cli_tools_tab_sits_next_to_mcp_servers(panel):
    labels = [panel._sidebar.item(i).text() for i in range(panel._sidebar.count())]

    assert labels.index("CLI Tools") == labels.index("MCP Servers") + 1


def test_the_refresh_hook_constants_still_point_at_their_own_pages(panel):
    # These fire page-specific refreshes on tab change; a stale index would
    # silently refresh the wrong page.
    assert panel._pages[panel._AUDIO_DEBUG_TAB] is panel._audio_debug
    assert panel._pages[panel._SKILLS_TAB] is panel._skills
    assert panel._pages[panel._AI_TAB] is panel._ai
    assert panel._pages[panel._DICTATION_TAB] is panel._dictation
    assert panel._pages[panel._ATTITUDES_TAB] is panel._attitudes
    assert panel._pages[panel._SPEAKERS_TAB] is panel._speakers


def test_the_cli_tools_page_is_registered_and_contributes_its_slice(panel):
    cli_page = next(p for p in panel._pages if isinstance(p, _CliToolsPage))

    assert "cli_tools" in cli_page.get_settings()
