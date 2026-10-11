"""One data folder per platform, and the macOS move off ~/.local/share."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from roomkit_ui import paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_macos_keeps_everything_in_application_support(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert paths.data_dir() == home / "Library" / "Application Support" / "RoomKit UI"


def test_linux_keeps_everything_in_local_share(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert paths.data_dir() == home / ".local" / "share" / "roomkit-ui"


def _legacy(home: Path) -> Path:
    return home / ".local" / "share" / "roomkit-ui"


def test_macos_moves_what_older_versions_left_in_local_share(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    model = _legacy(home) / "models" / "whisper-small" / "encoder.int8.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"onnx")
    (_legacy(home) / "wakeword").mkdir()
    (_legacy(home) / "wakeword" / "fingerprint.json").write_text("{}")

    paths.migrate_legacy_mac_data()

    target = paths.data_dir()
    assert (target / "models" / "whisper-small" / "encoder.int8.onnx").read_bytes() == b"onnx"
    assert (target / "wakeword" / "fingerprint.json").read_text() == "{}"
    assert not _legacy(home).exists()  # emptied, then removed


def test_a_folder_already_at_its_new_home_is_never_overwritten(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    (_legacy(home) / "models").mkdir(parents=True)
    (_legacy(home) / "models" / "old.onnx").write_bytes(b"old")
    (paths.data_dir() / "models").mkdir(parents=True)
    (paths.data_dir() / "models" / "new.onnx").write_bytes(b"new")

    paths.migrate_legacy_mac_data()

    assert not (paths.data_dir() / "models" / "old.onnx").exists()
    assert (_legacy(home) / "models" / "old.onnx").exists()  # left for the user


def test_linux_data_is_never_moved(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    (_legacy(home) / "models").mkdir(parents=True)

    paths.migrate_legacy_mac_data()

    assert (_legacy(home) / "models").is_dir()


def test_an_old_cache_next_to_the_new_one_is_dropped_not_reported_again(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    legacy = home / ".local" / "share" / "roomkit-ui"
    (legacy / "cache").mkdir(parents=True)
    (legacy / "cache" / "old.svg").write_text("x")
    (legacy / "models").mkdir()
    new = paths.data_dir()
    (new / "cache").mkdir(parents=True)
    (new / "models").mkdir()

    paths.migrate_legacy_mac_data()

    assert not (legacy / "cache").exists()  # rebuilt by the app: nothing lost
    assert (legacy / "models").exists()  # user data: never dropped
    assert not (new / "cache" / "old.svg").exists()
