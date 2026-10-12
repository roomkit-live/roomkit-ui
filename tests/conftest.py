"""Shared fixtures: isolated QSettings so tests never touch real user config."""

import pytest
from PySide6.QtCore import QCoreApplication, QSettings

from roomkit_ui.secret_store import (
    SecretStore,
    reset_secret_store_for_tests,
    set_secret_store_for_tests,
)


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path, monkeypatch):
    """Point QSettings at a per-test temp ini file under a test-only org name."""
    monkeypatch.setattr(
        "roomkit_ui.memory.conversations_db_path", lambda: tmp_path / "conversations.db"
    )
    QCoreApplication.setOrganizationName("RoomKitUI-Tests")
    QCoreApplication.setApplicationName("RoomKitUI-Tests")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    set_secret_store_for_tests(SecretStore(keyring_backend=None))
    yield
    reset_secret_store_for_tests()


class InlineJobs:
    """A wake-word job runner that runs each job at once, on the caller's thread.

    Keeps tests about *what* the listener and enroller decide synchronous;
    tests about *where* the work runs use the real SerialWorker.
    """

    def submit(self, job, on_done, on_error=None) -> None:
        try:
            result = job()
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
            return
        on_done(result)

    def shutdown(self) -> None:
        pass


@pytest.fixture
def inline_jobs():
    return InlineJobs()
