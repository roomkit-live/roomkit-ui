"""The log file the app writes beside its console."""

import logging
import sys

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


@pytest.fixture
def root_logging():
    """basicConfig(force=True) replaces the root handlers: put pytest's back."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers:
        handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_the_log_file_takes_characters_outside_the_locale(
    app_module, monkeypatch, tmp_path, root_logging
):
    # Windows' locale is cp1252, which has no "→": every such line failed.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    app_module._configure_logging()

    logging.getLogger("roomkit_ui.test").info("Settings → Components")
    for handler in logging.getLogger().handlers:
        handler.flush()

    log = tmp_path / "roomkit-ui" / "logs" / "roomkit-ui.log"
    assert "Settings → Components" in log.read_text(encoding="utf-8")
