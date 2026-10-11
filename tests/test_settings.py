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
    save_settings({"provider": "openai", "stt_enabled": False, "diarization_enabled": True})
    out = load_settings()
    assert out["provider"] == "openai"
    assert out["stt_enabled"] is False
    assert out["diarization_enabled"] is True


@pytest.mark.parametrize(("legacy", "mode"), [(True, "immediate"), (False, "off")])
def test_barge_in_bool_migrates_to_a_mode(legacy, mode):
    QSettings().setValue("room/vc_interruption", legacy)

    assert load_settings()["vc_interruption_mode"] == mode
    assert not QSettings().contains("room/vc_interruption")
    assert load_settings()["vc_interruption_mode"] == mode  # stored, not recomputed


def test_a_saved_barge_in_mode_wins_over_the_legacy_bool():
    qs = QSettings()
    qs.setValue("room/vc_interruption", True)
    qs.setValue("room/vc_interruption_mode", "semantic")

    assert load_settings()["vc_interruption_mode"] == "semantic"
    assert not QSettings().contains("room/vc_interruption")


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


# -- CLI tool env secrets --------------------------------------------------


def _cli_tool(env: str, **extra) -> dict:
    return {"name": "gh", "command": "gh", "env": env, **extra}


def _stored_cli_tools() -> list[dict]:
    return json.loads(QSettings().value("room/cli_tools"))


def test_cli_tool_env_secrets_stay_out_of_qsettings_and_come_back(secure_store):
    save_settings({"cli_tools": json.dumps([_cli_tool("GH_TOKEN=ghp_x\nGH_PAGER=cat")])})

    stored = _stored_cli_tools()
    tool_id = stored[0]["id"]
    assert stored[0]["env"] == "GH_TOKEN=\nGH_PAGER=cat"
    assert "ghp_x" not in json.dumps(stored)
    assert secure_store.get_secret(f"cli_tool:{tool_id}:env:GH_TOKEN") == "ghp_x"

    hydrated = json.loads(load_settings()["cli_tools"])
    assert hydrated[0]["id"] == tool_id
    assert hydrated[0]["env"] == "GH_TOKEN=ghp_x\nGH_PAGER=cat"


def test_cli_tool_legacy_plaintext_env_secret_is_migrated(secure_store):
    QSettings().setValue("room/cli_tools", json.dumps([_cli_tool("GITHUB_PAT=legacy")]))

    hydrated = json.loads(load_settings()["cli_tools"])
    stored = _stored_cli_tools()

    assert hydrated[0]["env"] == "GITHUB_PAT=legacy"
    assert stored[0]["env"] == "GITHUB_PAT="
    assert secure_store.get_secret(f"cli_tool:{stored[0]['id']}:env:GITHUB_PAT") == "legacy"


@pytest.mark.parametrize(
    "line",
    [
        "OPENAI_APIKEY=sk-1",
        "GITHUB_PAT=ghp_1",
        "AUTH_BEARER=abc",
        "DB_PWD=hunter2",
        "DATABASE_URL=postgres://db.local/app",
        "SENTRY_DSN=https://k@o1.ingest.sentry.io/1",
        "UPSTREAM=https://user:hunter2@example.test/api",
        "REMOTE=https://ghp_token@github.com/org/repo.git",
    ],
)
def test_env_secret_detection_covers_names_and_urls_with_credentials(secure_store, line):
    save_settings({"cli_tools": json.dumps([_cli_tool(line)])})

    key, value = line.split("=", 1)
    assert _stored_cli_tools()[0]["env"] == f"{key}="
    assert json.loads(load_settings()["cli_tools"])[0]["env"] == line


@pytest.mark.parametrize("line", ["PATH_PREFIX=/opt", "API_URL=https://example.test", "X=1"])
def test_plain_env_values_stay_in_qsettings(secure_store, line):
    save_settings({"cli_tools": json.dumps([_cli_tool(line)])})

    assert _stored_cli_tools()[0]["env"] == line


def test_emptying_a_secret_env_value_does_not_bring_the_old_one_back(secure_store):
    tool = _cli_tool("UPSTREAM=https://user:pw@example.test", id="t1")
    save_settings({"cli_tools": json.dumps([tool])})

    save_settings({"cli_tools": json.dumps([{**tool, "env": "UPSTREAM="}])})

    assert json.loads(load_settings()["cli_tools"])[0]["env"] == "UPSTREAM="
    assert secure_store.get_secret("cli_tool:t1:env:UPSTREAM") == ""
