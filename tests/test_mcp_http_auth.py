"""Authentication choices preserve existing headers and produce one credential."""

import base64
import json

import pytest
import shiboken6
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLineEdit

from roomkit_ui.mcp_config import mcp_server_problem, parse_mcp_headers
from roomkit_ui.mcp_http_auth import HTTPAuthentication
from roomkit_ui.mcp_manager import _request_headers
from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.widgets.settings.mcp_page import _MCPPage


@pytest.mark.parametrize(
    "value, mode, credential, username, password",
    [
        ("Bearer my-token", "bearer", "my-token", "", ""),
        ("my-key", "api_key", "my-key", "", ""),
        (
            "Basic " + base64.b64encode(b"sylvain:secret:with:colons").decode(),
            "basic",
            "",
            "sylvain",
            "secret:with:colons",
        ),
        ("Basic invalid-base64", "api_key", "Basic invalid-base64", "", ""),
    ],
)
def test_legacy_none_with_authorization_has_an_explicit_method(
    value, mode, credential, username, password
):
    auth = HTTPAuthentication.from_server(
        {"auth": "none", "headers": f"authorization: {value}\nX-Workspace: demo"}
    )
    assert (auth.mode, auth.credential, auth.username, auth.password) == (
        mode,
        credential,
        username,
        password,
    )
    assert auth.headers == "X-Workspace: demo"
    assert parse_mcp_headers(auth.header_block()) == {
        "Authorization": value,
        "X-Workspace": "demo",
    }


def test_raw_authorization_stays_raw_when_its_value_looks_like_bearer():
    auth = HTTPAuthentication.from_server(
        {"auth": "api_key", "headers": "Authorization: Bearer literal-value"}
    )
    assert auth.mode == "api_key"
    assert auth.credential == "Bearer literal-value"
    assert auth.header_block() == "Authorization: Bearer literal-value"


@pytest.mark.parametrize("credential", ['"literal-quotes"', "key-with-a-comma,"])
def test_raw_key_keeps_its_literal_value_through_storage_and_transport(page, credential):
    page._auth_combo.setCurrentIndex(page._auth_combo.findData("api_key"))
    page._auth_credential.setText(credential)
    save_settings(page.get_settings())
    [server] = json.loads(load_settings()["mcp_servers"])
    assert _request_headers(server) == {"Authorization": credential}


def test_json_headers_decode_escapes_but_reject_embedded_line_breaks():
    assert parse_mcp_headers('"X-Value": "one\\"two,",') == {"X-Value": 'one"two,'}
    assert parse_mcp_headers('"X-Value": "one\\nInjected: two",') == {}


def test_bearer_accepts_a_pasted_prefix_without_doubling_it():
    assert HTTPAuthentication("bearer", "Bearer abc").header_block() == "Authorization: Bearer abc"


@pytest.mark.parametrize("mode", ["none", "oauth2"])
def test_switching_off_manual_auth_removes_its_header(mode):
    auth = HTTPAuthentication(mode, headers="authorization: old-secret\nX-Workspace: demo")
    assert auth.header_block() == "X-Workspace: demo"


def test_oauth_alone_supplies_authorization_to_the_transport():
    assert _request_headers(
        {"auth": "oauth2", "headers": "AUTHORIZATION: stale\nX-Workspace: demo"}
    ) == {"X-Workspace": "demo"}


@pytest.mark.parametrize("mode", ["bearer", "api_key", "basic"])
def test_incomplete_authentication_is_not_a_ready_server(mode):
    assert mcp_server_problem({"transport": "sse", "url": "https://mcp.test", "auth": mode})


@pytest.fixture
def page(qapp):
    page = _MCPPage({})
    page._add_server()
    page._name_edit.setText("Workspace")
    page._transport_combo.setCurrentIndex(2)
    page._url_edit.setText("https://mcp.example.test")
    yield page
    shiboken6.delete(page)


def test_authentication_fields_follow_the_selection_and_roundtrip(page):
    assert page._auth_credential.isHidden()
    page._auth_combo.setCurrentIndex(page._auth_combo.findData("bearer"))
    assert not page._auth_credential.isHidden()
    assert page._auth_username.isHidden()
    assert page._auth_credential.echoMode() == QLineEdit.Password
    page._auth_credential.setText("token")
    page._headers_edit.setPlainText("X-Workspace: demo")
    [server] = json.loads(page.get_servers_json())
    assert server["auth"] == "bearer"
    assert parse_mcp_headers(server["headers"])["Authorization"] == "Bearer token"

    page._auth_combo.setCurrentIndex(page._auth_combo.findData("basic"))
    assert page._auth_credential.isHidden()
    assert not page._auth_username.isHidden()
    assert page._auth_password.echoMode() == QLineEdit.Password
    page._auth_username.setText("sylvain")
    page._auth_password.setText("secret:part2")
    page._show_list()
    page._show_edit(0)
    assert page._auth_combo.currentData() == "basic"
    assert page._auth_username.text() == "sylvain"
    assert page._auth_password.text() == "secret:part2"
    assert page._headers_edit.toPlainText() == "X-Workspace: demo"


def test_pasting_a_legacy_header_selects_its_method(page):
    page._headers_edit.setPlainText('"Authorization": "Bearer secret",\nX-Workspace: demo')
    assert page._auth_combo.currentData() == "bearer"
    assert page._auth_credential.text() == "secret"
    assert page._headers_edit.toPlainText() == "X-Workspace: demo"
    assert not page._auth_credential.isHidden()


def test_none_removes_the_stored_credential_without_changing_other_headers(page):
    page._auth_combo.setCurrentIndex(page._auth_combo.findData("bearer"))
    page._auth_credential.setText("private-token")
    page._headers_edit.setPlainText("X-Workspace: demo")
    save_settings(page.get_settings())
    assert "private-token" not in QSettings().value("room/mcp_servers")
    page._auth_combo.setCurrentIndex(page._auth_combo.findData("none"))
    save_settings(page.get_settings())
    [server] = json.loads(load_settings()["mcp_servers"])
    assert server["auth"] == "none"
    assert server["headers"] == "X-Workspace: demo"
    # An empty header must not bring back the credential that was removed.
    server["headers"] += "\nAuthorization:"
    QSettings().setValue("room/mcp_servers", json.dumps([server]))
    assert "private-token" not in load_settings()["mcp_servers"]


def test_basic_credentials_are_stored_in_the_secret_store(page):
    page._auth_combo.setCurrentIndex(page._auth_combo.findData("basic"))
    page._auth_username.setText("sylvain")
    page._auth_password.setText("secret password")
    save_settings(page.get_settings())
    stored = QSettings().value("room/mcp_servers")
    assert "sylvain" not in stored and "secret password" not in stored
    assert base64.b64encode(b"sylvain:secret password").decode() not in stored
    [server] = json.loads(load_settings()["mcp_servers"])
    restored = HTTPAuthentication.from_server(server)
    assert restored.username == "sylvain" and restored.password == "secret password"
