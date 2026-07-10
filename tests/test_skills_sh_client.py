"""Tests for skills.sh public search parsing."""

import httpx
import pytest

from roomkit_ui.skills_sh_client import SkillsShClient, SkillsShSkill


def test_skills_sh_skill_github_urls():
    skill = SkillsShSkill(
        id="vercel-labs/agent-skills/react",
        skill_id="react",
        name="React",
        source="vercel-labs/agent-skills",
        installs=123,
    )
    assert skill.is_github_source is True
    assert skill.github_url == "https://github.com/vercel-labs/agent-skills"
    assert skill.page_url == "https://skills.sh/vercel-labs/agent-skills/react"


def test_skills_sh_skill_well_known_url():
    skill = SkillsShSkill(
        id="skills.example.com/example",
        skill_id="example",
        name="Example",
        source="skills.example.com",
    )
    assert skill.is_github_source is False
    assert skill.github_url is None
    assert skill.page_url == "https://skills.sh/site/skills.example.com/example"


@pytest.mark.asyncio
async def test_skills_sh_client_search_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/search"
        assert request.url.params["q"] == "react"
        assert request.url.params["limit"] == "3"
        return httpx.Response(
            200,
            json={
                "query": "react",
                "skills": [
                    {
                        "id": "vercel-labs/agent-skills/vercel-react-best-practices",
                        "skillId": "vercel-react-best-practices",
                        "name": "vercel-react-best-practices",
                        "installs": 538551,
                        "source": "vercel-labs/agent-skills",
                    },
                    {"name": "invalid"},
                ],
            },
        )

    client = SkillsShClient(transport=httpx.MockTransport(handler))
    results = await client.search("react", limit=3)

    assert len(results) == 1
    assert results[0].name == "vercel-react-best-practices"
    assert results[0].github_url == "https://github.com/vercel-labs/agent-skills"


@pytest.mark.asyncio
async def test_skills_sh_client_skips_short_queries():
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("short query should not call HTTP")

    client = SkillsShClient(transport=httpx.MockTransport(handler))
    assert await client.search("r") == []
