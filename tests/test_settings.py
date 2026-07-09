"""Round-trip and coercion tests for QSettings persistence."""

import json

import pytest
from PySide6.QtCore import QSettings

import roomkit_ui.settings as settings_mod
from roomkit_ui.secret_store import SecretStore
from roomkit_ui.settings import _DEFAULTS, load_settings, save_settings


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
    monkeypatch.setattr(settings_mod, "get_secret_store", lambda: store)
    return store


def test_defaults_returned_when_nothing_saved():
    out = load_settings()
    assert set(out) == set(_DEFAULTS)
    assert out["provider"] == _DEFAULTS["provider"]
    assert out["input_device"] is None


def test_round_trip_preserves_values():
    save_settings({"provider": "openai", "stt_enabled": False, "vc_interruption": True})
    out = load_settings()
    assert out["provider"] == "openai"
    assert out["stt_enabled"] is False
    assert out["vc_interruption"] is True


def test_bool_strings_are_coerced():
    # QSettings ini storage stringifies bools; load must coerce them back.
    save_settings({"stt_enabled": "true", "diarization_enabled": "1", "stt_translate": "no"})
    out = load_settings()
    assert out["stt_enabled"] is True
    assert out["diarization_enabled"] is True
    assert out["stt_translate"] is False


def test_denoise_migrates_from_legacy_bool():
    save_settings({"denoise": True})
    assert load_settings()["denoise"] == "rnnoise"
    save_settings({"denoise": "false"})
    assert load_settings()["denoise"] == "none"


def test_diarization_threshold_coercion():
    save_settings({"diarization_threshold": "0.55"})
    assert load_settings()["diarization_threshold"] == 0.55
    save_settings({"diarization_threshold": "garbage"})
    assert load_settings()["diarization_threshold"] == 0.4


def test_device_indices_coercion():
    save_settings({"input_device": "3", "output_device": ""})
    out = load_settings()
    assert out["input_device"] == 3
    assert out["output_device"] is None
    save_settings({"input_device": "not-a-number"})
    assert load_settings()["input_device"] is None


def test_api_key_is_saved_outside_plain_qsettings(secure_store):
    save_settings({"openai_api_key": "sk-test"})

    qs = QSettings()
    assert qs.value("room/openai_api_key", None) is None
    assert secure_store.get_secret("settings:openai_api_key") == "sk-test"
    assert load_settings()["openai_api_key"] == "sk-test"


def test_api_key_legacy_plaintext_is_migrated(secure_store):
    qs = QSettings()
    qs.setValue("room/openai_api_key", "legacy-secret")

    out = load_settings()

    assert out["openai_api_key"] == "legacy-secret"
    assert qs.value("room/openai_api_key", None) is None
    assert secure_store.get_secret("settings:openai_api_key") == "legacy-secret"


def test_api_key_clear_deletes_secret(secure_store):
    save_settings({"openai_api_key": "sk-test"})
    save_settings({"openai_api_key": ""})

    assert load_settings()["openai_api_key"] == ""
    assert secure_store.get_secret("settings:openai_api_key") == ""


def test_mcp_oauth_client_secret_is_sanitized_and_hydrated(secure_store):
    servers = [
        {
            "name": "srv",
            "transport": "streamable_http",
            "auth": "oauth2",
            "url": "https://example.test/mcp",
            "oauth_client_secret": "client-secret",
        }
    ]

    save_settings({"mcp_servers": json.dumps(servers)})

    qs = QSettings()
    stored = json.loads(qs.value("room/mcp_servers"))
    server_id = stored[0]["id"]
    assert stored[0]["oauth_client_secret"] == ""
    assert secure_store.get_secret(f"mcp_server:{server_id}:oauth_client_secret") == (
        "client-secret"
    )

    hydrated = json.loads(load_settings()["mcp_servers"])
    assert hydrated[0]["id"] == server_id
    assert hydrated[0]["oauth_client_secret"] == "client-secret"


def test_mcp_oauth_client_secret_legacy_plaintext_is_migrated(secure_store):
    servers = [
        {
            "name": "srv",
            "transport": "streamable_http",
            "auth": "oauth2",
            "url": "https://example.test/mcp",
            "oauth_client_secret": "legacy-client-secret",
        }
    ]
    qs = QSettings()
    qs.setValue("room/mcp_servers", json.dumps(servers))

    hydrated = json.loads(load_settings()["mcp_servers"])
    sanitized = json.loads(qs.value("room/mcp_servers"))

    assert hydrated[0]["oauth_client_secret"] == "legacy-client-secret"
    assert sanitized[0]["oauth_client_secret"] == ""
    assert (
        secure_store.get_secret(f"mcp_server:{sanitized[0]['id']}:oauth_client_secret")
        == "legacy-client-secret"
    )


def test_mcp_env_secrets_are_sanitized_and_hydrated(secure_store):
    servers = [
        {
            "name": "srv",
            "transport": "stdio",
            "command": "server",
            "env": "OPENAI_API_KEY=sk-test\nPLAIN=value\nMONKEY=banana",
        }
    ]

    save_settings({"mcp_servers": json.dumps(servers)})

    qs = QSettings()
    stored = json.loads(qs.value("room/mcp_servers"))
    server_id = stored[0]["id"]
    assert stored[0]["env"] == "OPENAI_API_KEY=\nPLAIN=value\nMONKEY=banana"
    assert secure_store.get_secret(f"mcp_server:{server_id}:env:OPENAI_API_KEY") == "sk-test"

    hydrated = json.loads(load_settings()["mcp_servers"])
    assert hydrated[0]["env"] == "OPENAI_API_KEY=sk-test\nPLAIN=value\nMONKEY=banana"


def test_mcp_env_legacy_plaintext_is_migrated(secure_store):
    servers = [
        {
            "name": "srv",
            "transport": "stdio",
            "command": "server",
            "env": "GITHUB_TOKEN=legacy-token\nDEBUG=true",
        }
    ]
    qs = QSettings()
    qs.setValue("room/mcp_servers", json.dumps(servers))

    hydrated = json.loads(load_settings()["mcp_servers"])
    sanitized = json.loads(qs.value("room/mcp_servers"))

    assert hydrated[0]["env"] == "GITHUB_TOKEN=legacy-token\nDEBUG=true"
    assert sanitized[0]["env"] == "GITHUB_TOKEN=\nDEBUG=true"
    assert secure_store.get_secret(f"mcp_server:{sanitized[0]['id']}:env:GITHUB_TOKEN") == (
        "legacy-token"
    )


def test_mcp_secret_store_entries_migrate_from_server_name_to_id(secure_store):
    secure_store.set_secret("mcp_server:srv:oauth_client_secret", "old-secret")
    secure_store.set_secret("mcp_oauth:srv:tokens", '{"access_token":"old-token"}')
    servers = [
        {
            "name": "srv",
            "transport": "streamable_http",
            "auth": "oauth2",
            "url": "https://example.test/mcp",
            "oauth_client_secret": "",
        }
    ]
    qs = QSettings()
    qs.setValue("room/mcp_servers", json.dumps(servers))

    hydrated = json.loads(load_settings()["mcp_servers"])
    server_id = hydrated[0]["id"]

    assert hydrated[0]["oauth_client_secret"] == "old-secret"
    assert secure_store.get_secret(f"mcp_server:{server_id}:oauth_client_secret") == "old-secret"
    assert secure_store.get_secret("mcp_server:srv:oauth_client_secret") == ""
    assert secure_store.get_secret(f"mcp_oauth:{server_id}:tokens") == (
        '{"access_token":"old-token"}'
    )
    assert secure_store.get_secret("mcp_oauth:srv:tokens") == ""
