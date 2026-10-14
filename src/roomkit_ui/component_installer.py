"""Install a component, or update the app, while it runs: one at a time, for the whole app.

The install outlives whatever asked for it — the Settings dialog is destroyed
on close, a chat line scrolls away — so the runner is one object for the app
(:func:`installer`), and pages subscribe to it: one opened mid-install shows
the output so far (``log``).  It runs the argv of an
:class:`~roomkit_ui.components.InstallPlan` as a child process, never through
a shell, and only for a plan the app runs itself (``Installer.APP``).  An
update (``updates.update_plan``) runs the same way, under the key
:data:`UPDATE` where an install has its component's extra.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QProcessEnvironment, Signal

from roomkit_ui import env_extras, features
from roomkit_ui.components import Component, Installer, InstallPlan, install_plan
from roomkit_ui.features import DISTRIBUTION
from roomkit_ui.updates import current_version

logger = logging.getLogger(__name__)

_LOG_LINES = 400  # what a page opened mid-install can still show

UPDATE = DISTRIBUTION  # the key an update runs under, where an install has its extra


class ComponentInstaller(QObject):
    """Runs one component install (or app update) at a time and reports how it went."""

    started = Signal(str)  # extra, or UPDATE
    output = Signal(str)  # one line of the installer's output
    finished = Signal(str, bool, str)  # extra (or UPDATE), installed, what the user is told

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._key = ""  # the running (or last) job: an extra, or UPDATE
        self._component: Component | None = None
        self._log: list[str] = []
        self._pending = ""
        self._cancelled = False
        self._version_before = ""  # the version on disk when the update started
        self.last_result: tuple[str, bool, str] | None = None  # the last component install
        self.last_update: tuple[bool, str] | None = None  # updated, what the user is told

    @property
    def running(self) -> Component | None:
        """The component being installed, or None."""
        return self._component if self._process is not None else None

    @property
    def busy(self) -> bool:
        """Whether an install or an update runs: no other job can start."""
        return self._process is not None

    @property
    def current(self) -> str:
        """The running (or last) job's key: a component's extra, or UPDATE."""
        return self._key

    def log(self) -> list[str]:
        """The running (or last) job's output."""
        return list(self._log)

    def install(self, component: Component) -> bool:
        """Start installing *component*; False if a job runs already or the
        app does not install it here (a checkout, a frozen build)."""
        plan = install_plan(component)
        if self._process is not None or plan.how is not Installer.APP:
            return False
        self.last_result = None
        self._start(component.extra, component, plan)
        return True

    def update(self, plan: InstallPlan) -> bool:
        """Start updating the app with *plan*; False if a job runs already or
        the app does not run this plan (a command the user runs, a built app)."""
        if self._process is not None or plan.how is not Installer.APP:
            return False
        self.last_update = None
        self._version_before = current_version()
        self._start(UPDATE, None, plan)
        return True

    def _start(self, key: str, component: Component | None, plan: InstallPlan) -> None:
        self._key, self._component, self._log, self._pending = key, component, [], ""
        self._cancelled = False
        process = QProcess(self)
        process.setProgram(plan.argv[0])
        process.setArguments(list(plan.argv[1:]))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        # pip buffers what it prints into a pipe: the user would see it in bursts.
        env.insert("PYTHONUNBUFFERED", "1")
        for name, value in plan.env:
            env.insert(name, value)
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._done)
        process.errorOccurred.connect(self._failed_to_start)
        self._process = process
        logger.info("Running %s: %s", key, plan.command)
        self._line(f"$ {plan.command}")
        self.started.emit(key)
        process.start()

    def cancel(self) -> None:
        if self._process is not None:
            self._cancelled = True
            self._process.kill()

    def _read(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput().data())
        text = self._pending + data.decode("utf-8", errors="replace").replace("\r", "\n")
        *lines, self._pending = text.split("\n")
        for line in lines:
            if line.strip():
                self._line(line)

    def _line(self, line: str) -> None:
        self._log.append(line)
        del self._log[:-_LOG_LINES]
        self.output.emit(line)

    def _done(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        self._read()
        if self._pending.strip():
            self._line(self._pending)
        ok = status == QProcess.ExitStatus.NormalExit and exit_code == 0
        self._finish(ok, exit_code)

    def _failed_to_start(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self._line(f"Could not run the installer: {self._process.errorString()}")
            self._finish(False, -1)

    def _finish(self, ok: bool, exit_code: int) -> None:
        component = self._component
        process = self._process
        if process is None:
            return
        self._process = None
        process.deleteLater()
        features.refresh()
        env_extras.refresh()
        if component is None:
            self.last_update = self._update_outcome(ok, exit_code)
            logger.info("Update: %s", self.last_update[1])
            self.finished.emit(UPDATE, *self.last_update)
            return
        message = self._outcome(component, ok, exit_code)
        logger.info("Install of %s: %s", component.extra, message)
        self.last_result = (component.extra, ok and not self._cancelled, message)
        self.finished.emit(*self.last_result)

    def _last_line(self) -> str:
        return next((line for line in reversed(self._log) if line.strip()), "")

    def _outcome(self, component: Component, ok: bool, exit_code: int) -> str:
        if self._cancelled:
            return f"{component.title}: installation cancelled."
        if not ok:
            return f"Could not install {component.title} (exit {exit_code}): {self._last_line()}"
        if component.needs_restart or not component.installed():
            return f"{component.title} is installed: restart RoomKit UI to use it."
        return f"{component.title} is installed."

    def _update_outcome(self, ok: bool, exit_code: int) -> tuple[bool, str]:
        """Whether a new version is on disk, and what the user is told."""
        if self._cancelled:
            return False, "Update cancelled."
        if not ok:
            return False, f"Could not update RoomKit UI (exit {exit_code}): {self._last_line()}"
        # Read from disk, not from the running code: the update changed it.
        version = current_version()
        if version == self._version_before:
            return False, f"Nothing to update: RoomKit UI {version} is what this install takes."
        return True, f"RoomKit UI {version} is installed: restart RoomKit UI to use it."


_installer: ComponentInstaller | None = None


def busy_reason() -> str:
    """Why no session starts now: an install or an update is changing the code
    a session would run ("" when none is)."""
    runner = installer()
    if not runner.busy:
        return ""
    if runner.current == UPDATE:
        return "RoomKit UI is updating. Start again once the update is done."
    return "A component is being installed. Start again once it is done."


def installer() -> ComponentInstaller:
    """The app's one installer, owned by the application so it outlives dialogs."""
    global _installer
    if _installer is None:
        _installer = ComponentInstaller(QCoreApplication.instance())
    return _installer


def restart_app(app: QCoreApplication | None = None) -> None:
    """Quit, then start again with the same command line once this one is gone.

    Never while an install or an update runs: quitting kills it midway, and a
    `uv tool install` cut short can leave the environment half built.
    """
    if installer().busy:
        logger.warning("Restart refused: an install or an update is running")
        return
    app = app or QCoreApplication.instance()
    if app is None:
        return
    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    app.aboutToQuit.connect(lambda: QProcess.startDetached(argv[0], argv[1:]))
    app.quit()
