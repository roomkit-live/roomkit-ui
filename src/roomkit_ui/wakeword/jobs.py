"""Run the wake word's heavy work off the Qt thread, one job at a time.

Embedding a segment runs whisper's encoder and then a DTW per prototype in
pure Python — tens of milliseconds per utterance, more on a slow machine,
and every utterance heard while armed pays it.  On the Qt thread that is
a UI that stalls whenever anyone talks.

Jobs run in submission order on a single thread: the encoder must be
loaded before the first take is embedded, and results reach the UI in
the order the speech was heard.  Each result is handed back on the Qt
thread, through a queued signal, so receivers never see another thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Protocol

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

OnDone = Callable[[Any], None]
OnError = Callable[[Exception], None]


class JobRunner(Protocol):
    """Where wake-word work runs. Tests substitute one that runs inline."""

    def submit(
        self, job: Callable[[], Any], on_done: OnDone, on_error: OnError | None = None
    ) -> None: ...

    def shutdown(self) -> None: ...


class SerialWorker(QObject):
    """A single background thread whose results come back on the Qt thread."""

    # Emitted from the worker thread; the receiver lives on the Qt thread,
    # so Qt queues the call there.
    _finished = Signal(object)

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._executor: ThreadPoolExecutor | None = None
        # Bumped by shutdown(): a result from before it is no longer wanted.
        self._generation = 0
        self._finished.connect(self._deliver)

    def submit(
        self, job: Callable[[], Any], on_done: OnDone, on_error: OnError | None = None
    ) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=self._name)
        self._executor.submit(self._run, self._generation, job, on_done, on_error)

    def _run(
        self,
        generation: int,
        job: Callable[[], Any],
        on_done: OnDone,
        on_error: OnError | None,
    ) -> None:
        try:
            result = job()
        except Exception as exc:
            logger.exception("%s job failed", self._name)
            if on_error is not None:
                self._emit(generation, partial(on_error, exc))
            return
        self._emit(generation, partial(on_done, result))

    def _emit(self, generation: int, callback: Callable[[], None]) -> None:
        try:
            self._finished.emit((generation, callback))
        except RuntimeError:
            pass  # the owner was deleted while the job ran

    @Slot(object)
    def _deliver(self, payload: tuple[int, Callable[[], None]]) -> None:
        generation, callback = payload
        if generation == self._generation:
            callback()

    def shutdown(self) -> None:
        """Drop queued jobs and every result not yet delivered."""
        self._generation += 1
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
