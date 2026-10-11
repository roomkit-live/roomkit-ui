"""The AI Models page runs each download through one path: progress, then outcome."""

from __future__ import annotations

import asyncio

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
    for _ in range(5):
        await asyncio.sleep(0)


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
