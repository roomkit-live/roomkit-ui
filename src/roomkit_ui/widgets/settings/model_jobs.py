"""Download progress owned by the application, shared by Settings instances."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from roomkit_ui.widgets.settings.model_library import LibraryModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadState:
    phase: str
    percent: int = 0
    error: str = ""


class ModelDownloads(QObject):
    changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.states: dict[str, DownloadState] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, model: LibraryModel) -> None:
        if model.id in self._tasks:
            return
        loop = asyncio.get_event_loop()
        self.states[model.id] = DownloadState("resolving")
        self._tasks[model.id] = loop.create_task(self._run(model))
        self._notify(model.id)

    def clear(self, model_id: str) -> None:
        if model_id not in self._tasks:
            self.states.pop(model_id, None)
            self._notify(model_id)

    def _notify(self, model_id: str) -> None:
        try:
            self.changed.emit(model_id)
        except RuntimeError:
            pass  # QApplication may have been destroyed during shutdown.

    async def _run(self, model: LibraryModel) -> None:
        loop = asyncio.get_running_loop()
        finished = False

        def show_progress(done: int, total: int) -> None:
            # A worker's final callback can arrive after its outcome, or a retry.
            if finished:
                return
            phase = "downloading" if total > 0 else "resolving"
            percent = max(0, min(int(done * 100 / total), 100)) if total > 0 else 0
            self.states[model.id] = DownloadState(phase, percent)
            self._notify(model.id)

        def progress(done: int, total: int) -> None:
            loop.call_soon_threadsafe(show_progress, done, total)

        try:
            await model.download(progress)
        except asyncio.CancelledError:
            self.states.pop(model.id, None)
            raise
        except Exception as exc:
            logger.exception("%s download failed", model.name)
            self.states[model.id] = DownloadState("error", error=str(exc))
        else:
            self.states.pop(model.id, None)
        finally:
            finished = True
            self._tasks.pop(model.id, None)
            self._notify(model.id)


def model_downloads() -> ModelDownloads:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Model downloads require a QApplication")
    runner = getattr(app, "_roomkit_model_downloads", None)
    if runner is None:
        runner = ModelDownloads(app)
        app._roomkit_model_downloads = runner
    return runner
