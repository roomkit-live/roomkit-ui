import json

import pytest

from roomkit_ui.mcp_config import (
    enabled_mcp_servers,
    has_enabled_mcp_servers,
    parse_mcp_servers,
    validate_mcp_http_url,
)


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


def test_validate_mcp_http_url_allows_localhost_and_https():
    assert validate_mcp_http_url(" http://localhost:8000/mcp ") == "http://localhost:8000/mcp"
    assert validate_mcp_http_url("https://example.com/mcp") == "https://example.com/mcp"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.com/mcp",
        "https://user:pass@example.com/mcp",
        "http:///missing-host",
    ],
)
def test_validate_mcp_http_url_rejects_invalid_or_credential_urls(url):
    with pytest.raises(ValueError):
        validate_mcp_http_url(url)
