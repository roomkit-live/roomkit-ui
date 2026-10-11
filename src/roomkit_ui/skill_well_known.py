"""Install a skill published at a site's ``/.well-known/`` skills index.

https only (redirects included), every download streamed under a byte cap,
file paths confined to the skill's own folder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import httpx

from roomkit_ui.skill_manager import well_known_skill_dir

logger = logging.getLogger(__name__)

_DISCOVERY_SCHEMA_V2 = "https://schemas.agentskills.io/discovery/0.2.0/schema.json"
_WELL_KNOWN_PATHS = (".well-known/agent-skills", ".well-known/skills")
_WELL_KNOWN_TIMEOUT = 20.0
_MAX_WELL_KNOWN_FILES = 500
_MAX_WELL_KNOWN_FILE_BYTES = 5 * 1024 * 1024
_MAX_WELL_KNOWN_TOTAL_BYTES = 50 * 1024 * 1024
_WELL_KNOWN_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


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
