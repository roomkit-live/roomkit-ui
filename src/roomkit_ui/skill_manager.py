"""Agent Skills source management, discovery, and registry builder."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


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


def get_clawhub_dir() -> Path:
    """Return the directory for ClawHub-installed skills."""
    d = get_skills_dir() / "clawhub"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_clawhub_installed() -> list[str]:
    """Return slugs of installed ClawHub skills."""
    d = get_clawhub_dir()
    if not d.exists():
        return []
    return [p.name for p in d.iterdir() if p.is_dir() and (p / "SKILL.md").exists()]


def remove_clawhub_skill(slug: str) -> None:
    """Remove an installed ClawHub skill."""
    target = get_clawhub_dir() / slug
    if target.exists():
        shutil.rmtree(target)
        logger.info("Removed ClawHub skill %s", slug)


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


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
    parts = [p for p in raw.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}--{parts[-1]}"
    if parts:
        return parts[-1]
    return "repo"


async def clone_repo(url: str) -> Path:
    """Shallow-clone a git repo into the repos directory. Returns the clone path."""
    import asyncio

    dest = get_repos_dir() / repo_dir_name(url)
    if dest.exists():
        shutil.rmtree(dest)

    def _clone() -> None:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )

    await asyncio.to_thread(_clone)
    logger.info("Cloned %s → %s", url, dest)
    return dest


async def pull_repo(repo_path: Path) -> bool:
    """Pull latest changes (fast-forward only). Returns True on success."""
    import asyncio

    def _pull() -> bool:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "pull", "--ff-only"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    ok = await asyncio.to_thread(_pull)
    if ok:
        logger.info("Pulled %s", repo_path)
    else:
        logger.warning("Pull failed for %s", repo_path)
    return ok


def remove_repo(repo_path: Path) -> None:
    """Remove a cloned repo directory."""
    if repo_path.exists():
        shutil.rmtree(repo_path)
        logger.info("Removed %s", repo_path)


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
    if src_type == "clawhub":
        d = get_clawhub_dir()
        return d if d.is_dir() else None
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
    from roomkit.skills.parser import parse_skill_metadata

    results: list[tuple[object, Path, str]] = []
    for source in sources:
        label = source.get("label", source.get("url", source.get("path", "unknown")))
        root = _resolve_source_path(source)
        if root is None:
            continue
        for skill_dir in _find_skill_dirs(root):
            try:
                meta = parse_skill_metadata(skill_dir)
            except Exception:
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
