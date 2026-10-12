"""Where settings secrets live: the OS keyring, never plain QSettings.

API keys (``settings._SECRET_KEYS``), MCP server OAuth client secrets, the
header values of MCP HTTP servers, and the env values of MCP servers and CLI
tools that look like credentials (``_is_env_secret``) are stored through
``SecretStore``.  ``hydrate_*`` fills
them back into the JSON the settings page edits; ``sanitize_*`` strips them
out before the JSON reaches QSettings, migrating plaintext left by older
versions on the way.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import QSettings

from roomkit_ui.mcp_config import header_line, split_header_line
from roomkit_ui.secret_store import SecretStore

_MCP_SERVER_SECRET_FIELDS = ("oauth_client_secret",)
# Words of an env var name (split on non-alphanumerics) that mark its value as
# a credential, for MCP servers and CLI tools alike. A value is also a secret
# when it is a URL carrying credentials, whatever the name (_is_env_secret).
_ENV_SECRET_MARKERS = frozenset(
    {
        "APIKEY",
        "AUTH",
        "BEARER",
        "CREDENTIAL",
        "CREDENTIALS",
        "DSN",
        "KEY",
        "PASS",
        "PASSPHRASE",
        "PASSWD",
        "PASSWORD",
        "PAT",
        "PWD",
        "SECRET",
        "TOKEN",
    }
)
_MCP_OAUTH_SECRET_SUFFIXES = ("tokens", "client_info")


def _settings_secret_name(key: str) -> str:
    return f"settings:{key}"


def _mcp_server_secret_name(server_id: str, field: str) -> str:
    return f"mcp_server:{server_id}:{field}"


def _mcp_server_env_secret_name(server_id: str, key: str) -> str:
    return f"mcp_server:{server_id}:env:{key}"


def _mcp_server_env_legacy_names(legacy_ids: list[str], key: str) -> list[str]:
    return [_mcp_server_env_secret_name(old_id, key) for old_id in legacy_ids]


def _mcp_server_header_secret_name(server_id: str, name: str) -> str:
    # Header names are case-insensitive: "authorization" is the same header.
    return f"mcp_server:{server_id}:header:{name.lower()}"


def _cli_tool_env_secret_name(tool_id: str, key: str) -> str:
    return f"cli_tool:{tool_id}:env:{key}"


def _mcp_oauth_secret_name(server_id: str, suffix: str) -> str:
    return f"mcp_oauth:{server_id}:{suffix}"


def _ensure_entry_id(entry: dict[str, Any]) -> tuple[str, bool]:
    """Return the stable id of an MCP server / CLI tool, minting one if absent."""
    entry_id = str(entry.get("id", "") or "").strip()
    if entry_id:
        return entry_id, False
    entry_id = uuid.uuid4().hex
    entry["id"] = entry_id
    return entry_id, True


def _legacy_server_identities(server_id: str, server_name: str) -> list[str]:
    legacy: list[str] = []
    if server_name and server_name != server_id:
        legacy.append(server_name)
    return legacy


def _is_env_secret(key: str, value: str = "") -> bool:
    """Whether an env line holds a credential — by its name, or by its value."""
    parts = {part for part in re.split(r"[^A-Z0-9]+", key.upper()) if part}
    if parts & _ENV_SECRET_MARKERS:
        return True
    if "DATABASE" in parts and parts & {"URL", "URI"}:
        return True
    return _url_has_credentials(value)


def _url_has_credentials(value: str) -> bool:
    """``scheme://user:password@host`` (or a token as the user) is a secret."""
    try:
        split = urlsplit(value.strip())
    except ValueError:
        return False
    return bool(split.scheme and split.netloc and (split.username or split.password))


def _get_secret_with_legacy(
    store: SecretStore,
    secret_name: str,
    legacy_names: list[str],
) -> str:
    stored = store.get_secret(secret_name, "")
    if stored:
        return stored
    for legacy_name in legacy_names:
        legacy_value = store.get_secret(legacy_name, "")
        if legacy_value:
            store.set_secret(secret_name, legacy_value)
            store.delete_secret(legacy_name)
            return legacy_value
    return ""


def _hydrate_env(
    raw: Any,
    store: SecretStore,
    secret_name: Callable[[str], str],
    legacy_names: Callable[[str], list[str]] = lambda _key: [],
) -> tuple[str, bool]:
    """Fill an env block's secret values back in from *store*.

    A secret is stored as ``KEY=`` in QSettings, so every empty value is
    looked up — the name alone cannot say which ones were secrets, since a
    URL carrying a password is one whatever it is called. A secret still in
    plain text is moved to *store*; the returned flag says one was.
    """
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or ""), False

    migrated = False
    out: list[str] = []
    for line in raw.splitlines():
        if "=" not in line:
            out.append(line)
            continue
        key, value = line.split("=", 1)
        env_key, value_text = key.strip(), value.strip()
        if not env_key or (value_text and not _is_env_secret(env_key, value_text)):
            out.append(line)
            continue

        name = secret_name(env_key)
        stored = _get_secret_with_legacy(store, name, legacy_names(env_key))
        if value_text:
            if not stored:
                store.set_secret(name, value_text)
            migrated = True
        elif stored:
            value_text = stored

        out.append(f"{env_key}={value_text}")
    return "\n".join(out), migrated


def _sanitize_env(
    raw: Any, store: SecretStore, secret_name: Callable[[str], str], *, persist: bool
) -> str:
    """Strip an env block's secret values, moving them to *store* if *persist*.

    An emptied value deletes its stored secret, or loading would bring the
    old one back (``_hydrate_env`` fills every empty value it can).
    """
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or "")

    out: list[str] = []
    for line in raw.splitlines():
        if "=" not in line:
            out.append(line)
            continue
        key, value = line.split("=", 1)
        env_key, value_text = key.strip(), value.strip()
        if not env_key or (value_text and not _is_env_secret(env_key, value_text)):
            out.append(line)
            continue

        if persist:
            if value_text:
                store.set_secret(secret_name(env_key), value_text)
            else:
                store.delete_secret(secret_name(env_key))
        out.append(f"{env_key}=")
    return "\n".join(out)


def _hydrate_headers(
    raw: Any, store: SecretStore, secret_name: Callable[[str], str]
) -> tuple[str, bool]:
    """Fill a headers block's values back in from *store*.

    Every value is a secret: what an MCP server is sent besides its requests
    is nearly always its credential (``Authorization``, an API key). A value
    still in plain text is moved to *store*; the returned flag says one was.
    """
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or ""), False

    migrated = False
    out: list[str] = []
    for line in raw.splitlines():
        pair = split_header_line(line)
        if pair is None:
            out.append(line)
            continue
        name, value = pair
        stored = store.get_secret(secret_name(name), "")
        if value:
            if not stored:
                store.set_secret(secret_name(name), value)
            migrated = True
        elif stored:
            value = stored
        out.append(header_line(name, value))
    return "\n".join(out), migrated


def _sanitize_headers(
    raw: Any, store: SecretStore, secret_name: Callable[[str], str], *, persist: bool
) -> str:
    """Strip a headers block's values, moving them to *store* if *persist*.

    An emptied value deletes its stored secret, or loading would bring it back.
    """
    if persist and not any(
        pair is not None and pair[0].lower() == "authorization"
        for pair in (split_header_line(line) for line in str(raw or "").splitlines())
    ):
        # Selecting None/OAuth removes the manual credential, including its
        # stored value, so a subsequently empty header cannot resurrect it.
        store.delete_secret(secret_name("Authorization"))
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or "")

    out: list[str] = []
    for line in raw.splitlines():
        pair = split_header_line(line)
        if pair is None:
            out.append(line)
            continue
        name, value = pair
        if persist:
            if value:
                store.set_secret(secret_name(name), value)
            else:
                store.delete_secret(secret_name(name))
        out.append(header_line(name, ""))
    return "\n".join(out)


def load_secret_setting(qs: QSettings, store: SecretStore, key: str) -> str:
    """Load a setting-backed secret and migrate any legacy plaintext value."""
    legacy_key = f"room/{key}"
    raw = qs.value(legacy_key, None)
    secret_name = _settings_secret_name(key)
    stored = store.get_secret(secret_name, "")

    if raw is not None:
        raw_value = str(raw)
        if raw_value and not stored:
            store.set_secret(secret_name, raw_value)
            stored = raw_value
        qs.remove(legacy_key)
        qs.sync()
    return stored


def save_secret_setting(qs: QSettings, store: SecretStore, key: str, value: Any) -> None:
    """Persist a secret in SecretStore and remove any plaintext QSettings copy."""
    secret_name = _settings_secret_name(key)
    text = "" if value is None else str(value)
    if text:
        store.set_secret(secret_name, text)
    else:
        store.delete_secret(secret_name)
    qs.remove(f"room/{key}")


def _parse_json_list(raw: Any) -> list[Any] | None:
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, list) else None


def hydrate_mcp_server_secrets(raw: Any, qs: QSettings, store: SecretStore) -> Any:
    """Return mcp_servers JSON with secrets filled from SecretStore.

    Legacy plaintext secrets are migrated out of QSettings as a side effect.
    The returned JSON still contains the secret values so existing UI and
    connection code can keep consuming one settings dict.
    """
    servers = _parse_json_list(raw)
    if servers is None:
        return raw

    migrated = False
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id, created_id = _ensure_entry_id(server)
        migrated = migrated or created_id
        server_name = str(server.get("name", "")).strip()
        legacy_ids = _legacy_server_identities(server_id, server_name)
        for field in _MCP_SERVER_SECRET_FIELDS:
            secret_name = _mcp_server_secret_name(server_id, field)
            legacy_names = [_mcp_server_secret_name(old_id, field) for old_id in legacy_ids]
            legacy_value = str(server.get(field, "") or "")
            stored = _get_secret_with_legacy(store, secret_name, legacy_names)
            if legacy_value:
                if not stored:
                    store.set_secret(secret_name, legacy_value)
                    stored = legacy_value
                server[field] = stored
                migrated = True
            elif stored:
                server[field] = stored
        hydrated_env, env_migrated = _hydrate_env(
            server.get("env", ""),
            store,
            partial(_mcp_server_env_secret_name, server_id),
            partial(_mcp_server_env_legacy_names, legacy_ids),
        )
        if hydrated_env != server.get("env", ""):
            server["env"] = hydrated_env
        migrated = migrated or env_migrated
        hydrated_headers, headers_migrated = _hydrate_headers(
            server.get("headers", ""),
            store,
            partial(_mcp_server_header_secret_name, server_id),
        )
        if hydrated_headers != server.get("headers", ""):
            server["headers"] = hydrated_headers
        migrated = migrated or headers_migrated

        for suffix in _MCP_OAUTH_SECRET_SUFFIXES:
            secret_name = _mcp_oauth_secret_name(server_id, suffix)
            legacy_names = [_mcp_oauth_secret_name(old_id, suffix) for old_id in legacy_ids]
            if _get_secret_with_legacy(store, secret_name, legacy_names):
                migrated = True

    if migrated:
        sanitized = sanitize_mcp_servers(json.dumps(servers), store, persist=False)
        qs.setValue("room/mcp_servers", sanitized)
        qs.sync()
    return json.dumps(servers)


def sanitize_mcp_servers(raw: Any, store: SecretStore, *, persist: bool) -> Any:
    """Move MCP server secrets into SecretStore and return sanitized JSON."""
    servers = _parse_json_list(raw)
    if servers is None:
        return raw

    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id, _created_id = _ensure_entry_id(server)
        if "env" in server:
            server["env"] = _sanitize_env(
                server.get("env", ""),
                store,
                partial(_mcp_server_env_secret_name, server_id),
                persist=persist,
            )
        if "headers" in server:
            server["headers"] = _sanitize_headers(
                server.get("headers", ""),
                store,
                partial(_mcp_server_header_secret_name, server_id),
                persist=persist,
            )
        for field in _MCP_SERVER_SECRET_FIELDS:
            if field not in server:
                continue
            secret_name = _mcp_server_secret_name(server_id, field)
            value = str(server.get(field, "") or "")
            if persist:
                if value:
                    store.set_secret(secret_name, value)
                else:
                    store.delete_secret(secret_name)
            server[field] = ""
    return json.dumps(servers)


def hydrate_cli_tool_secrets(raw: Any, qs: QSettings, store: SecretStore) -> Any:
    """Return cli_tools JSON with env secrets filled from SecretStore.

    Same contract as ``hydrate_mcp_server_secrets``: plaintext secrets left
    by an older version are moved out of QSettings on the way.
    """
    tools = _parse_json_list(raw)
    if tools is None:
        return raw

    migrated = False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_id, created_id = _ensure_entry_id(tool)
        env, env_migrated = _hydrate_env(
            tool.get("env", ""), store, partial(_cli_tool_env_secret_name, tool_id)
        )
        if env != tool.get("env", ""):
            tool["env"] = env
        migrated = migrated or created_id or env_migrated

    if migrated:
        qs.setValue("room/cli_tools", sanitize_cli_tools(json.dumps(tools), store, persist=False))
        qs.sync()
    return json.dumps(tools)


def sanitize_cli_tools(raw: Any, store: SecretStore, *, persist: bool) -> Any:
    """Move CLI tool env secrets into SecretStore and return sanitized JSON."""
    tools = _parse_json_list(raw)
    if tools is None:
        return raw

    for tool in tools:
        if not isinstance(tool, dict) or "env" not in tool:
            continue
        tool_id, _created_id = _ensure_entry_id(tool)
        tool["env"] = _sanitize_env(
            tool.get("env", ""),
            store,
            partial(_cli_tool_env_secret_name, tool_id),
            persist=persist,
        )
    return json.dumps(tools)
