"""Shared fixtures: isolated QSettings so tests never touch real user config."""

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    """Point QSettings at a per-test temp ini file under a test-only org name."""
    QCoreApplication.setOrganizationName("RoomKitUI-Tests")
    QCoreApplication.setApplicationName("RoomKitUI-Tests")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    yield
