"""MainWindow lifecycles: what must survive a teardown, and what must go."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from shiboken6 import isValid

import roomkit_ui.widgets.main_window as main_window_mod
from roomkit_ui.widgets.main_window import MainWindow
from roomkit_ui.widgets.settings import SettingsPanel


def _flush_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.deleteLater()
    _flush_deletes()


# -- Settings dialog -----------------------------------------------------------


def test_a_closed_settings_dialog_is_destroyed(window, monkeypatch):
    opened: list[SettingsPanel] = []

    class _ClosesAtOnce(SettingsPanel):
        def exec(self) -> int:
            opened.append(self)
            self.reject()
            return 0

    monkeypatch.setattr(main_window_mod, "SettingsPanel", _ClosesAtOnce)

    window._open_settings()
    _flush_deletes()

    assert len(opened) == 1
    assert not isValid(opened[0])
