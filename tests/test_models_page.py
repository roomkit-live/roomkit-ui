"""The AI Models page runs each download through one path: progress, then outcome."""

from __future__ import annotations

import asyncio

import shiboken6
from PySide6.QtWidgets import QWidget

from roomkit_ui.widgets.settings.models_page import _ModelsPage


class _Row:
    def __init__(self) -> None:
        self.states: list[object] = []

    def set_resolving(self) -> None:
        self.states.append("resolving")

    def set_downloading(self, pct: int) -> None:
        self.states.append(pct)

    def set_downloaded(self) -> None:
        self.states.append("downloaded")

    def set_error(self) -> None:
        self.states.append("error")


async def _drain() -> None:
    # The download's worker thread, then the callbacks it scheduled.
    for _ in range(20):
        await asyncio.sleep(0.01)


async def test_a_download_reports_progress_then_success(qapp):
    page = _ModelsPage({})
    row = _Row()

    async def download(progress):
        # Real downloads report from their worker thread.
        await asyncio.to_thread(progress, 50, 100)

    page._start_download(row, download, "Test model")
    await _drain()

    assert row.states == ["resolving", 50, "downloaded"]
    page.deleteLater()


async def test_a_failed_download_marks_the_row(qapp):
    page = _ModelsPage({})
    row = _Row()

    async def download(_progress):
        raise OSError("connection reset")

    page._start_download(row, download, "Test model")
    await _drain()

    assert row.states == ["resolving", "error"]
    page.deleteLater()


class _WidgetRow(QWidget):
    """A real widget, so it can be destroyed with the dialog mid-download.

    Each state touches the C++ side, as _ModelRow's labels and buttons do.
    """

    def _show(self, state: object) -> None:
        self.setToolTip(str(state))

    def set_resolving(self) -> None:
        self._show("resolving")

    def set_downloading(self, pct: int) -> None:
        self._show(pct)

    def set_downloaded(self) -> None:
        self._show("downloaded")

    def set_error(self) -> None:
        self._show("error")


async def test_a_download_outliving_the_dialog_leaves_its_row_alone(qapp, caplog):
    # Closing Settings destroys the page and its rows; the download goes on.
    page = _ModelsPage({})
    row = _WidgetRow()
    gate = asyncio.Event()
    loop_errors: list[dict] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))

    async def download(progress):
        await gate.wait()
        await asyncio.to_thread(progress, 100, 100)

    page._start_download(row, download, "Test model")
    shiboken6.delete(row)
    gate.set()
    await _drain()
    loop.set_exception_handler(None)

    assert loop_errors == []  # no progress report on the dead row
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    page.deleteLater()
