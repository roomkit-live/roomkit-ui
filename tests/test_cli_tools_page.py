"""The settings page ↔ QSettings round-trip for CLI tool declarations.

The panel has no Save button — it persists on close from whatever the page
kept in memory — so the live sync and the settings slice are the contract.
"""

import json

import pytest

from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.widgets.settings.cli_tools_page import _CliToolsPage


@pytest.fixture
def page(qapp):
    return _CliToolsPage({})


def test_a_declared_tool_survives_a_save_and_reload(page):
    page._add_tool()
    page._name_edit.setText("gh")
    page._command_edit.setText("gh")
    page._description_edit.setText("GitHub CLI")

    save_settings(page.get_settings())

    reloaded = json.loads(load_settings()["cli_tools"])
    assert reloaded == [
        {
            "enabled": True,
            "name": "gh",
            "command": "gh",
            "description": "GitHub CLI",
            "seed_help": True,
            "help_depth": 2,
            "timeout": 10.0,
        }
    ]


def test_a_human_name_shows_what_the_assistant_will_actually_call(page):
    # The derived name is what the model receives, so it has to be on screen —
    # deriving in silence leaves the user unable to explain a failing call.
    page._add_tool()
    page._name_edit.setText("GitHub CLI")

    assert page._name_status.text() == "The assistant calls this: github_cli"
    # The list keeps the name as typed — only the function name is derived.
    assert page._tool_list.item(0).text() == "GitHub CLI"


def test_a_name_with_nothing_usable_in_it_is_called_out(page):
    page._add_tool()
    page._name_edit.setText("!!!")

    assert "Unusable name" in page._name_status.text()


def test_editing_a_field_syncs_to_the_model_without_a_save_button(page):
    page._add_tool()
    page._name_edit.setText("gh")

    assert page._tools[0]["name"] == "gh"
    assert page._tool_list.item(0).text() == "gh"


def test_populating_the_form_does_not_clobber_a_sibling_declaration(page):
    # _show_edit must block signals while it populates, or _sync_to_model
    # fires mid-populate and writes row 0's widgets into row 1.
    page._add_tool()
    page._name_edit.setText("first")
    page._add_tool()
    page._name_edit.setText("second")

    page._show_edit(0)

    assert [t["name"] for t in page._tools] == ["first", "second"]


def test_a_disabled_tool_says_so_in_the_list(page):
    page._add_tool()
    page._name_edit.setText("gh")
    page._enabled_check.setChecked(False)

    assert page._tool_list.item(0).text() == "gh (disabled)"


def test_the_command_field_reports_a_resolved_binary(page):
    page._add_tool()
    page._command_edit.setText("echo")

    assert page._command_status.text().endswith("/echo")


def test_the_command_field_reports_a_binary_it_cannot_find(page):
    page._add_tool()
    page._command_edit.setText("definitely-not-a-real-binary-xyz")

    assert "Not found" in page._command_status.text()


def test_removing_a_tool_drops_it_from_both_model_and_list(page):
    page._add_tool()
    page._name_edit.setText("gh")
    page._tool_list.setCurrentRow(0)

    page._remove_tool()

    assert page._tools == []
    assert page._tool_list.count() == 0


def test_help_depth_hides_when_seeding_is_off(page):
    page._add_tool()
    page._seed_help_check.setChecked(False)

    assert page._tools[0]["seed_help"] is False
    assert not page._help_depth_spin.isVisible()
