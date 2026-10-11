"""Agent Skills source management, discovery, and registry builder."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import httpx

from roomkit_ui.cli_exec import CliResult, ProcessRegistry, resolve_command, run_sync

logger = logging.getLogger(__name__)

_GIT_CLONE_TIMEOUT = 180.0
_GIT_PULL_TIMEOUT = 120.0
# Variables that point git at another repository, index or object store.
_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)
# Anything but letters, digits, ".", "_", "-" — a backslash included, which
# Windows reads as a path separator.
_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

_DISCOVERY_SCHEMA_V2 = "https://schemas.agentskills.io/discovery/0.2.0/schema.json"
_WELL_KNOWN_PATHS = (".well-known/agent-skills", ".well-known/skills")
_WELL_KNOWN_TIMEOUT = 20.0
_MAX_WELL_KNOWN_FILES = 500
_MAX_WELL_KNOWN_FILE_BYTES = 5 * 1024 * 1024
_MAX_WELL_KNOWN_TOTAL_BYTES = 50 * 1024 * 1024
_WELL_KNOWN_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


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
    # One path segment each, never "." or "..": the name is joined under the
    # repos directory, which a clone replaces and discovery scans.
    parts = [_UNSAFE_SEGMENT_CHARS.sub("-", p) for p in raw.split("/")]
    parts = [p for p in parts if p not in ("", ".", "..")]
    if len(parts) >= 2:
        return f"{parts[-2]}--{parts[-1]}"
    if parts:
        return parts[-1]
    return f"repo-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def _run_git(args: list[str], *, timeout: float, ceiling: Path | None = None) -> CliResult:
    """Run git like any other child process: resolved on the user's PATH,
    with the bundle's library paths stripped (``cli_exec``), bounded in time,
    and never prompting — a credential prompt would wait for the timeout.

    *ceiling* stops git from looking above that directory for a repository,
    so ``-C`` on a folder that is not a clone fails instead of acting on an
    enclosing one (a home directory kept in git, say).

    Git's repository-redirecting variables are dropped: an app started from
    a git hook or a terminal inside ``git rebase --exec`` inherits GIT_DIR,
    and every skill clone or pull would act on that repository instead.
    """
    git = resolve_command("git")
    if git is None:
        raise RuntimeError("git is not installed or not on PATH")
    env: dict[str, str | None] = dict.fromkeys(_GIT_REDIRECTS)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    return run_sync([*git, *args], timeout=timeout, registry=ProcessRegistry(), extra_env=env)


def _git_error(action: str, result: CliResult) -> RuntimeError:
    if result.timed_out:
        return RuntimeError(f"git {action} timed out")
    detail = result.stderr.strip().splitlines()[-1:] or [f"exit code {result.exit_code}"]
    return RuntimeError(f"git {action} failed: {detail[0]}")


async def clone_repo(url: str) -> Path:
    """Shallow-clone a git repo into the repos directory. Returns the clone path.

    Clones next to the destination and swaps it in only once the clone
    succeeded: a network error must not cost the skills already installed.
    """
    import asyncio

    dest = get_repos_dir() / repo_dir_name(url)
    staging = Path(tempfile.mkdtemp(prefix=".clone-", dir=get_skills_dir()))
    try:
        # "--" ends the options: a URL starting with "-" is a URL, not a flag.
        result = await asyncio.to_thread(
            _run_git,
            ["clone", "--depth", "1", "--", url, str(staging / "repo")],
            timeout=_GIT_CLONE_TIMEOUT,
        )
        if result.exit_code != 0 or result.timed_out:
            raise _git_error("clone", result)
        _swap_in(staging / "repo", dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info("Cloned %s → %s", url, dest)
    return dest


def _swap_in(new: Path, dest: Path) -> None:
    """Replace *dest* with *new*, keeping the old copy until the move succeeded."""
    old = new.with_name("previous")
    if dest.exists():
        dest.rename(old)
    try:
        new.rename(dest)
    except OSError:
        if old.exists():
            old.rename(dest)
        raise


async def pull_repo(repo_path: Path) -> bool:
    """Pull latest changes (fast-forward only). Returns True on success."""
    import asyncio

    if not (repo_path / ".git").exists():
        logger.warning("Pull skipped: %s is not a git clone", repo_path)
        return False
    try:
        result = await asyncio.to_thread(
            _run_git,
            ["-C", str(repo_path), "pull", "--ff-only"],
            timeout=_GIT_PULL_TIMEOUT,
            ceiling=repo_path.parent,
        )
    except RuntimeError:
        logger.warning("Pull failed for %s", repo_path, exc_info=True)
        return False
    ok = result.exit_code == 0 and not result.timed_out
    if ok:
        logger.info("Pulled %s", repo_path)
    else:
        logger.warning("Pull failed for %s: %s", repo_path, _git_error("pull", result))
    return ok


def remove_repo(repo_path: Path) -> None:
    """Remove a cloned repo directory."""
    if repo_path.exists():
        shutil.rmtree(repo_path)
        logger.info("Removed %s", repo_path)


# ---------------------------------------------------------------------------
# Well-known skills operations
# ---------------------------------------------------------------------------


def _is_valid_well_known_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    if not _WELL_KNOWN_NAME_RE.fullmatch(name):
        return False
    return not (name.startswith("-") or name.endswith("-") or "--" in name)


def _is_safe_well_known_file_path(file_path: object) -> bool:
    if not isinstance(file_path, str) or not file_path:
        return False
    if file_path.startswith(("/", "\\")) or "\\" in file_path or "\0" in file_path:
        return False
    # Match the legacy CLI's strict behavior for path traversal prevention.
    return ".." not in file_path


def _is_subpath(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _candidate_well_known_indexes(install_url: str) -> list[tuple[str, str, str]]:
    parsed = urlparse(install_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("well-known install URL must be https")

    root = f"{parsed.scheme}://{parsed.netloc}"
    base_path = parsed.path.rstrip("/")
    candidates: list[tuple[str, str, str]] = []
    for well_known_path in _WELL_KNOWN_PATHS:
        candidates.append(
            (
                f"{root}{base_path}/{well_known_path}/index.json",
                f"{root}{base_path}",
                well_known_path,
            )
        )
        if base_path:
            candidates.append((f"{root}/{well_known_path}/index.json", root, well_known_path))
    return candidates


def _normalize_well_known_index(
    raw_index: object,
    *,
    index_url: str,
    base_url: str,
    well_known_path: str,
) -> list[dict]:
    if not isinstance(raw_index, dict):
        return []
    entries = raw_index.get("skills")
    if not isinstance(entries, list):
        return []

    schema = raw_index.get("$schema")
    if schema == _DISCOVERY_SCHEMA_V2:
        normalized: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if not _is_valid_well_known_name(entry.get("name")):
                continue
            entry_type = entry.get("type")
            digest = entry.get("digest")
            url = entry.get("url")
            description = entry.get("description")
            if entry_type not in {"skill-md", "archive"}:
                continue
            if not isinstance(description, str) or not description or len(description) > 1024:
                continue
            if not isinstance(url, str) or not url:
                continue
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                continue
            artifact_url = urljoin(index_url, url)
            normalized.append(
                {
                    "version": "0.2.0",
                    "name": entry["name"],
                    "type": entry_type,
                    "artifact_url": artifact_url,
                    "digest": digest,
                }
            )
        return normalized

    if schema is not None:
        return []

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            return []
        files = entry.get("files")
        if (
            not _is_valid_well_known_name(entry.get("name"))
            or not isinstance(entry.get("description"), str)
            or not entry.get("description")
            or not isinstance(files, list)
            or not files
            or len(files) > _MAX_WELL_KNOWN_FILES
        ):
            return []
        if not all(_is_safe_well_known_file_path(file_path) for file_path in files):
            return []
        has_skill_md = any(
            isinstance(file_path, str) and file_path.lower() == "skill.md" for file_path in files
        )
        if not has_skill_md:
            return []
        normalized.append(
            {
                "version": "0.1.0",
                "name": entry["name"],
                "files": files,
                "base_url": base_url,
                "well_known_path": well_known_path,
            }
        )
    return normalized


async def _fetch_well_known_entries(
    client: httpx.AsyncClient,
    install_url: str,
) -> list[dict]:
    for index_url, base_url, well_known_path in _candidate_well_known_indexes(install_url):
        try:
            body = await _get_capped(client, index_url, path="index.json", total={"bytes": 0})
            if body is None:
                continue
            entries = _normalize_well_known_index(
                json.loads(body),
                index_url=index_url,
                base_url=base_url,
                well_known_path=well_known_path,
            )
            if entries:
                return entries
        except Exception:
            logger.debug("Failed to read well-known index %s", index_url, exc_info=True)
            continue
    return []


def _select_well_known_entry(
    entries: list[dict],
    *,
    skill_name: str | None,
    install_url: str,
) -> dict:
    if skill_name:
        for entry in entries:
            if entry.get("name") == skill_name:
                return entry

    parsed = urlparse(install_url)
    path_match = re.search(r"/\.well-known/(?:agent-skills|skills)/([^/]+)/?$", parsed.path)
    if path_match:
        name = path_match.group(1)
        for entry in entries:
            if entry.get("name") == name:
                return entry

    if len(entries) == 1:
        return entries[0]

    if skill_name:
        raise ValueError(f"Skill {skill_name!r} was not found in the well-known index")
    raise ValueError("The well-known index contains multiple skills; a skill name is required")


async def _get_capped(
    client: httpx.AsyncClient, url: str, *, path: str, total: dict[str, int]
) -> bytes | None:
    """GET *url*, reading at most the per-file and per-skill caps.

    Streamed: the caps stop the download, not just the result — reading
    ``resp.content`` first held a body of any size in memory before the
    size check ran. Returns None when the server answers with an error.
    """
    async with client.stream("GET", url) as resp:
        if not resp.is_success:
            return None
        declared = resp.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > _MAX_WELL_KNOWN_FILE_BYTES:
            raise ValueError(f"well-known file is too large: {path}")
        body = bytearray()
        async for chunk in resp.aiter_bytes():
            body += chunk
            if len(body) > _MAX_WELL_KNOWN_FILE_BYTES:
                raise ValueError(f"well-known file is too large: {path}")
            if total["bytes"] + len(body) > _MAX_WELL_KNOWN_TOTAL_BYTES:
                raise ValueError("well-known skill exceeds the maximum download size")
    total["bytes"] += len(body)
    return bytes(body)


async def _require_https(request: httpx.Request) -> None:
    """Refuse any plain-http hop, redirects included: nothing here is signed
    but a v0.2 artifact, so TLS is what keeps a skill's text unmodified."""
    if request.url.scheme != "https":
        raise ValueError(f"well-known skills are only fetched over https: {request.url}")


def _validate_skill_md(content: bytes) -> None:
    from roomkit.skills.parser import parse_frontmatter

    text = content.decode("utf-8")
    data, _body = parse_frontmatter(text)
    if not isinstance(data.get("name"), str) or not isinstance(data.get("description"), str):
        raise ValueError("well-known SKILL.md is missing required frontmatter")


async def _fetch_legacy_well_known_files(
    client: httpx.AsyncClient,
    entry: dict,
) -> dict[str, bytes]:
    skill_base_url = f"{entry['base_url'].rstrip('/')}/{entry['well_known_path']}/{entry['name']}"
    files: dict[str, bytes] = {}
    total = {"bytes": 0}
    for file_path in entry["files"]:
        file_url = f"{skill_base_url}/{quote(file_path, safe='/')}"
        try:
            content = await _get_capped(client, file_url, path=file_path, total=total)
            if content is None:
                if file_path.lower() == "skill.md":
                    raise ValueError("well-known SKILL.md could not be downloaded")
                logger.debug("Skipping missing well-known file %s", file_url)
                continue
            files[file_path] = content
        except Exception:
            if file_path.lower() == "skill.md":
                raise
            logger.debug("Skipping failed well-known file %s", file_url, exc_info=True)
    skill_md = files.get("SKILL.md")
    if skill_md is None:
        raise ValueError("well-known SKILL.md could not be downloaded")
    _validate_skill_md(skill_md)
    return files


async def _fetch_v2_well_known_files(
    client: httpx.AsyncClient,
    entry: dict,
) -> dict[str, bytes]:
    if entry["type"] != "skill-md":
        raise ValueError("well-known archive artifacts are not supported yet")

    content = await _get_capped(client, entry["artifact_url"], path="SKILL.md", total={"bytes": 0})
    if content is None:
        raise ValueError("well-known skill artifact could not be downloaded")
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != entry["digest"]:
        raise ValueError("well-known skill artifact digest mismatch")
    _validate_skill_md(content)
    return {"SKILL.md": content}


async def install_well_known_skill(
    install_url: str,
    *,
    skill_name: str | None,
    source: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    """Install a well-known skill into RoomKit's local skills directory.

    The implementation mirrors the public skills CLI discovery contract without
    executing external commands. It downloads only declared files and writes them
    as a local source that RoomKit can discover normally.
    """
    async with httpx.AsyncClient(
        timeout=_WELL_KNOWN_TIMEOUT,
        follow_redirects=True,
        transport=transport,
        event_hooks={"request": [_require_https]},
    ) as client:
        entries = await _fetch_well_known_entries(client, install_url)
        if not entries:
            raise ValueError("No valid well-known skills index was found")
        entry = _select_well_known_entry(entries, skill_name=skill_name, install_url=install_url)
        if entry["version"] == "0.1.0":
            files = await _fetch_legacy_well_known_files(client, entry)
        else:
            files = await _fetch_v2_well_known_files(client, entry)

    dest = well_known_skill_dir(source, entry["name"])
    tmp = dest.with_name(f".{dest.name}.tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        for rel_path, content in files.items():
            if not _is_safe_well_known_file_path(rel_path):
                raise ValueError(f"Unsafe well-known file path: {rel_path}")
            target = tmp / rel_path
            if not _is_subpath(tmp, target):
                raise ValueError(f"Unsafe well-known file path: {rel_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            shutil.rmtree(tmp)
        raise

    logger.info("Installed well-known skill %s from %s into %s", entry["name"], install_url, dest)
    return dest


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
