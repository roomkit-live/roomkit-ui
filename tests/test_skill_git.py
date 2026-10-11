"""Git clone / pull of skill sources, against real local repositories."""

import shutil
import subprocess

import pytest

import roomkit_ui.skill_manager as sm

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

_GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.test"]

# Set by git for the hooks and `rebase --exec` commands it runs — and pytest
# is often one of them. Inherited, they point every git below at the
# repository under development: `git init` there rewrote its config.
_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


@pytest.fixture(autouse=True)
def isolated_from_the_enclosing_repo(monkeypatch):
    for var in _GIT_REDIRECTS:
        monkeypatch.delenv(var, raising=False)


def _git(*args, cwd=None):
    subprocess.run(["git", *_GIT_ID, *args], cwd=cwd, check=True, capture_output=True)


def _make_repo(path, skill="demo"):
    """A repo holding one skill, committed."""
    (path / skill).mkdir(parents=True)
    (path / skill / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: d\n---\n")
    _git("init", "-q", str(path))
    _git("add", ".", cwd=path)
    _git("commit", "-q", "-m", "init", cwd=path)
    return path


@pytest.fixture
def skills_root(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(sm, "get_skills_dir", lambda: root)
    return root


@pytest.mark.parametrize(
    "url",
    ["https://h/..", "https://h/.", "https://h/../..", "https://h/", "git@h:..", "https://h"],
)
def test_repo_dir_name_never_names_the_repos_dir_or_its_parent(url):
    name = sm.repo_dir_name(url)

    assert name not in ("", ".", "..")
    assert "/" not in name and "\\" not in name


def test_repo_dir_name_keeps_one_segment_per_path_part():
    assert sm.repo_dir_name("https://h/org/..") == "org"
    assert sm.repo_dir_name("https://h/a\\..\\b/repo") == "a-..-b--repo"


async def test_clone_installs_a_repo(skills_root, tmp_path):
    upstream = _make_repo(tmp_path / "up")

    dest = await sm.clone_repo(upstream.as_uri())

    assert dest.parent == skills_root / "repos"
    assert (dest / "demo" / "SKILL.md").exists()
    assert [p.name for p in skills_root.iterdir()] == ["repos"]  # no staging left


async def test_a_failed_reclone_keeps_the_installed_skills(skills_root, tmp_path):
    upstream = _make_repo(tmp_path / "up")
    dest = await sm.clone_repo(upstream.as_uri())
    shutil.rmtree(upstream)  # the remote is gone: the next clone fails

    with pytest.raises(RuntimeError, match="clone failed"):
        await sm.clone_repo(upstream.as_uri())

    assert (dest / "demo" / "SKILL.md").exists()
    assert [p.name for p in skills_root.iterdir()] == ["repos"]


async def test_a_url_starting_with_a_dash_is_not_read_as_an_option(skills_root, tmp_path):
    marker = tmp_path / "pwned"

    with pytest.raises(RuntimeError):
        await sm.clone_repo(f"--upload-pack=touch {marker}")

    assert not marker.exists()


async def test_pull_does_not_act_on_an_enclosing_repository(skills_root, tmp_path):
    # The skills folder lives inside a repo (a home directory kept in git):
    # `git -C <not a clone> pull` used to walk up and pull that one instead.
    upstream = _make_repo(tmp_path / "up")
    _git("clone", "-q", str(upstream), str(tmp_path / "home"))
    enclosing = tmp_path / "home"
    (upstream / "new.txt").write_text("x")
    _git("add", ".", cwd=upstream)
    _git("commit", "-q", "-m", "more", cwd=upstream)
    not_a_clone = enclosing / "skills" / "repos" / "org--repo"
    not_a_clone.mkdir(parents=True)

    ok = await sm.pull_repo(not_a_clone)

    assert ok is False
    assert not (enclosing / "new.txt").exists()


async def test_pull_updates_a_clone(skills_root, tmp_path):
    upstream = _make_repo(tmp_path / "up")
    dest = await sm.clone_repo(upstream.as_uri())
    (upstream / "new.txt").write_text("x")
    _git("add", ".", cwd=upstream)
    _git("commit", "-q", "-m", "more", cwd=upstream)

    assert await sm.pull_repo(dest) is True
    assert (dest / "new.txt").exists()
