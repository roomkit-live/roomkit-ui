"""Well-known skill downloads: https only, and bounded while they stream."""

import httpx
import pytest

import roomkit_ui.skill_manager as sm
from roomkit_ui.skills_sh_client import SkillsShSkill

_SKILL_MD = "---\nname: demo\ndescription: d\n---\n\nDo the thing.\n"
_INDEX = {"skills": [{"name": "demo", "description": "d", "files": ["SKILL.md"]}]}


@pytest.fixture
def skills_root(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(sm, "get_skills_dir", lambda: root)
    return root


def _catalog(skill_md_response):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/skills/index.json":
            return httpx.Response(200, json=_INDEX)
        if request.url.path == "/.well-known/skills/demo/SKILL.md":
            return skill_md_response(request)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def _install(url, transport):
    return await sm.install_well_known_skill(
        url, skill_name="demo", source="skills.example.com", transport=transport
    )


async def test_a_plain_http_install_url_is_refused(skills_root):
    transport = _catalog(lambda _r: httpx.Response(200, text=_SKILL_MD))

    with pytest.raises(ValueError, match="https"):
        await _install("http://skills.example.com", transport)


async def test_a_redirect_to_plain_http_is_refused(skills_root):
    # The install URL is https, but the file hops to http on the way.
    transport = _catalog(
        lambda _r: httpx.Response(302, headers={"location": "http://cdn.example.com/SKILL.md"})
    )

    with pytest.raises(ValueError, match="https"):
        await _install("https://skills.example.com", transport)


async def test_an_oversized_file_stops_downloading_at_the_cap(skills_root, monkeypatch):
    monkeypatch.setattr(sm, "_MAX_WELL_KNOWN_FILE_BYTES", 1_000)
    sent = []

    async def endless():
        for _ in range(1_000):
            sent.append(100)
            yield b"x" * 100

    # No Content-Length: only reading the stream can tell the size.
    transport = _catalog(lambda _r: httpx.Response(200, content=endless()))

    with pytest.raises(ValueError, match="too large"):
        await _install("https://skills.example.com", transport)

    assert sum(sent) <= 1_200  # stopped at the cap, not after 100 KB


async def test_a_declared_oversized_file_is_refused_before_reading(skills_root, monkeypatch):
    monkeypatch.setattr(sm, "_MAX_WELL_KNOWN_FILE_BYTES", 1_000)
    transport = _catalog(
        lambda _r: httpx.Response(200, content=b"x" * 10, headers={"content-length": "5000"})
    )

    with pytest.raises(ValueError, match="too large"):
        await _install("https://skills.example.com", transport)


async def test_an_https_install_still_works(skills_root):
    transport = _catalog(lambda _r: httpx.Response(200, text=_SKILL_MD))

    dest = await _install("https://skills.example.com", transport)

    assert (dest / "SKILL.md").read_text() == _SKILL_MD


def test_skills_sh_keeps_only_https_install_urls():
    def parsed(url):
        item = {"source": "skills.example.com", "skillId": "demo", "installUrl": url}
        return SkillsShSkill.from_json(item).install_url

    assert parsed("https://skills.example.com/catalog") == "https://skills.example.com/catalog"
    assert parsed("http://skills.example.com/catalog") is None
