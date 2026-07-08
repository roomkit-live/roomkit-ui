"""Tests for secure OAuth token storage."""

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from PySide6.QtCore import QSettings

import roomkit_ui.mcp_auth as mcp_auth
from roomkit_ui.mcp_auth import SecretTokenStorage, clear_oauth_tokens, has_oauth_tokens
from roomkit_ui.secret_store import SecretStore


class _FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


@pytest.fixture
def secure_store(monkeypatch):
    store = SecretStore(service="svc", namespace="ns", keyring_backend=_FakeKeyring())
    monkeypatch.setattr(mcp_auth, "get_secret_store", lambda: store)
    return store


async def test_oauth_tokens_are_saved_in_secret_store(secure_store):
    storage = SecretTokenStorage("srv", store=secure_store)
    token = OAuthToken(access_token="access", refresh_token="refresh")

    await storage.set_tokens(token)
    out = await storage.get_tokens()

    assert out.access_token == "access"
    assert out.refresh_token == "refresh"
    assert "access" in secure_store.get_secret("mcp_oauth:srv:tokens")
    assert QSettings().value("room/mcp_oauth/srv/tokens", None) is None


async def test_oauth_client_info_is_saved_in_secret_store(secure_store):
    storage = SecretTokenStorage("srv", store=secure_store)
    client_info = OAuthClientInformationFull(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uris=["http://127.0.0.1:1234/callback"],
    )

    await storage.set_client_info(client_info)
    out = await storage.get_client_info()

    assert out.client_id == "client-id"
    assert out.client_secret == "client-secret"
    assert "client-secret" in secure_store.get_secret("mcp_oauth:srv:client_info")
    assert QSettings().value("room/mcp_oauth/srv/client_info", None) is None


async def test_oauth_legacy_tokens_are_migrated_on_read(secure_store):
    legacy = OAuthToken(access_token="legacy-access", refresh_token="legacy-refresh")
    qs = QSettings()
    qs.setValue("room/mcp_oauth/srv/tokens", legacy.model_dump_json())
    storage = SecretTokenStorage("srv", store=secure_store)

    out = await storage.get_tokens()

    assert out.access_token == "legacy-access"
    assert qs.value("room/mcp_oauth/srv/tokens", None) is None
    assert "legacy-access" in secure_store.get_secret("mcp_oauth:srv:tokens")


async def test_oauth_helpers_check_and_clear_secret_store(secure_store):
    storage = SecretTokenStorage("srv", store=secure_store)
    await storage.set_tokens(OAuthToken(access_token="access"))
    await storage.set_client_info(
        OAuthClientInformationFull(
            client_id="client-id",
            redirect_uris=["http://127.0.0.1:1234/callback"],
        )
    )

    assert has_oauth_tokens("srv") is True
    clear_oauth_tokens("srv")

    assert has_oauth_tokens("srv") is False
    assert secure_store.get_secret("mcp_oauth:srv:tokens") == ""
    assert secure_store.get_secret("mcp_oauth:srv:client_info") == ""
