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


async def test_tokens_issued_for_another_url_are_dropped_not_sent(secure_store):
    # A server keeps its id when its URL is edited: the old host's bearer and
    # refresh token must not be handed to the new one.
    old = SecretTokenStorage("srv", store=secure_store, server_url="https://old.test/mcp")
    await old.set_tokens(OAuthToken(access_token="old-access", refresh_token="old-refresh"))
    await old.set_client_info(
        OAuthClientInformationFull(
            client_id="old-client", redirect_uris=["http://127.0.0.1:1234/callback"]
        )
    )
    assert has_oauth_tokens("srv", "https://evil.test/mcp") is False

    moved = SecretTokenStorage("srv", store=secure_store, server_url="https://evil.test/mcp")

    assert await moved.get_tokens() is None
    assert await moved.get_client_info() is None
    assert secure_store.get_secret("mcp_oauth:srv:tokens") == ""


async def test_a_preset_client_id_does_not_bind_old_tokens_to_a_new_url(secure_store):
    old = SecretTokenStorage("srv", store=secure_store, server_url="https://old.test/mcp")
    await old.set_tokens(OAuthToken(access_token="old-access"))

    # create_oauth_provider writes the configured client before the SDK reads.
    moved = SecretTokenStorage("srv", store=secure_store, server_url="https://new.test/mcp")
    await moved.set_client_info(
        OAuthClientInformationFull(
            client_id="client-id", redirect_uris=["http://127.0.0.1:1234/callback"]
        )
    )

    assert await moved.get_tokens() is None
    assert (await moved.get_client_info()).client_id == "client-id"


async def test_tokens_for_the_same_url_are_kept(secure_store):
    first = SecretTokenStorage("srv", store=secure_store, server_url="https://a.test/mcp")
    await first.set_tokens(OAuthToken(access_token="access"))

    again = SecretTokenStorage("srv", store=secure_store, server_url="https://a.test/mcp")

    assert (await again.get_tokens()).access_token == "access"
    assert has_oauth_tokens("srv", "https://a.test/mcp") is True


async def test_tokens_saved_before_the_binding_are_adopted_by_their_url(secure_store):
    unbound = SecretTokenStorage("srv", store=secure_store)
    await unbound.set_tokens(OAuthToken(access_token="access"))

    reader = SecretTokenStorage("srv", store=secure_store, server_url="https://a.test/mcp")

    assert (await reader.get_tokens()).access_token == "access"
    assert secure_store.get_secret("mcp_oauth:srv:url") == "https://a.test/mcp"
