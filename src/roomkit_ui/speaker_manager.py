"""Persist enrolled speaker profiles as JSON files."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _speakers_dir() -> Path:
    """Return (and create) the speaker profiles directory."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "RoomKit UI"
    else:
        base = Path.home() / ".local" / "share" / "roomkit-ui"
    d = base / "speakers"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class SpeakerProfile:
    name: str
    embeddings: list[list[float]] = field(default_factory=list)
    is_primary: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(UTC).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


def _profile_path(name: str) -> Path:
    """Return the JSON file path for a speaker profile."""
    safe_name = name.replace("/", "_").replace("\\", "_")
    return _speakers_dir() / f"{safe_name}.json"


def load_speakers() -> list[SpeakerProfile]:
    """Load all saved speaker profiles."""
    profiles: list[SpeakerProfile] = []
    d = _speakers_dir()
    for path in sorted(d.glob("*.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
            profiles.append(SpeakerProfile(**data))
        except Exception:
            logger.exception("Failed to load speaker profile: %s", path)
    return profiles


def save_speaker(profile: SpeakerProfile) -> None:
    """Save a speaker profile to disk."""
    profile.updated_at = datetime.now(UTC).isoformat()
    path = _profile_path(profile.name)
    path.write_text(json.dumps(asdict(profile), indent=2), "utf-8")


def delete_speaker(name: str) -> None:
    """Delete a speaker profile by name."""
    path = _profile_path(name)
    path.unlink(missing_ok=True)


def get_primary_speaker() -> SpeakerProfile | None:
    """Return the primary speaker profile, or None."""
    for p in load_speakers():
        if p.is_primary:
            return p
    return None


def set_primary_speaker(name: str) -> None:
    """Set *name* as the primary speaker (clears any previous primary)."""
    for p in load_speakers():
        changed = False
        if p.name == name and not p.is_primary:
            p.is_primary = True
            changed = True
        elif p.name != name and p.is_primary:
            p.is_primary = False
            changed = True
        if changed:
            save_speaker(p)


def add_embedding_to_speaker(name: str, embedding: list[float]) -> None:
    """Append a new voice embedding sample to an existing speaker."""
    for p in load_speakers():
        if p.name == name:
            p.embeddings.append(embedding)
            save_speaker(p)
            return
    raise ValueError(f"Speaker not found: {name}")
