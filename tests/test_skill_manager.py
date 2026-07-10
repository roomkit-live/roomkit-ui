"""Tests for skill discovery across git/local sources."""

import hashlib

import httpx
import pytest

import roomkit_ui.skill_manager as sm

_SKILL_MD = """---
name: {name}
description: {desc}
---

# Instructions

Do the thing.
"""


def _write_skill(dirpath, name, desc="A test skill."):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "SKILL.md").write_text(_SKILL_MD.format(name=name, desc=desc))


@pytest.fixture
def skills_root(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(sm, "get_skills_dir", lambda: root)
    return root


def test_repo_dir_name_variants():
    assert sm.repo_dir_name("https://github.com/org/repo") == "org--repo"
    assert sm.repo_dir_name("https://github.com/org/repo.git") == "org--repo"
    assert sm.repo_dir_name("git@github.com:org/repo.git") == "org--repo"
    assert sm.repo_dir_name("https://github.com/solo") == "solo"


def test_discover_git_source(skills_root):
    # Strict parser requires directory name == skill name.
    _write_skill(skills_root / "repos" / "org--repo" / "my-skill", "my-skill")
    found = sm.discover_all_skills([{"type": "git", "url": "https://github.com/org/repo"}])
    assert len(found) == 1
    meta, path, label = found[0]
    assert meta.name == "my-skill"
    assert path.name == "my-skill"
    assert label.startswith("git")


def test_discover_local_lenient_slug_mismatch(tmp_path, skills_root):
    # Imported marketplace skills can be stored under a slug that differs
    # from the skill name; discovery must fall back to the lenient parser.
    local = tmp_path / "imported-skills"
    _write_skill(local / "some-slug-123", "real-name")
    found = sm.discover_all_skills([{"type": "local", "path": str(local)}])
    assert len(found) == 1
    assert found[0][0].name == "real-name"
    assert found[0][2].startswith("local")


def test_discover_local_source(tmp_path, skills_root):
    local = tmp_path / "my-local-skills"
    _write_skill(local / "helper", "helper")
    found = sm.discover_all_skills([{"type": "local", "path": str(local)}])
    assert [m.name for m, _, _ in found] == ["helper"]


def test_discover_skips_missing_and_unknown_sources(skills_root):
    found = sm.discover_all_skills(
        [
            {"type": "git", "url": "https://github.com/never/cloned"},
            {"type": "local", "path": "/nonexistent/path"},
            {"type": "wat"},
        ]
    )
    assert found == []


def test_discover_skips_invalid_skill_md(skills_root):
    bad = skills_root / "invalid" / "broken"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("no frontmatter at all")
    assert sm.discover_all_skills([{"type": "local", "path": str(bad.parent)}]) == []


def test_build_registry_filters_by_enabled_names(skills_root):
    local = skills_root / "local"
    _write_skill(local / "skill-a", "skill-a")
    _write_skill(local / "skill-b", "skill-b")
    registry = sm.build_registry(
        [{"type": "local", "path": str(local)}], enabled_names=["skill-a"]
    )
    assert registry.skill_names == ["skill-a"]


@pytest.mark.asyncio
async def test_install_well_known_legacy_skill(skills_root):
    skill_md = _SKILL_MD.format(name="demo", desc="Downloaded skill.")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/catalog/.well-known/agent-skills/index.json":
            return httpx.Response(404)
        if path == "/catalog/.well-known/skills/index.json":
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {
                            "name": "demo",
                            "description": "Downloaded skill.",
                            "files": ["SKILL.md", "scripts/run.py"],
                        }
                    ]
                },
            )
        if path == "/catalog/.well-known/skills/demo/SKILL.md":
            return httpx.Response(200, text=skill_md)
        if path == "/catalog/.well-known/skills/demo/scripts/run.py":
            return httpx.Response(200, content=b"print('ok')\n")
        return httpx.Response(404)

    dest = await sm.install_well_known_skill(
        "https://skills.example.com/catalog",
        skill_name="demo",
        source="skills.example.com",
        transport=httpx.MockTransport(handler),
    )

    assert dest == sm.well_known_skill_dir("skills.example.com", "demo")
    assert (dest / "SKILL.md").read_text() == skill_md
    assert (dest / "scripts" / "run.py").read_bytes() == b"print('ok')\n"
    found = sm.discover_all_skills([{"type": "local", "path": str(dest)}])
    assert [meta.name for meta, _path, _label in found] == ["demo"]


@pytest.mark.asyncio
async def test_install_well_known_v2_skill_md(skills_root):
    skill_md = _SKILL_MD.format(name="v2-demo", desc="Downloaded v2 skill.")
    digest = f"sha256:{hashlib.sha256(skill_md.encode()).hexdigest()}"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/agent-skills/index.json":
            return httpx.Response(
                200,
                json={
                    "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
                    "skills": [
                        {
                            "name": "v2-demo",
                            "description": "Downloaded v2 skill.",
                            "type": "skill-md",
                            "url": "v2-demo.md",
                            "digest": digest,
                        }
                    ],
                },
            )
        if path == "/.well-known/agent-skills/v2-demo.md":
            return httpx.Response(200, text=skill_md)
        return httpx.Response(404)

    dest = await sm.install_well_known_skill(
        "https://skills.example.com",
        skill_name="v2-demo",
        source="skills.example.com",
        transport=httpx.MockTransport(handler),
    )

    assert (dest / "SKILL.md").read_text() == skill_md


@pytest.mark.asyncio
async def test_install_well_known_rejects_unsafe_legacy_paths(skills_root):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-skills/index.json":
            return httpx.Response(404)
        if request.url.path == "/.well-known/skills/index.json":
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {
                            "name": "demo",
                            "description": "Downloaded skill.",
                            "files": ["SKILL.md", "../escape.py"],
                        }
                    ]
                },
            )
        return httpx.Response(404)

    with pytest.raises(ValueError, match="No valid well-known skills index"):
        await sm.install_well_known_skill(
            "https://skills.example.com",
            skill_name="demo",
            source="skills.example.com",
            transport=httpx.MockTransport(handler),
        )
