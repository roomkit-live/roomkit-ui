"""Secure secret storage with a QSettings fallback.

The primary backend is the platform keyring exposed by the ``keyring``
package: macOS Keychain, Windows Credential Manager, or Linux Secret Service
when available.  If no keyring backend is usable, values fall back to QSettings
under an encoded namespace so callers can keep using one API.
"""

from __future__ import annotations

import base64
import importlib
import logging
from typing import Any

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

_DEFAULT_SERVICE = "RoomKit UI"
_DEFAULT_NAMESPACE = "roomkit-ui"
_FALLBACK_PREFIX = "room/secrets"
_DEFAULT_KEYRING = object()


class SecretStore:
    """Store secrets in the OS keyring, falling back to QSettings when needed."""

    def __init__(
        self,
        *,
        service: str = _DEFAULT_SERVICE,
        namespace: str = _DEFAULT_NAMESPACE,
        qsettings: QSettings | None = None,
        keyring_backend: Any = _DEFAULT_KEYRING,
    ) -> None:
        self._service = service
        self._namespace = namespace
        self._qs = qsettings or QSettings()
        self._keyring = _load_keyring() if keyring_backend is _DEFAULT_KEYRING else keyring_backend
        self._fallback_reason: str | None = None
        if self._keyring is None:
            self._fallback_reason = "keyring package is unavailable"

    @property
    def is_secure(self) -> bool:
        """Return True while the keyring backend is available and has not failed."""
        return self._keyring is not None and self._fallback_reason is None

    @property
    def backend_name(self) -> str:
        """Return the active storage family: ``keyring`` or ``qsettings``."""
        return "keyring" if self.is_secure else "qsettings"

    @property
    def fallback_reason(self) -> str | None:
        """Return why QSettings fallback is active, if known."""
        return self._fallback_reason

    def get_secret(self, name: str, default: str = "") -> str:
        """Return a stored secret or *default* when no value exists."""
        value = self._get_from_keyring(name)
        if value is not None:
            return value

        fallback = self._qs.value(self._fallback_key(name), None)
        if fallback is None:
            return default
        return str(fallback)

    def set_secret(self, name: str, value: str) -> None:
        """Store *value* for *name*.

        Empty strings are valid values.  Call :meth:`delete_secret` to remove a
        secret.
        """
        if self._set_in_keyring(name, value):
            self._qs.remove(self._fallback_key(name))
            self._qs.sync()
            return

        self._qs.setValue(self._fallback_key(name), value)
        self._qs.sync()
        logger.warning("Secret %r stored in QSettings fallback: %s", name, self._fallback_reason)

    def delete_secret(self, name: str) -> None:
        """Remove *name* from both keyring and fallback storage."""
        self._delete_from_keyring(name)
        self._qs.remove(self._fallback_key(name))
        self._qs.sync()

    def _account(self, name: str) -> str:
        return f"{self._namespace}:{name}"

    def _fallback_key(self, name: str) -> str:
        raw = self._account(name).encode("utf-8")
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"{_FALLBACK_PREFIX}/{token}"

    def _get_from_keyring(self, name: str) -> str | None:
        if self._keyring is None:
            return None
        try:
            value = self._keyring.get_password(self._service, self._account(name))
        except Exception as exc:
            self._mark_fallback(exc)
            return None
        return str(value) if value is not None else None

    def _set_in_keyring(self, name: str, value: str) -> bool:
        if self._keyring is None:
            return False
        try:
            self._keyring.set_password(self._service, self._account(name), value)
        except Exception as exc:
            self._mark_fallback(exc)
            return False
        self._fallback_reason = None
        return True

    def _delete_from_keyring(self, name: str) -> None:
        if self._keyring is None:
            return
        try:
            self._keyring.delete_password(self._service, self._account(name))
        except Exception as exc:
            logger.debug("SecretStore keyring delete failed for %r: %s", name, exc)

    def _mark_fallback(self, exc: Exception) -> None:
        self._fallback_reason = f"{type(exc).__name__}: {exc}"
        logger.debug("SecretStore keyring backend unavailable", exc_info=True)


_default_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    """Return the process-wide default secret store."""
    global _default_store
    if _default_store is None:
        _default_store = SecretStore()
    return _default_store


def reset_secret_store_for_tests() -> None:
    """Clear the process-wide store singleton."""
    global _default_store
    _default_store = None


def set_secret_store_for_tests(store: SecretStore | None) -> None:
    """Replace the process-wide store singleton for tests."""
    global _default_store
    _default_store = store


def _load_keyring() -> Any | None:
    try:
        return importlib.import_module("keyring")
    except ImportError:
        return None
