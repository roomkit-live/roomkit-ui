"""Camera review and cleanup without opening a real user's camera."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from roomkit_ui.widgets import camera_dialog
from roomkit_ui.widgets.camera_dialog import CameraDialog
from roomkit_ui.widgets.image_attachments import ImageAttachments


@pytest.fixture(autouse=True)
def local_camera(monkeypatch):
    monkeypatch.setattr("roomkit_ui.widgets.camera_process.needs_camera_process", lambda: False)


def test_capture_is_reviewed_before_use_and_camera_stops(qtbot, monkeypatch):
    monkeypatch.setattr(CameraDialog, "_request_access", lambda _: None)
    tray = ImageAttachments()
    qtbot.addWidget(tray)
    tray._open_camera()
    dialog = tray._camera
    qtbot.addWidget(dialog)
    camera, session = Mock(), Mock()
    dialog._camera = camera
    dialog._session = session
    dialog._video = QWidget()
    dialog._views.addWidget(dialog._video)
    image = QImage(90, 60, QImage.Format_RGB32)
    image.fill(Qt.green)
    dialog._captured(1, image)
    assert tray.images == ()
    camera.stop.assert_called_once()
    assert dialog._shutter.text() == "Use photo"
    dialog._retake.click()
    assert dialog._photo.isNull() and tray.images == ()
    camera.start.assert_called_once()
    dialog._captured(2, image)
    dialog._shutter.click()
    assert len(tray.images) == 1 and tray.images[0].name == "Camera photo"
    assert tray._camera is None
    session.setCamera.assert_called_with(None)
    session.setVideoOutput.assert_called_with(None)


def test_cancel_and_late_permission_never_start_camera(qtbot, monkeypatch):
    monkeypatch.setattr(CameraDialog, "_request_access", lambda _: None)
    dialog = CameraDialog()
    qtbot.addWidget(dialog)
    opened = Mock()
    monkeypatch.setattr(dialog, "_open_camera", opened)
    dialog.reject()
    dialog._permission_ready(SimpleNamespace(status=lambda: Qt.PermissionStatus.Granted))
    opened.assert_not_called()
    assert dialog._photo.isNull()


def test_no_device_and_denied_permission_have_visible_feedback(qtbot, monkeypatch):
    monkeypatch.setattr(CameraDialog, "_request_access", lambda _: None)
    monkeypatch.setattr(
        camera_dialog, "QMediaDevices", SimpleNamespace(videoInputs=lambda: []), raising=False
    )
    dialog = CameraDialog()
    qtbot.addWidget(dialog)
    dialog._open_camera()
    assert "No camera" in dialog._status.text()
    assert not dialog._shutter.isEnabled()
    dialog._permission_ready(SimpleNamespace(status=lambda: Qt.PermissionStatus.Denied))
    assert "privacy settings" in dialog._status.text()


def test_clearing_draft_closes_camera_without_adding_photo(qtbot, monkeypatch):
    monkeypatch.setattr(CameraDialog, "_request_access", lambda _: None)
    tray = ImageAttachments()
    qtbot.addWidget(tray)
    tray._open_camera()
    dialog = tray._camera
    camera = Mock()
    dialog._camera = camera
    tray.clear()
    camera.stop.assert_called_once()
    assert tray._camera is None and tray.images == ()


def test_first_request_waits_for_user_and_launch_issue_is_not_reported_as_denial(
    qtbot, monkeypatch
):
    request = CameraDialog._request_access
    monkeypatch.setattr(CameraDialog, "_request_access", lambda _: None)
    monkeypatch.setattr(camera_dialog, "HAS_CAMERA", True)
    dialog = CameraDialog()
    qtbot.addWidget(dialog)
    opened = Mock()
    monkeypatch.setattr(dialog, "_open_camera", opened)
    app = SimpleNamespace(
        checkPermission=Mock(return_value=Qt.PermissionStatus.Undetermined),
        requestPermission=Mock(),
    )
    monkeypatch.setattr(camera_dialog, "QApplication", SimpleNamespace(instance=lambda: app))
    monkeypatch.setattr(camera_dialog, "camera_usage_declared", lambda: False)
    request(dialog)
    app.requestPermission.assert_not_called()
    assert "could not be requested" in dialog._status.text()
    assert dialog._views.isHidden() and dialog._shutter.isHidden()
    assert dialog._settings.isHidden()  # There is no OS entry to enable yet.
    monkeypatch.setattr(camera_dialog, "camera_usage_declared", lambda: True)
    request(dialog)
    app.requestPermission.assert_called_once()
    opened.assert_not_called()
    callback = app.requestPermission.call_args.args[-1]
    callback(SimpleNamespace(status=lambda: Qt.PermissionStatus.Granted))
    opened.assert_called_once()


def test_actual_denial_offers_system_settings_without_requesting_again(qtbot, monkeypatch):
    request = CameraDialog._request_access
    monkeypatch.setattr(CameraDialog, "_request_access", lambda _: None)
    monkeypatch.setattr(camera_dialog, "HAS_CAMERA", True)
    monkeypatch.setattr(camera_dialog, "sys", SimpleNamespace(platform="darwin"))
    dialog = CameraDialog()
    qtbot.addWidget(dialog)
    app = SimpleNamespace(
        checkPermission=Mock(return_value=Qt.PermissionStatus.Denied), requestPermission=Mock()
    )
    monkeypatch.setattr(camera_dialog, "QApplication", SimpleNamespace(instance=lambda: app))
    open_url = Mock(return_value=True)
    monkeypatch.setattr(camera_dialog, "QDesktopServices", SimpleNamespace(openUrl=open_url))
    request(dialog)
    app.requestPermission.assert_not_called()
    assert not dialog._settings.isHidden()
    assert dialog._views.isHidden() and dialog._shutter.isHidden()
    dialog._settings.click()
    assert open_url.call_args.args[0].toString().endswith("?Privacy_Camera")
