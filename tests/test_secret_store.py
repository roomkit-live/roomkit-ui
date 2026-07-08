"""Tests for the OS-keyring secret store facade."""

import pytest
from PySide6.QtCore import QSettings

from roomkit_ui.secret_store import SecretStore, get_secret_store, reset_secret_store_for_tests


class _FakeKeyring:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        if self.fail:
            raise RuntimeError("backend unavailable")
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("backend unavailable")
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        if self.fail:
            raise RuntimeError("backend unavailable")
        self.values.pop((service, account), None)


@pytest.fixture(autouse=True)
def reset_default_store():
    reset_secret_store_for_tests()
    yield
    reset_secret_store_for_tests()


def test_keyring_backend_round_trip():
    keyring = _FakeKeyring()
    store = SecretStore(service="svc", namespace="ns", keyring_backend=keyring)

    store.set_secret("openai_api_key", "sk-test")

    assert store.backend_name == "keyring"
    assert store.is_secure is True
    assert store.get_secret("openai_api_key") == "sk-test"
    assert keyring.values == {("svc", "ns:openai_api_key"): "sk-test"}


def test_delete_removes_keyring_and_fallback_values():
    keyring = _FakeKeyring()
    store = SecretStore(service="svc", namespace="ns", keyring_backend=keyring)
    fallback_store = SecretStore(service="svc", namespace="ns", keyring_backend=None)
    fallback_store.set_secret("token", "fallback-copy")
    store.set_secret("token", "secure-copy")

    store.delete_secret("token")

    assert store.get_secret("token") == ""
    assert fallback_store.get_secret("token") == ""
    assert keyring.values == {}


def test_qsettings_fallback_when_keyring_is_unavailable():
    store = SecretStore(service="svc", namespace="ns", keyring_backend=None)

    store.set_secret("api/key with odd chars", "secret")

    assert store.backend_name == "qsettings"
    assert store.is_secure is False
    assert store.fallback_reason == "keyring package is unavailable"
    assert store.get_secret("api/key with odd chars") == "secret"
    assert store.get_secret("missing", default="fallback") == "fallback"


def test_qsettings_fallback_survives_new_store_instance():
    first = SecretStore(service="svc", namespace="ns", keyring_backend=None)
    first.set_secret("oauth/server/tokens", '{"access_token":"x"}')

    second = SecretStore(service="svc", namespace="ns", keyring_backend=None)

    assert second.get_secret("oauth/server/tokens") == '{"access_token":"x"}'


def test_keyring_failure_falls_back_to_qsettings():
    store = SecretStore(service="svc", namespace="ns", keyring_backend=_FakeKeyring(fail=True))

    store.set_secret("token", "value")

    assert store.backend_name == "qsettings"
    assert "RuntimeError" in str(store.fallback_reason)
    assert store.get_secret("token") == "value"


def test_successful_keyring_write_removes_stale_fallback():
    fallback_store = SecretStore(service="svc", namespace="ns", keyring_backend=None)
    fallback_store.set_secret("token", "old")

    store = SecretStore(service="svc", namespace="ns", keyring_backend=_FakeKeyring())
    store.set_secret("token", "new")

    assert store.get_secret("token") == "new"
    assert fallback_store.get_secret("token") == ""


def test_default_store_is_singleton():
    first = get_secret_store()
    second = get_secret_store()

    assert first is second


def test_fallback_keys_do_not_expose_secret_names():
    store = SecretStore(service="svc", namespace="ns", keyring_backend=None)
    store.set_secret("openai_api_key", "secret")

    keys = QSettings().allKeys()

    assert keys
    assert all("openai_api_key" not in key for key in keys)
