"""Tests for safe ZIP extraction of ClawHub skill archives."""

import zipfile

import pytest

from roomkit_ui.clawhub_client import _validate_members


def _make_zip(path, names):
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, "content")
    return path


def test_validate_members_accepts_normal_archive(tmp_path):
    zp = _make_zip(tmp_path / "ok.zip", ["SKILL.md", "sub/dir/file.txt"])
    dest = tmp_path / "dest"
    with zipfile.ZipFile(zp) as zf:
        _validate_members(zf, dest)  # must not raise


def test_validate_members_rejects_parent_traversal(tmp_path):
    zp = _make_zip(tmp_path / "evil.zip", ["SKILL.md", "../evil.txt"])
    dest = tmp_path / "dest"
    with zipfile.ZipFile(zp) as zf, pytest.raises(ValueError, match="unsafe path"):
        _validate_members(zf, dest)


def test_validate_members_rejects_deep_traversal(tmp_path):
    zp = _make_zip(tmp_path / "evil2.zip", ["a/../../outside/file"])
    dest = tmp_path / "dest"
    with zipfile.ZipFile(zp) as zf, pytest.raises(ValueError, match="unsafe path"):
        _validate_members(zf, dest)
