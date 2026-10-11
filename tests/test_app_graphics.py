"""GPU detection and the graphics environment decided before PySide6 loads."""

import ctypes.util

import pytest

_GRAPHICS_KEYS = ("QTWEBENGINE_CHROMIUM_FLAGS", "QT_QUICK_BACKEND", "LIBGL_ALWAYS_SOFTWARE")


@pytest.fixture
def app_module(monkeypatch):
    # Importing app.py applies its graphics environment with setdefault: set
    # the keys first so the import changes nothing monkeypatch won't restore.
    for key in _GRAPHICS_KEYS:
        monkeypatch.setenv(key, "test")
    import roomkit_ui.app as app

    return app


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_no_libegl_on_macos_or_windows_is_not_missing_opengl(app_module, monkeypatch, platform):
    # Stock macOS and Windows have no libEGL; they render through Metal/D3D.
    monkeypatch.setattr(app_module.sys, "platform", platform)
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)

    assert app_module._opengl_available() is True


def test_no_libegl_on_linux_is_missing_opengl(app_module, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)

    assert app_module._opengl_available() is False


def test_a_working_gpu_keeps_hardware_rendering(app_module):
    env = app_module._graphics_env(has_opengl=True)

    assert "LIBGL_ALWAYS_SOFTWARE" not in env  # forced llvmpipe, and leaked into children
    assert "QT_QUICK_BACKEND" not in env
    assert "--disable-gpu" not in env["QTWEBENGINE_CHROMIUM_FLAGS"]


def test_without_opengl_everything_renders_on_the_cpu(app_module):
    env = app_module._graphics_env(has_opengl=False)

    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert env["QT_QUICK_BACKEND"] == "software"
    assert "--disable-gpu" in env["QTWEBENGINE_CHROMIUM_FLAGS"]


@pytest.mark.parametrize("has_opengl", [True, False])
def test_web_security_is_never_disabled(app_module, has_opengl):
    flags = app_module._graphics_env(has_opengl)["QTWEBENGINE_CHROMIUM_FLAGS"]

    assert "--disable-web-security" not in flags
