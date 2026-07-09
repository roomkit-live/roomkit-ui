import json

from roomkit_ui.mcp_config import enabled_mcp_servers, has_enabled_mcp_servers, parse_mcp_servers


def test_parse_mcp_servers_ignores_invalid_json_and_non_lists():
    assert parse_mcp_servers("{bad json") == []
    assert parse_mcp_servers({"name": "not-a-list"}) == []


def test_parse_mcp_servers_filters_non_dict_entries():
    raw = json.dumps(
        [
            {"name": "srv-a"},
            "bad",
            None,
            {"name": "srv-b", "enabled": False},
        ]
    )

    assert parse_mcp_servers(raw) == [
        {"name": "srv-a"},
        {"name": "srv-b", "enabled": False},
    ]


def test_enabled_mcp_servers_filters_disabled_entries():
    raw = [
        {"name": "srv-a"},
        {"name": "srv-b", "enabled": False},
    ]

    assert enabled_mcp_servers(raw) == [{"name": "srv-a"}]
    assert has_enabled_mcp_servers(raw) is True
    assert has_enabled_mcp_servers([{"name": "srv-b", "enabled": False}]) is False
