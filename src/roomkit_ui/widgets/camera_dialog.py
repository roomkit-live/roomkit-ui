"""Take and review one photo; the camera is owned by this dialog only."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCameraPermission, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from roomkit_ui.images import ImageAttachment
from roomkit_ui.macos_app import camera_usage_declared

logger = logging.getLogger(__name__)

try:
    from PySide6.QtMultimedia import QCamera, QImageCapture, QMediaCaptureSession, QMediaDevices
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_CAMERA = True
except ImportError:
    HAS_CAMERA = False


class CameraDialog(QDialog):
    photo_selected = Signal(object)  # ImageAttachment

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Take a photo")
        self.setWindowModality(Qt.WindowModal)
        self.resize(560, 480)
        self._closed = False
        self._photo = QImage()
        self._camera: QCamera | None = None
        self._session: QMediaCaptureSession | None = None
        self._capture: QImageCapture | None = None
        layout = QVBoxLayout(self)
        self._layout = layout
        layout.setContentsMargins(20, 20, 20, 20)
        self._devices = QComboBox()
        self._devices.setAccessibleName("Camera")
        self._devices.hide()
        layout.addWidget(self._devices)
        self._views = QStackedWidget()
        self._review = QLabel()
        self._review.setAlignment(Qt.AlignCenter)
        self._views.addWidget(self._review)
        layout.addWidget(self._views, 1)
        self._status = QLabel("Opening camera…")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        actions.addStretch()
        self._settings = QPushButton("Open System Settings")
        self._settings.clicked.connect(self._open_privacy_settings)
        self._settings.hide()
        actions.addWidget(self._settings)
        self._retake = QPushButton("Retake")
        self._retake.clicked.connect(self._start_preview)
        self._retake.hide()
        actions.addWidget(self._retake)
        self._shutter = QPushButton("Take photo")
        self._shutter.setEnabled(False)
        self._shutter.clicked.connect(self._take_or_use)
        actions.addWidget(self._shutter)
        layout.addLayout(actions)
        QTimer.singleShot(0, self._request_access)

    def _request_access(self) -> None:
        if self._closed:
            return
        if not HAS_CAMERA:
            from roomkit_ui.widgets.install_offer import InstallOffer

            self._unavailable("Camera support is not installed.")
            self._layout.addWidget(
                InstallOffer("camera", self, done_hint="Reopen the camera after restarting.")
            )
            return
        app = QApplication.instance()
        if app is None:
            return
        permission = QCameraPermission()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Undetermined:
            if not camera_usage_declared():
                logger.warning("Camera request unavailable: missing NSCameraUsageDescription")
                self._unavailable(
                    "Camera access could not be requested. Restart RoomKit UI to use its "
                    "macOS launcher. If this continues, use the packaged RoomKit UI app."
                )
                return
            app.requestPermission(permission, self, self._permission_ready)
        elif status == Qt.PermissionStatus.Granted:
            self._open_camera()
        else:
            self._permission_denied()

    def _permission_ready(self, permission) -> None:
        if self._closed:
            return
        if permission.status() == Qt.PermissionStatus.Granted:
            self._open_camera()
        else:
            self._permission_denied()

    def _permission_denied(self) -> None:
        self._unavailable(
            "Camera access is disabled. In your system privacy settings, open "
            "Privacy & Security → Camera and allow the app, then reopen the camera.",
            settings_link=True,
        )

    def _unavailable(self, message: str, *, settings_link: bool = False) -> None:
        self._views.hide()
        self._devices.hide()
        self._shutter.hide()
        self._retake.hide()
        self._settings.setVisible(settings_link and sys.platform == "darwin")
        self._status.setText(message)
        self.resize(480, 180)

    def _open_privacy_settings(self) -> None:
        QDesktopServices.openUrl(
            QUrl("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera")
        )

    def _open_camera(self) -> None:
        devices = QMediaDevices.videoInputs()
        if not devices:
            self._unavailable("No camera found. Connect a camera, or add an image from a file.")
            return
        self._views.show()
        self._shutter.show()
        self._settings.hide()
        self.resize(560, 480)
        self._video = QVideoWidget()
        self._views.addWidget(self._video)
        self._session = QMediaCaptureSession(self)
        self._camera = QCamera(devices[0], self)
        self._capture = QImageCapture(self)
        self._session.setCamera(self._camera)
        self._session.setVideoOutput(self._video)
        self._session.setImageCapture(self._capture)
        # Queued: Qt's FFmpeg backend emits this from inside its V4L2 frame read, and
        # stopping the camera there frees what that read still uses (segfault on Linux).
        self._capture.imageCaptured.connect(self._captured, Qt.QueuedConnection)
        self._capture.readyForCaptureChanged.connect(self._ready)
        self._capture.errorOccurred.connect(lambda _id, _error, message: self._error(message))
        self._camera.errorOccurred.connect(lambda _error, message: self._error(message))
        for device in devices:
            self._devices.addItem(device.description(), device)
        self._devices.setVisible(len(devices) > 1)
        self._devices.currentIndexChanged.connect(self._switch_camera)
        self._start_preview()

    def _switch_camera(self, index: int) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera.setCameraDevice(self._devices.itemData(index))
            self._start_preview()

    def _start_preview(self) -> None:
        if self._closed or self._camera is None:
            return
        self._photo = QImage()
        self._retake.hide()
        self._devices.setEnabled(True)
        self._shutter.setText("Take photo")
        self._shutter.setEnabled(False)
        self._status.setText("Your photo will be added to the message before sending.")
        self._views.setCurrentWidget(self._video)
        self._camera.start()

    def _ready(self, ready: bool) -> None:
        if not self._closed and self._photo.isNull():
            self._shutter.setEnabled(ready)

    def _take_or_use(self) -> None:
        if not self._photo.isNull():
            try:
                photo = ImageAttachment.from_image(self._photo, "Camera photo")
            except ValueError as exc:
                self._error(str(exc))
                return
            self.photo_selected.emit(photo)
            self.accept()
        elif self._capture is not None and self._capture.isReadyForCapture():
            self._shutter.setEnabled(False)
            self._capture.capture()  # QImage only: never write to the user's Photos folder.

    def _captured(self, _id: int, image: QImage) -> None:
        if self._closed:
            return
        self._photo = image.copy()
        if self._camera is not None:
            self._camera.stop()
        self._review.setPixmap(
            QPixmap.fromImage(image).scaled(500, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._views.setCurrentWidget(self._review)
        self._devices.setEnabled(False)
        self._retake.show()
        self._shutter.setText("Use photo")
        self._shutter.setEnabled(True)
        self._status.setText("Use this photo, or retake it.")

    def _error(self, message: str) -> None:
        if not self._closed:
            self._status.setText(message or "The camera could not be opened.")
            self._shutter.setEnabled(False)

    def done(self, result: int) -> None:
        self._closed = True
        if self._camera is not None:
            self._camera.stop()
        if self._session is not None:
            self._session.setCamera(None)  # type: ignore[arg-type]
            self._session.setVideoOutput(None)  # type: ignore[arg-type]
        super().done(result)
