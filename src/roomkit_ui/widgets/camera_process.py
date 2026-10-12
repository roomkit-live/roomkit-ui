"""Isolate source macOS camera permission from the main app's Keychain identity."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget

from roomkit_ui.cli_exec import child_env
from roomkit_ui.images import MAX_IMAGE_BYTES, ImageAttachment
from roomkit_ui.macos_app import camera_usage_declared

if TYPE_CHECKING:
    from roomkit_ui.widgets.camera_dialog import CameraDialog

_MAX_REPLY = MAX_IMAGE_BYTES * 2
_FAILURE = "The camera window could not be opened. Please try again or choose an image file."


def needs_camera_process() -> bool:
    return (
        sys.platform == "darwin"
        and not getattr(sys, "frozen", False)
        and not camera_usage_declared()
    )


def create_camera(
    parent: QWidget, on_error: Callable[[str], None]
) -> CameraDialog | CameraProcess:
    from roomkit_ui.widgets.camera_dialog import HAS_CAMERA, CameraDialog

    if HAS_CAMERA and needs_camera_process():
        camera = CameraProcess(parent)
        camera.error.connect(on_error)
        return camera
    return CameraDialog(parent)


class CameraProcess(QObject):
    """One camera window, with a bounded image reply over an anonymous pipe."""

    photo_selected = Signal(object)  # ImageAttachment
    finished = Signal(int)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._closed = False
        self._finished = False
        self._received = False
        self._buffer = bytearray()
        self._process = QProcess(self)
        environment = QProcessEnvironment()
        for key, value in child_env().items():
            environment.insert(key, value)
        self._process.setProcessEnvironment(environment)
        self._process.setProgram(sys.executable)
        theme = str(QSettings().value("room/theme", "dark"))
        self._process.setArguments(["-m", "roomkit_ui.camera_capture", "--theme", theme])
        # Qt diagnostics are not protocol data. Drain them without retaining images.
        self._process.readyReadStandardError.connect(self._drain_errors)
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.started.connect(self._started)
        self._process.finished.connect(self._ended)
        self._process.errorOccurred.connect(self._process_error)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._process.kill)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def open(self) -> None:
        self._process.start()

    @Slot()
    def _started(self) -> None:
        if self._closed:
            self._process.write(b"cancel\n")

    def raise_(self) -> None:
        if not self._closed and self._process.state() == QProcess.Running:
            self._process.write(b"raise\n")

    def reject(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._buffer.clear()
        if self._process.state() == QProcess.NotRunning:
            self._finish()
        else:
            if self._process.state() == QProcess.Running:
                self._process.write(b"cancel\n")
            self._kill_timer.start(2000)

    @Slot()
    def _drain_errors(self) -> None:
        self._process.readAllStandardError()

    @Slot()
    def _read(self) -> None:
        data = self._process.readAllStandardOutput().data()
        if self._closed:
            return
        self._buffer.extend(data)
        if len(self._buffer) > _MAX_REPLY:
            self._fail()
            return
        while b"\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            try:
                reply = json.loads(line)
                if reply["event"] != "photo" or self._received:
                    raise ValueError("Unexpected camera reply")
                photo = ImageAttachment.restore(reply["image"])
                if photo.image().isNull():
                    raise ValueError("Invalid photo")
            except (ValueError, TypeError, KeyError):
                self._fail()
                return
            self._received = True
            self.photo_selected.emit(photo)

    @Slot(QProcess.ProcessError)
    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            self._fail()
            self._finish()

    @Slot(int, QProcess.ExitStatus)
    def _ended(self, code: int, status: QProcess.ExitStatus) -> None:
        self._read()
        if not self._closed and (code != 0 or status == QProcess.CrashExit or self._buffer):
            self._fail()
        self._finish()

    def _fail(self) -> None:
        if not self._closed:
            self.error.emit(_FAILURE)
            self.reject()

    def _finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._closed = True
            self._kill_timer.stop()
            self._buffer.clear()
            self.finished.emit(int(self._received))

    @Slot()
    def shutdown(self) -> None:
        """Bounded synchronous cleanup only at application exit."""
        self.reject()
        if self._process.state() != QProcess.NotRunning and not self._process.waitForFinished(
            1000
        ):
            self._process.kill()
            self._process.waitForFinished(1000)
