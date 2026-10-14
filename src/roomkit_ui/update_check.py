"""When to look for a newer RoomKit UI, and the update that follows.

One object for the app (:func:`update_service`), like the installer: the
About page and the notice on the home screen follow it.  It checks shortly
after startup, then at most once a day (``update_checked_at``), never in a
source checkout and never once the user turned it off (``update_check``,
the About page's).  Offline, or on any error, it says nothing: a line in the
log, no traceback.  What it found stays in settings (``update_latest``, with
the endpoint's ETag), so a restart within the day still knows; a version the
user dismissed (``update_dismissed``) keeps the notice quiet until a newer
one.  The update itself runs on the app's one installer, never under an open
session: it replaces the code that session runs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from roomkit_ui import updates
from roomkit_ui.component_installer import installer
from roomkit_ui.components import Installer, InstallPlan
from roomkit_ui.install_env import InstallKind, install_kind
from roomkit_ui.settings import load_setting, save_settings

logger = logging.getLogger(__name__)

STARTUP_DELAY_MS = 8_000  # past the window, the tray and the wake word
LOOK_AGAIN_MS = 3 * 60 * 60 * 1000  # an app left open for days still checks; the day gate decides
CHECK_EVERY = 24 * 60 * 60  # seconds

Fetch = Callable[[InstallKind, str], Awaitable[updates.LatestRelease]]


class UpdateService(QObject):
    """The update check's schedule, what it found, and the update it offers."""

    changed = Signal()  # what is known, dismissed or allowed changed

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        kind: InstallKind | None = None,
        current: str | None = None,
        fetch: Fetch = updates.fetch_latest,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(parent)
        self.kind = kind or install_kind()
        self.current = updates.current_version() if current is None else current
        self._fetch = fetch
        self._clock = clock
        self._task: asyncio.Future | None = None
        self._session_open = False
        self.error = ""  # why the last check failed
        self._timer = QTimer(self)
        self._timer.setInterval(LOOK_AGAIN_MS)
        self._timer.timeout.connect(self.check_if_due)

    def start(self) -> None:
        """Check soon, then keep an eye out while the app stays open."""
        if self.kind is InstallKind.CHECKOUT:
            return  # it moves with git: nothing to offer
        if self.notice:
            self.changed.emit()  # a check earlier today found it
        QTimer.singleShot(STARTUP_DELAY_MS, self, self.check_if_due)
        self._timer.start()

    @property
    def latest(self) -> str:
        """A release newer than the running app, or ""."""
        latest = str(load_setting("update_latest") or "")
        return latest if updates.is_newer(latest, self.current) else ""

    @property
    def notice(self) -> str:
        """The release the home screen offers: newer, and not dismissed."""
        latest = self.latest
        return latest if latest and latest != load_setting("update_dismissed") else ""

    def due(self) -> bool:
        """Whether a check may run now: switched on, not a checkout, not today."""
        if self.kind is InstallKind.CHECKOUT or not load_setting("update_check"):
            return False
        return self._clock() - _seconds(load_setting("update_checked_at")) >= CHECK_EVERY

    @property
    def checking(self) -> bool:
        return self._task is not None

    @property
    def checked(self) -> bool:
        """Whether a check ever answered."""
        return _seconds(load_setting("update_checked_at")) > 0

    def check_if_due(self) -> bool:
        """Start a check in the background when one is due."""
        if not self.due():
            return False
        return self.check_now()

    def check_now(self) -> bool:
        """Start a check in the background (the About page's Check now)."""
        if self._task is not None:
            return False
        self._task = asyncio.ensure_future(self.check())
        self.changed.emit()
        return True

    async def check(self) -> None:
        """Ask the release endpoint, remember the answer.  A failure is no
        notice: a log line, and ``error`` for the About page."""
        try:
            found = await self._fetch(self.kind, str(load_setting("update_etag") or ""))
        except Exception as exc:  # offline, a timeout, a server or JSON error
            self.error = str(exc) or type(exc).__name__
            logger.info("Update check failed: %s", self.error)
            return
        else:
            self.error = ""
            values = {"update_checked_at": str(int(self._clock()))}
            if not found.unchanged:
                values |= {"update_latest": found.version or "", "update_etag": found.etag}
            save_settings(values)
            logger.info("Update check: newer %s, running %s", self.latest or "none", self.current)
        finally:
            self._task = None
            self.changed.emit()

    def dismiss(self) -> None:
        """Keep the home screen quiet about this release."""
        save_settings({"update_dismissed": self.latest})
        self.changed.emit()

    def set_session_open(self, session_open: bool) -> None:
        if session_open != self._session_open:
            self._session_open = session_open
            self.changed.emit()

    def plan(self) -> InstallPlan:
        return updates.update_plan(self.kind)

    def run_update(self) -> str:
        """Start the update; "" once it runs, else why it did not."""
        if self._session_open:
            return "End the session first: the update replaces the code it runs."
        plan = self.plan()
        if plan.how is not Installer.APP:
            return plan.note
        if not installer().update(plan):
            return "Another installation is running: try again once it ends."
        return ""


def _seconds(value: object) -> float:
    try:
        return float(str(value))
    except ValueError:
        return 0.0


_service: UpdateService | None = None


def update_service() -> UpdateService:
    """The app's one update service, owned by the application."""
    global _service
    if _service is None:
        _service = UpdateService(QCoreApplication.instance())
    return _service
