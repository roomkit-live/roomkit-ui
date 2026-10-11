"""Settings pages outlived by their own background work.

The Settings dialog is destroyed when it closes, while a skills.sh search,
an install or a git clone it started may still be running.  Whatever such
a task does on completion must not reach into the destroyed widgets.
"""

from __future__ import annotations

import asyncio

import pytest
import shiboken6

import roomkit_ui.skill_manager as skill_manager
import roomkit_ui.widgets.settings.skills.marketplace as marketplace_mod
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.skills_sh_client import SkillsShSkill
from roomkit_ui.widgets.settings.audio_debug_page import _HAS_MULTIMEDIA, _AudioDebugPage
from roomkit_ui.widgets.settings.skills import _SkillsPage
from roomkit_ui.widgets.settings.skills.marketplace import MarketplaceTab
from roomkit_ui.widgets.settings.speakers_page import _SpeakersPage

SKILL = SkillsShSkill(
    id="acme/skills/pdf", skill_id="pdf", name="PDF", source="acme/skills", installs=3
)


async def test_a_search_answered_after_the_dialog_closed_is_dropped(qapp, monkeypatch):
    tab = MarketplaceTab()

    async def search(_client, _query, *, limit=50):
        shiboken6.delete(tab)  # Settings closed while the request was in flight
        return [SKILL]

    monkeypatch.setattr(marketplace_mod.SkillsShClient, "search", search)

    await tab._run_search("pdf")  # must not raise on the destroyed widgets


async def test_an_install_finishing_after_the_dialog_closed_is_dropped(qapp):
    async def install(_skill):
        shiboken6.delete(tab)  # Settings closed while the clone ran

    tab = MarketplaceTab(on_install_source=install)
    tab._render([SKILL])
    card = tab._flow.itemAt(0).widget()

    await tab._do_install(SKILL, card)  # must not raise on the destroyed widgets


async def test_a_clone_finishing_after_the_dialog_closed_is_dropped(qapp, monkeypatch, tmp_path):
    page = _SkillsPage(dict(_DEFAULTS))

    async def clone_repo(_url):
        shiboken6.delete(page)  # Settings closed while git ran

    monkeypatch.setattr(skill_manager, "clone_repo", clone_repo)
    monkeypatch.setattr(skill_manager, "get_repos_dir", lambda: tmp_path)

    await page._run_git_op("https://github.com/acme/skills")  # must not raise


async def test_a_voice_test_finishing_after_the_dialog_closed_is_dropped(qapp, monkeypatch):
    import roomkit_ui.enrollment as enrollment
    import roomkit_ui.speaker_manager as speaker_manager

    page = _SpeakersPage(dict(_DEFAULTS))
    page._get_model_path = lambda: "speaker.onnx"
    monkeypatch.setattr(
        speaker_manager,
        "load_speakers",
        lambda: [speaker_manager.SpeakerProfile(name="Ann", embeddings=[[1.0, 0.0]])],
    )

    async def record_and_extract(*_args, **_kwargs):
        shiboken6.delete(page)  # Settings closed during the 3 s recording
        return [1.0, 0.0]

    monkeypatch.setattr(enrollment, "record_and_extract", record_and_extract)

    page._on_test()
    started = asyncio.all_tasks() - {asyncio.current_task()}
    await asyncio.gather(*started)  # must not raise on the destroyed widgets


@pytest.mark.skipif(not _HAS_MULTIMEDIA, reason="PySide6 QtMultimedia not installed")
def test_the_audio_player_goes_away_with_the_page(qapp):
    page = _AudioDebugPage(dict(_DEFAULTS))
    player, output = page._player, page._audio_output

    shiboken6.delete(page)

    assert not shiboken6.isValid(player)
    assert not shiboken6.isValid(output)
