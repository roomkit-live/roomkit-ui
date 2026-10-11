"""Where RoomKit UI keeps its files.

One root per platform: ``~/Library/Application Support/RoomKit UI`` on
macOS, ``~/.local/share/roomkit-ui`` elsewhere.  Every module that stores
something (models, skills, speakers, the conversation database, the wake
word, recordings) builds its folder under :func:`data_dir`.

Older versions split macOS data between the two roots: skills, speakers and
conversations in Application Support, everything else under
``~/.local/share``.  :func:`migrate_legacy_mac_data` moves the latter once.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# What older macOS versions kept under ~/.local/share/roomkit-ui.
_MOVED_ON_MACOS = ("models", "wakeword", "recordings", "debug_audio", "cache")


def data_dir() -> Path:
    """The root every stored file lives under (not created here)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "RoomKit UI"
    return _linux_style_dir()


def _linux_style_dir() -> Path:
    return Path.home() / ".local" / "share" / "roomkit-ui"


def migrate_legacy_mac_data() -> None:
    """Move what older versions kept under ``~/.local/share`` on macOS.

    Each folder moves only when its new home does not exist yet — never
    merged, never overwritten; one already there leaves the old copy in
    place and says so.  A no-op off macOS and once everything has moved.
    """
    if sys.platform != "darwin":
        return
    legacy = _linux_style_dir()
    if not legacy.is_dir():
        return
    target = data_dir()
    for name in _MOVED_ON_MACOS:
        _move_legacy(legacy / name, target / name)
    try:
        legacy.rmdir()  # only once nothing is left in it
    except OSError:
        pass


def _move_legacy(source: Path, dest: Path) -> None:
    if not source.exists():
        return
    if dest.exists():
        logger.warning("Not moving %s: %s already exists", source, dest)
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        logger.info("Moved %s to %s", source, dest)
    except OSError:
        logger.exception("Could not move %s to %s", source, dest)
