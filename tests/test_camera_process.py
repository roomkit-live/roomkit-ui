"""Real helper pipes, with synthetic photos and no camera or credential access."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QProcess

from roomkit_ui.widgets import camera_process
from roomkit_ui.widgets.camera_process import CameraProcess
from roomkit_ui.widgets.image_attachments import ImageAttachments

# Exercise the actual helper entrypoint and real CameraDialog review path. Block
# secret/application imports instead of touching the user's Keychain or camera.
_HELPER = """
import sys
class NoSecrets:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] == 'keyring' or fullname in (
            'roomkit_ui.settings', 'roomkit_ui.secret_store', 'roomkit_ui.app',
            'roomkit_ui.engine',
        ):
            raise RuntimeError('Camera must not import ' + fullname)
sys.meta_path.insert(0, NoSecrets())
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage
from roomkit_ui.widgets.camera_dialog import CameraDialog
from roomkit_ui import camera_capture
camera_capture.relaunch_camera_if_needed = lambda: None
def ready(dialog):
    print('ready', file=sys.stderr, flush=True)
    if SEND_PHOTO:
        def use_photo():
            image = QImage(32, 24, QImage.Format_RGB32)
            image.fill(Qt.green)
            dialog._captured(1, image)
            dialog._take_or_use()
        QTimer.singleShot(30, use_photo)
CameraDialog._request_access = ready
sys.argv = ['camera', '--theme', 'light']
sys.exit(camera_capture.main())
"""


@pytest.fixture
def camera(qtbot):
    process = CameraProcess()
    # The source-only helper is not invoked by Windows/Linux product paths.
    # Qt pipe reading is supported by the macOS/Linux test environment.
    yield process
    process.shutdown()


def _helper(camera, *, photo=False):
    camera._process.setArguments(["-c", f"SEND_PHOTO = {photo!r}\n" + _HELPER])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX camera helper")
def test_camera_helper_returns_reviewed_photo_without_loading_secrets(qtbot, camera):
    selected, errors = [], []
    camera.photo_selected.connect(selected.append)
    camera.error.connect(errors.append)
    _helper(camera, photo=True)
    with qtbot.waitSignal(camera.finished, timeout=15000):
        camera.open()
    assert errors == []
    assert len(selected) == 1
    assert selected[0].name == "Camera photo"
    image = selected[0].image()
    assert (image.width(), image.height()) == (32, 24)
    assert camera._process.state() == QProcess.NotRunning


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX camera helper")
@pytest.mark.parametrize("action", ["reject", "parent_eof"])
def test_camera_helper_stops_on_cancel_or_parent_exit(qtbot, camera, action):
    _helper(camera)
    selected, errors = [], []
    camera.photo_selected.connect(selected.append)
    camera.error.connect(errors.append)
    with qtbot.waitSignal(camera.finished, timeout=15000):
        camera.open()
        qtbot.waitUntil(lambda: camera._process.state() == QProcess.Running)
        if action == "reject":
            camera.reject()
        else:
            camera._process.closeWriteChannel()
    assert errors == [] and selected == []
    assert camera._process.exitStatus() == QProcess.NormalExit


def test_clearing_draft_ignores_photo_arriving_after_cancel(qtbot, monkeypatch):
    tray = ImageAttachments()
    qtbot.addWidget(tray)
    camera = CameraProcess(tray)
    camera._process.setArguments(
        ["-c", "import sys; sys.stdin.readline(); print('late photo reply', flush=True)"]
    )
    monkeypatch.setattr(camera_process, "create_camera", lambda *_: camera)
    tray._open_camera()
    with qtbot.waitSignal(camera.finished, timeout=10000):
        tray.clear()
    assert tray.images == () and tray._camera is None
    assert tray._notice.text() == ""


@pytest.mark.parametrize(
    "reply",
    ["not json", json.dumps({"event": "photo", "image": {}}), "x" * 2049],
)
def test_bad_camera_reply_reports_error_and_finishes(qtbot, camera, monkeypatch, reply):
    monkeypatch.setattr(camera_process, "_MAX_REPLY", 2048)
    camera._process.setArguments(["-c", f"print({reply!r}, flush=True)"])
    errors, selected = [], []
    camera.error.connect(errors.append)
    camera.photo_selected.connect(selected.append)
    with qtbot.waitSignal(camera.finished, timeout=10000):
        camera.open()
    assert len(errors) == 1 and selected == []


def test_start_failure_is_visible_and_can_be_retried(qtbot, camera, tmp_path):
    camera._process.setProgram(str(tmp_path / "missing-python"))
    errors = []
    camera.error.connect(errors.append)
    with qtbot.waitSignal(camera.finished, timeout=10000):
        camera.open()
    assert len(errors) == 1


def test_app_exit_forces_an_unresponsive_helper_to_stop(qtbot, camera):
    camera._process.setArguments(["-c", "import time; time.sleep(60)"])
    camera.open()
    qtbot.waitUntil(lambda: camera._process.state() == QProcess.Running)
    camera.shutdown()
    assert camera._process.state() == QProcess.NotRunning


@pytest.mark.parametrize(
    ("platform", "frozen", "declared", "isolated"),
    [
        ("darwin", False, False, True),
        ("darwin", False, True, False),
        ("darwin", True, False, False),
        ("linux", False, False, False),
        ("win32", False, False, False),
    ],
)
def test_only_source_mac_camera_needs_another_identity(
    monkeypatch, platform, frozen, declared, isolated
):
    monkeypatch.setattr(camera_process, "sys", SimpleNamespace(platform=platform, frozen=frozen))
    monkeypatch.setattr(camera_process, "camera_usage_declared", lambda: declared)
    assert camera_process.needs_camera_process() is isolated


def test_main_app_does_not_reexec_for_camera(monkeypatch):
    from roomkit_ui import app, macos_app

    class ApplicationReachedError(Exception):
        pass

    # Stop before loading settings or touching hardware; a regression in source
    # bootstrap would try to copy/re-exec the interpreter before reaching Qt.
    monkeypatch.setattr(app, "_configure_logging", lambda: None)
    monkeypatch.setattr(app, "migrate_legacy_mac_data", lambda: None)
    monkeypatch.setattr(app, "_create_app", Mock(side_effect=ApplicationReachedError))
    execute = Mock(side_effect=AssertionError("Main app must keep its Keychain identity"))
    monkeypatch.setattr(macos_app.os, "execve", execute)
    monkeypatch.setattr(macos_app, "prepare_app", execute)
    with pytest.raises(ApplicationReachedError):
        app.main()
    execute.assert_not_called()
