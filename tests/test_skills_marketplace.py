"""skills.sh marketplace tab: searches and installs that overlap."""

from __future__ import annotations

import asyncio

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent

import roomkit_ui.widgets.settings.skills.marketplace as marketplace_mod
from roomkit_ui.skills_sh_client import SkillsShSkill
from roomkit_ui.widgets.settings.skills.marketplace import MarketplaceTab
from roomkit_ui.widgets.settings.skills.widgets import SkillCard


def _skill(name: str) -> SkillsShSkill:
    return SkillsShSkill(id=f"acme/skills/{name}", skill_id=name, name=name, source="acme/skills")


def _flush_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class _ControlledSearch:
    """skills.sh search whose answer, per query, lands only when released."""

    def __init__(self) -> None:
        self._gates: dict[str, asyncio.Event] = {}

    def release(self, query: str) -> None:
        self._gates.setdefault(query, asyncio.Event()).set()

    async def answer(self, query: str) -> list[SkillsShSkill]:
        await self._gates.setdefault(query, asyncio.Event()).wait()
        return [_skill(f"{query}-result")]


@pytest.fixture
def tab(qapp):
    t = MarketplaceTab()
    yield t
    if shiboken6.isValid(t):
        shiboken6.delete(t)


@pytest.fixture
def search(monkeypatch) -> _ControlledSearch:
    controlled = _ControlledSearch()

    async def fake_search(_client, query: str, *, limit: int = 50) -> list[SkillsShSkill]:
        return await controlled.answer(query)

    monkeypatch.setattr(marketplace_mod.SkillsShClient, "search", fake_search)
    return controlled


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def _finish_tasks() -> None:
    """Run what the tab started to completion, re-raising what it raised."""
    await asyncio.gather(*(asyncio.all_tasks() - {asyncio.current_task()}))


def _cards(tab: MarketplaceTab) -> list[SkillCard]:
    return [tab._flow.itemAt(i).widget() for i in range(tab._flow.count())]


def _card_names(tab: MarketplaceTab) -> list[str]:
    return [card.slug for card in _cards(tab)]


# -- searches ------------------------------------------------------------------


async def test_a_slow_older_search_does_not_overwrite_the_latest(tab, search):
    tab._do_search("pd")
    tab._do_search("pdf")

    search.release("pdf")
    await _settle()
    search.release("pd")  # the older query answers last
    await _settle()

    assert [s.skill_id for s in tab._results] == ["pdf-result"]
    assert _card_names(tab) == ["pdf-result"]
    assert tab._status.text() == "1 results"


async def test_clearing_the_query_drops_the_search_in_flight(tab, search):
    tab._do_search("pdf")
    tab._do_search("p")  # too short: the grid is cleared

    search.release("pdf")
    await _settle()

    assert tab._results == []
    assert _card_names(tab) == []


# -- installs ------------------------------------------------------------------


async def test_an_install_lands_on_the_card_a_new_search_put_in_place(qapp):
    gate = asyncio.Event()

    async def install(_skill):
        await gate.wait()

    tab = MarketplaceTab(on_install_source=install)
    skill = _skill("pdf")
    tab._render([skill])
    tab._install_skill_source(skill, _cards(tab)[0])

    tab._render([skill])  # a search re-renders the grid mid-install
    _flush_deletes()
    [replacement] = _cards(tab)
    assert replacement.action_btn.text() == "Installing..."

    gate.set()
    await _finish_tasks()

    assert replacement.action_btn.text() == "Installed ✓"
    shiboken6.delete(tab)


async def test_a_failed_install_whose_card_is_gone_reports_in_the_status(qapp):
    async def install(_skill):
        tab._render([])  # the skill dropped out of a newer search
        _flush_deletes()
        raise RuntimeError("git clone failed")

    tab = MarketplaceTab(on_install_source=install)
    skill = _skill("pdf")
    tab._render([skill])
    tab._install_skill_source(skill, _cards(tab)[0])

    await _finish_tasks()  # the install must not raise on the deleted card

    assert tab._status.text() == "Install failed: git clone failed"
    shiboken6.delete(tab)
