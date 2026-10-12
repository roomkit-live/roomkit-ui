"""Only the camera helper gains a bundle, without modifying the original Python."""

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from roomkit_ui import macos_app


def test_cached_bundle_is_separate_from_python_and_refreshes_on_upgrade(tmp_path, monkeypatch):
    source = tmp_path / "python"
    source.write_bytes(b"original interpreter")
    source.chmod(0o755)
    venv = tmp_path / "venv-python"
    venv.symlink_to(source)
    sign = Mock()
    monkeypatch.setattr(macos_app.subprocess, "run", sign)
    bundle = tmp_path / "RoomKit UI.app"
    executable = macos_app.prepare_app(venv, bundle)
    assert executable.read_bytes() == source.read_bytes()
    assert executable.stat().st_ino != source.stat().st_ino
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    assert info["NSCameraUsageDescription"] and info["NSMicrophoneUsageDescription"]
    assert info["CFBundleIdentifier"] == "com.roomkit.ui.development"
    assert sign.call_args.args[0][-1] == str(bundle)
    cached_mtime = executable.stat().st_mtime_ns
    assert macos_app.prepare_app(venv, bundle) == executable
    assert executable.stat().st_mtime_ns == cached_mtime
    assert sign.call_count == 1
    source.write_bytes(b"new interpreter version")
    macos_app.prepare_app(venv, bundle)
    assert executable.read_bytes() == b"new interpreter version"
    assert sign.call_count == 2


def test_failed_signing_never_leaves_a_valid_cache(tmp_path, monkeypatch):
    source = tmp_path / "python"
    source.write_bytes(b"python")
    sign = Mock(side_effect=subprocess.CalledProcessError(1, "codesign"))
    monkeypatch.setattr(macos_app.subprocess, "run", sign)
    bundle = tmp_path / "RoomKit UI.app"
    with pytest.raises(subprocess.CalledProcessError):
        macos_app.prepare_app(source, bundle)
    assert not (bundle / "Contents/Info.plist").exists()
    assert source.read_bytes() == b"python"


def test_relaunch_preserves_venv_arguments_and_environment(tmp_path, monkeypatch):
    python = tmp_path / "venv/bin/python"
    executable = tmp_path / "RoomKit UI.app/Contents/MacOS/RoomKit UI"
    monkeypatch.setattr(
        macos_app,
        "sys",
        SimpleNamespace(
            platform="darwin",
            executable=str(python),
            prefix=str(python.parent.parent),
            argv=["roomkit-ui", "example-argument"],
        ),
    )
    monkeypatch.setattr(macos_app, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(macos_app, "camera_usage_declared", lambda: False)
    monkeypatch.setattr(macos_app, "prepare_app", lambda *_: executable)
    monkeypatch.delenv(macos_app._RELAUNCH, raising=False)
    monkeypatch.setenv("ROOMKIT_TEST_VALUE", "keep this value")
    probe, execute = Mock(), Mock()
    monkeypatch.setattr(macos_app.subprocess, "run", probe)
    monkeypatch.setattr(macos_app.os, "execve", execute)
    macos_app.relaunch_camera_if_needed()
    path, argv, env = execute.call_args.args
    assert path == executable
    assert argv == [str(executable), "-m", "roomkit_ui.camera_capture", "example-argument"]
    assert env["__PYVENV_LAUNCHER__"] == str(python)
    assert env["ROOMKIT_TEST_VALUE"] == "keep this value"
    assert env[macos_app._RELAUNCH] == "1"
    assert probe.call_args.kwargs["env"]["__PYVENV_LAUNCHER__"] == str(python)
    # A broken bundle cannot cause a relaunch loop or leak the guard to workers.
    monkeypatch.setenv(macos_app._RELAUNCH, "1")
    with pytest.raises(RuntimeError, match="usage description"):
        macos_app.relaunch_camera_if_needed()
    assert execute.call_count == 1
    assert macos_app._RELAUNCH not in os.environ


@pytest.mark.parametrize(
    ("platform", "frozen", "declared"),
    [
        ("linux", False, False),
        ("win32", False, False),
        ("darwin", True, False),
        ("darwin", False, True),
    ],
)
def test_supported_launches_are_untouched(monkeypatch, platform, frozen, declared):
    monkeypatch.setattr(macos_app, "sys", SimpleNamespace(platform=platform, frozen=frozen))
    monkeypatch.setattr(macos_app, "camera_usage_declared", lambda: declared)
    prepare = Mock()
    monkeypatch.setattr(macos_app, "prepare_app", prepare)
    macos_app.relaunch_camera_if_needed()
    prepare.assert_not_called()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS bundle identity")
def test_native_bundle_keeps_venv_and_exposes_camera_declaration(tmp_path):
    python = Path(sys.executable)
    executable = macos_app.prepare_app(python, tmp_path / "RoomKit UI.app")
    code = (
        "import json, os, sys; "
        "from roomkit_ui.macos_app import camera_usage_declared; "
        "print(json.dumps([sys.executable, sys.prefix, camera_usage_declared(), "
        "'__PYVENV_LAUNCHER__' in os.environ]))"
    )
    result = subprocess.run(
        [str(executable), "-c", code],
        env=dict(os.environ, __PYVENV_LAUNCHER__=str(python)),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert json.loads(result.stdout) == [sys.executable, sys.prefix, True, False]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS source process relaunch")
def test_native_relaunch_returns_to_entrypoint_without_camera_or_venv_changes(tmp_path):
    package = tmp_path / "roomkit_ui"
    package.mkdir()
    package.joinpath("__init__.py").write_text(
        f"__path__.append({str(Path(macos_app.__file__).parent)!r})\n"
    )
    package.joinpath("camera_capture.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "from roomkit_ui import macos_app\n"
        f"macos_app.data_dir = lambda: Path({str(tmp_path / 'data')!r})\n"
        "macos_app.relaunch_camera_if_needed()\n"
        "print(json.dumps([sys.executable, sys.prefix, macos_app.camera_usage_declared(), "
        "sys.argv[1:], macos_app._RELAUNCH in os.environ]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "roomkit_ui.camera_capture", "argument with spaces"],
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path)),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == [
        sys.executable,
        sys.prefix,
        True,
        ["argument with spaces"],
        False,
    ]
