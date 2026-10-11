"""One download per model at a time, across Settings dialogs.

Module-level state on purpose: it has to outlive the dialog. Reopened
mid-download, the dialog shows the model as missing, and a second click used
to start another download writing into the same ``.part`` file. A second
caller now joins the download already running — its progress included —
and gets its outcome.

Leaf module: knows nothing about models, only about blocking functions whose
last parameter is a ``progress(done, total)`` callback.
"""

from __future__ import annotations

import functools
import inspect
import threading
from collections.abc import Callable
from typing import Any

ProgressCallback = Callable[[int, int], None]


class _Flight:
    """One running download and whoever waits on it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.error: BaseException | None = None
        self.listeners: list[ProgressCallback] = []
        self.last: tuple[int, int] | None = None

    def report(self, downloaded: int, total: int) -> None:
        self.last = (downloaded, total)
        for listener in list(self.listeners):
            listener(downloaded, total)


_flights: dict[tuple[Any, ...], _Flight] = {}
_flights_lock = threading.Lock()


def single_flight(fn: Callable[..., None]) -> Callable[..., None]:
    """Run *fn* once per argument set at a time; concurrent calls join it.

    *fn* takes its ids, then ``progress``. A joining call gets the progress
    reports from then on, returns when the running call does, and raises if
    it failed.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        progress = bound.arguments.pop("progress")
        ids = tuple(bound.arguments.values())
        key = (fn.__name__, *ids)
        with _flights_lock:
            flight = _flights.get(key)
            joining = flight is not None
            if flight is None:
                flight = _flights[key] = _Flight()
            if progress is not None:
                flight.listeners.append(progress)
        if joining:
            _join(flight, progress)
            return
        try:
            fn(*ids, flight.report)
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with _flights_lock:
                _flights.pop(key, None)
            flight.done.set()

    return wrapper


def _join(flight: _Flight, progress: ProgressCallback | None) -> None:
    last = flight.last
    if progress is not None and last is not None:
        progress(*last)
    flight.done.wait()
    if flight.error is not None:
        raise RuntimeError(f"download failed: {flight.error}") from flight.error
