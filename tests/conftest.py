"""Shared fixtures: isolated QSettings so tests never touch real user config."""

import pytest
from PySide6.QtCore import QCoreApplication, QSettings

from roomkit_ui.secret_store import (
    SecretStore,
    reset_secret_store_for_tests,
    set_secret_store_for_tests,
)


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    """Point QSettings at a per-test temp ini file under a test-only org name."""
    QCoreApplication.setOrganizationName("RoomKitUI-Tests")
    QCoreApplication.setApplicationName("RoomKitUI-Tests")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    set_secret_store_for_tests(SecretStore(keyring_backend=None))
    yield
    reset_secret_store_for_tests()
