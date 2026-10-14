"""Install a component while the app runs, one at a time, for the whole app.

The install outlives whatever asked for it — the Settings dialog is destroyed
on close, a chat line scrolls away — so the runner is one object for the app
(:func:`installer`), and pages subscribe to it: one opened mid-install shows
the output so far (``log``).  It runs the argv of the component's
:class:`~roomkit_ui.components.InstallPlan` as a child process, never through
a shell, and only for a plan the app runs itself (``Installer.APP``).
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QProcessEnvironment, Signal

from roomkit_ui import env_extras, features
from roomkit_ui.components import Component, Installer, install_plan

logger = logging.getLogger(__name__)

_LOG_LINES = 400  # what a page opened mid-install can still show


class ComponentInstaller(QObject):
    """Runs one component install at a time and reports how it went."""

    started = Signal(str)  # extra
    output = Signal(str)  # one line of the installer's output
    finished = Signal(str, bool, str)  # extra, installed, what the user is told

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._component: Component | None = None
        self._log: list[str] = []
        self._pending = ""
        self._cancelled = False
        self.last_result: tuple[str, bool, str] | None = None

    @property
    def running(self) -> Component | None:
        """The component being installed, or None."""
        return self._component if self._process is not None else None

    def log(self) -> list[str]:
        """The running (or last) install's output."""
        return list(self._log)

    def install(self, component: Component) -> bool:
        """Start installing *component*; False if one runs already or the
        app does not install it here (a checkout, a frozen build)."""
        plan = install_plan(component)
        if self._process is not None or plan.how is not Installer.APP:
            return False
        self._component, self._log, self._pending = component, [], ""
        self._cancelled = False
        self.last_result = None
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
        logger.info("Installing %s: %s", component.extra, plan.command)
        self._line(f"$ {plan.command}")
        self.started.emit(component.extra)
        process.start()
        return True

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
        if component is None or process is None:
            return
        self._process = None
        process.deleteLater()
        features.refresh()
        env_extras.refresh()
        message = self._outcome(component, ok, exit_code)
        logger.info("Install of %s: %s", component.extra, message)
        self.last_result = (component.extra, ok and not self._cancelled, message)
        self.finished.emit(*self.last_result)

    def _outcome(self, component: Component, ok: bool, exit_code: int) -> str:
        if self._cancelled:
            return f"{component.title}: installation cancelled."
        if not ok:
            last = next((line for line in reversed(self._log) if line.strip()), "")
            return f"Could not install {component.title} (exit {exit_code}): {last}"
        if component.needs_restart or not component.installed():
            return f"{component.title} is installed: restart RoomKit UI to use it."
        return f"{component.title} is installed."


_installer: ComponentInstaller | None = None


def installer() -> ComponentInstaller:
    """The app's one installer, owned by the application so it outlives dialogs."""
    global _installer
    if _installer is None:
        _installer = ComponentInstaller(QCoreApplication.instance())
    return _installer


def restart_app(app: QCoreApplication | None = None) -> None:
    """Quit, then start again with the same command line once this one is gone."""
    app = app or QCoreApplication.instance()
    if app is None:
        return
    argv = list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv])
    app.aboutToQuit.connect(lambda: QProcess.startDetached(argv[0], argv[1:]))
    app.quit()
