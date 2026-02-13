"""Async client for the ClawHub skill marketplace API."""

from __future__ import annotations

import asyncio
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx

from roomkit_ui.skill_manager import get_clawhub_dir

logger = logging.getLogger(__name__)

BASE_URL = "https://wry-manatee-359.convex.site/api/v1"
_TIMEOUT = 30.0


@dataclass
class ClawHubSkillInfo:
    """Lightweight representation of a skill from the marketplace."""

    slug: str
    display_name: str
    summary: str | None = None
    version: str | None = None
    downloads: int = 0
    stars: int = 0
    tags: list[str] = field(default_factory=list)


class ClawHubClient:
    """Async HTTP client for the ClawHub marketplace."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    async def search(self, query: str) -> list[ClawHubSkillInfo]:
        """Search for skills matching *query*."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{self._base_url}/search", params={"q": query})
            resp.raise_for_status()
            data = resp.json()
        return [self._parse_item(item) for item in data.get("items", data.get("results", []))]

    async def list_skills(
        self, cursor: str | None = None
    ) -> tuple[list[ClawHubSkillInfo], str | None]:
        """List skills (paginated). Returns ``(items, next_cursor)``."""
        params: dict[str, str] = {}
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{self._base_url}/skills", params=params)
            resp.raise_for_status()
            data = resp.json()
        items = [self._parse_item(item) for item in data.get("items", data.get("results", []))]
        next_cursor = data.get("next_cursor") or data.get("next") or None
        return items, next_cursor

    async def download_skill(self, slug: str, version: str | None = None) -> Path:
        """Download and extract a skill ZIP into the ClawHub skills directory.

        Returns the extracted directory path.
        """
        dest = get_clawhub_dir() / slug
        params: dict[str, str] = {"slug": slug}
        if version:
            params["version"] = version
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{self._base_url}/download",
                params=params,
            )
            resp.raise_for_status()
            content = resp.content

        def _extract() -> Path:
            with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                with zipfile.ZipFile(tmp_path) as zf:
                    # Clear previous install
                    if dest.exists():
                        import shutil

                        shutil.rmtree(dest)
                    dest.mkdir(parents=True, exist_ok=True)
                    zf.extractall(dest)
            finally:
                tmp_path.unlink(missing_ok=True)
            logger.info("Installed ClawHub skill %s → %s", slug, dest)
            return dest

        return await asyncio.to_thread(_extract)

    @staticmethod
    def _parse_item(item: dict) -> ClawHubSkillInfo:
        return ClawHubSkillInfo(
            slug=item.get("slug") or item.get("name") or "",
            display_name=item.get("display_name") or item.get("name") or item.get("slug") or "",
            summary=item.get("summary") or item.get("description"),
            version=item.get("version"),
            downloads=int(item.get("downloads", 0)),
            stars=int(item.get("stars", 0)),
            tags=item.get("tags", []),
        )
