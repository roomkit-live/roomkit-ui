"""Agent Skills: where sources live on disk, discovery, and the registry.

Fetching sources is apart: git clones in ``skill_git``, skills.sh
well-known installs in ``skill_well_known``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Anything but letters, digits, ".", "_", "-" — a backslash included, which
# Windows reads as a path separator.
_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def get_skills_dir() -> Path:
    """Return the base skills directory, creating it if needed."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "RoomKit UI" / "skills"
    else:
        base = Path.home() / ".local" / "share" / "roomkit-ui" / "skills"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_repos_dir() -> Path:
    """Return the directory for cloned git repos."""
    d = get_skills_dir() / "repos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_dir_segment(value: str) -> str:
    """Return a deterministic filesystem segment for marketplace-owned folders."""
    value = value.strip().lower()
    sanitized = re.sub(r"[^a-z0-9._-]+", "-", value).strip(".-")
    return sanitized[:96] or "unknown"


def well_known_skill_dir(source: str, skill_name: str) -> Path:
    """Return the local install directory for a skills.sh well-known skill."""
    return (
        get_skills_dir()
        / "well-known"
        / f"{_safe_dir_segment(source)}--{_safe_dir_segment(skill_name)}"
    )


def repo_dir_name(url: str) -> str:
    """Convert a git URL to a directory name: ``org--repo``.

    Handles both HTTPS (``https://github.com/org/repo``) and SSH
    (``git@github.com:org/repo.git``) URLs.
    """
    raw = url.strip()
    # SSH URLs: git@host:org/repo.git → extract the path after ':'
    if ":" in raw and not raw.startswith(("http://", "https://", "/")):
        raw = raw.split(":", 1)[1]
    else:
        raw = urlparse(raw).path
    raw = raw.rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    # One path segment each, never "." or "..": the name is joined under the
    # repos directory, which a clone replaces and discovery scans.
    parts = [_UNSAFE_SEGMENT_CHARS.sub("-", p) for p in raw.split("/")]
    parts = [p for p in parts if p not in ("", ".", "..")]
    if len(parts) >= 2:
        return f"{parts[-2]}--{parts[-1]}"
    if parts:
        return parts[-1]
    return f"repo-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _resolve_source_path(source: dict) -> Path | None:
    """Resolve the filesystem path for a skill source."""
    src_type = source.get("type", "")
    if src_type == "git":
        url = source.get("url", "")
        if not url:
            return None
        dest = get_repos_dir() / repo_dir_name(url)
        return dest if dest.exists() else None
    if src_type == "local":
        p = Path(source.get("path", ""))
        return p if p.is_dir() else None
    return None


def _find_skill_dirs(root: Path) -> list[Path]:
    """Recursively find all directories containing a SKILL.md file."""
    results: list[Path] = []
    for md in root.rglob("[Ss][Kk][Ii][Ll][Ll].[Mm][Dd]"):
        if md.is_file():
            results.append(md.parent)
    return results


def discover_all_skills(
    sources: list[dict],
) -> list[tuple[object, Path, str]]:
    """Discover all skills from configured sources.

    Recursively scans each source for directories containing SKILL.md,
    then parses metadata from each.  This handles repos that nest skills
    in subdirectories (e.g. ``plugins/<name>/skills/<skill>/``).

    Uses ``parse_skill_metadata`` directly (no ``register()``) so the
    framework doesn't emit "Registered skill" logs during browsing.

    Returns a list of ``(SkillMetadata, skill_path, source_label)`` tuples.
    Invalid skills are logged and skipped.
    """
    from roomkit.skills.parser import (
        SkillMetadata,
        find_skill_md,
        parse_frontmatter,
        parse_skill_metadata,
    )

    def _lenient_parse(skill_dir: Path) -> SkillMetadata | None:
        """Parse frontmatter without enforcing name-vs-directory match.

        Useful for imported or marketplace-listed skills where the directory
        name may be a slug rather than the skill name.
        """
        md_path = find_skill_md(skill_dir)
        if md_path is None:
            return None
        content = md_path.read_text(encoding="utf-8")
        data, _ = parse_frontmatter(content)

        def _text(value: str | list[str] | None) -> str:
            # A YAML list where text belongs is joined, as roomkit's strict
            # parser does; only allowed_tools keeps its list form.
            if isinstance(value, list):
                return ", ".join(value)
            return value or ""

        name = _text(data.get("name"))
        desc = _text(data.get("description"))
        if not name or not desc:
            return None
        _known = {"name", "description", "license", "compatibility", "allowed_tools"}
        extra = {k: _text(v) for k, v in data.items() if k not in _known}
        return SkillMetadata(
            name=name,
            description=desc,
            license=_text(data.get("license")) or None,
            compatibility=_text(data.get("compatibility")) or None,
            allowed_tools=data.get("allowed_tools"),
            extra_metadata=extra,
        )

    results: list[tuple[object, Path, str]] = []
    for source in sources:
        src_type = source.get("type", "")
        raw_label = source.get("label", source.get("url", source.get("path", "unknown")))
        if src_type == "git":
            label = f"git \u00b7 {raw_label}"
        elif src_type == "local":
            label = f"local \u00b7 {raw_label}"
        else:
            label = raw_label
        root = _resolve_source_path(source)
        if root is None:
            continue
        for skill_dir in _find_skill_dirs(root):
            meta: SkillMetadata | None
            try:
                meta = parse_skill_metadata(skill_dir)
            except Exception:
                # Strict parse failed; try lenient parsing for slug/name mismatches.
                try:
                    meta = _lenient_parse(skill_dir)
                except Exception:
                    meta = None
                if meta is None:
                    logger.debug("Skipping invalid skill in %s", skill_dir, exc_info=True)
                    continue
            results.append((meta, skill_dir, label))
    return results


# ---------------------------------------------------------------------------
# Registry builder (called by engine)
# ---------------------------------------------------------------------------


def build_registry(
    sources: list[dict],
    enabled_names: list[str],
) -> object:
    """Build a ``SkillRegistry`` containing only the enabled skills.

    Discovers all skills from sources, then registers only those whose
    name appears in *enabled_names*.  Returns the registry (may be empty).
    """
    from roomkit.skills import SkillRegistry

    all_skills = discover_all_skills(sources)
    registry = SkillRegistry()
    enabled_set = set(enabled_names)
    for meta, skill_path, _label in all_skills:
        if meta.name in enabled_set:
            try:
                registry.register(skill_path)
            except Exception:
                logger.exception("Failed to register skill %s from %s", meta.name, skill_path)
    return registry
