"""Client for the public skills.sh search endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from html import unescape
from urllib.parse import urlparse

import httpx

BASE_URL = "https://skills.sh"
_TIMEOUT = 15.0
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$", re.IGNORECASE)
_INSTALL_CMD_RE = re.compile(r"npx\s+skills\s+add\s+(https?://[^\s<\"']+)", re.IGNORECASE)


@dataclass(frozen=True)
class SkillsShSkill:
    """A skill returned by skills.sh public search."""

    id: str
    skill_id: str
    name: str
    source: str
    installs: int = 0
    is_duplicate: bool = False
    install_url: str | None = None

    @property
    def is_github_source(self) -> bool:
        parts = self.source.split("/")
        return len(parts) == 2 and all(parts)

    @property
    def github_url(self) -> str | None:
        if not self.is_github_source:
            return None
        return f"https://github.com/{self.source}"

    @property
    def is_well_known_source(self) -> bool:
        return _DOMAIN_RE.match(self.source) is not None

    @property
    def resolved_install_url(self) -> str | None:
        return self.github_url or self.install_url

    @property
    def page_url(self) -> str:
        source = self.source.lower()
        skill_id = self.skill_id.lower()
        if _DOMAIN_RE.match(source):
            return f"{BASE_URL}/site/{source}/{skill_id}"
        if self.is_github_source:
            owner, repo = source.split("/", 1)
            return f"{BASE_URL}/{owner}/{repo}/{skill_id}"
        return BASE_URL

    @classmethod
    def from_json(cls, item: dict) -> SkillsShSkill | None:
        source = str(item.get("source") or "").strip()
        skill_id = str(item.get("skillId") or item.get("slug") or "").strip()
        name = str(item.get("name") or skill_id).strip()
        if not source or not skill_id or not name:
            return None
        try:
            installs = int(item.get("installs", 0) or 0)
        except (TypeError, ValueError):
            installs = 0
        return cls(
            id=str(item.get("id") or f"{source}/{skill_id}"),
            skill_id=skill_id,
            name=name,
            source=source,
            installs=installs,
            is_duplicate=bool(item.get("isDuplicate", False)),
            install_url=_valid_http_url(item.get("installUrl") or item.get("install_url")),
        )


class SkillsShClient:
    """Async client for skills.sh's public search surface."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def search(self, query: str, *, limit: int = 50) -> list[SkillsShSkill]:
        """Search skills.sh using the public endpoint used by the website."""
        query = query.strip()
        if len(query) < 2:
            return []
        params = {"q": query, "limit": str(max(1, min(limit, 100)))}
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            resp = await client.get(f"{self._base_url}/api/search", params=params)
            resp.raise_for_status()
            data = resp.json()
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            return []
        parsed = [SkillsShSkill.from_json(item) for item in skills if isinstance(item, dict)]
        return [skill for skill in parsed if skill is not None]

    async def with_install_url(self, skill: SkillsShSkill) -> SkillsShSkill:
        """Return *skill* with the best install URL available from the public page."""
        if skill.resolved_install_url:
            return skill
        if not skill.is_well_known_source:
            return skill

        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            resp = await client.get(skill.page_url)
            resp.raise_for_status()

        install_url = _extract_install_url(resp.text)
        return replace(skill, install_url=install_url)


def _valid_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _extract_install_url(page_html: str) -> str | None:
    """Extract the public ``npx skills add`` URL rendered on a skills.sh page."""
    html = unescape(page_html)
    match = _INSTALL_CMD_RE.search(html)
    if match:
        return _valid_http_url(match.group(1))
    return None
