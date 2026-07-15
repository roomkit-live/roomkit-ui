import json

import pytest

from roomkit_ui.cli_tools_config import (
    DEFAULT_HELP_DEPTH,
    DEFAULT_TIMEOUT,
    enabled_cli_tools,
    has_enabled_cli_tools,
    help_depth,
    parse_cli_tools,
    slugify_tool_name,
)


def test_parse_cli_tools_ignores_invalid_json_and_non_lists():
    assert parse_cli_tools("{bad json") == []
    assert parse_cli_tools({"name": "not-a-list"}) == []


def test_parse_cli_tools_filters_non_dict_entries():
    raw = json.dumps([{"name": "gh"}, "bad", None, {"name": "docker", "enabled": False}])

    assert parse_cli_tools(raw) == [{"name": "gh"}, {"name": "docker", "enabled": False}]


def test_enabled_cli_tools_filters_disabled_entries():
    raw = [{"name": "gh"}, {"name": "docker", "enabled": False}]

    assert enabled_cli_tools(raw) == [{"name": "gh"}]
    assert has_enabled_cli_tools(raw) is True
    assert has_enabled_cli_tools([{"name": "docker", "enabled": False}]) is False


@pytest.mark.parametrize("name", ["gh", "kubectl", "my-tool", "my_tool_2"])
def test_slugify_leaves_an_already_safe_name_alone(name):
    assert slugify_tool_name(name) == name


def test_slugify_derives_a_callable_name_from_a_human_one():
    # The reported bug: a name with a space was rejected outright, so the
    # tool was never advertised and the user saw nothing.
    assert slugify_tool_name("GitHub CLI") == "github_cli"
    assert slugify_tool_name("  GitHub CLI  ") == "github_cli"
    assert slugify_tool_name("dots.not.ok") == "dots_not_ok"
    assert slugify_tool_name("Wow!!! Great") == "wow_great"


def test_slugify_trims_to_the_provider_name_limit():
    assert len(slugify_tool_name("a" * 100)) == 64


def test_slugify_never_leaves_leading_or_trailing_separators():
    assert slugify_tool_name("!!!gh!!!") == "gh"
    assert slugify_tool_name("-gh-") == "gh"


@pytest.mark.parametrize("name", ["", "   ", "!!!", "...", None])
def test_slugify_returns_empty_when_nothing_usable_remains(name):
    assert slugify_tool_name(name) == ""


def test_tool_timeout_falls_back_on_missing_or_unusable_values():
    from roomkit_ui.cli_tools_config import tool_timeout

    assert tool_timeout({}) == DEFAULT_TIMEOUT
    assert tool_timeout({"timeout": "nope"}) == DEFAULT_TIMEOUT
    assert tool_timeout({"timeout": 0}) == DEFAULT_TIMEOUT
    assert tool_timeout({"timeout": -5}) == DEFAULT_TIMEOUT
    assert tool_timeout({"timeout": 30}) == 30.0


def test_help_depth_is_zero_when_seeding_is_off():
    assert help_depth({"seed_help": False, "help_depth": 2}) == 0


def test_help_depth_defaults_and_clamps():
    assert help_depth({}) == DEFAULT_HELP_DEPTH
    assert help_depth({"help_depth": "nope"}) == DEFAULT_HELP_DEPTH
    assert help_depth({"help_depth": 99}) == 3
    assert help_depth({"help_depth": -1}) == 0
