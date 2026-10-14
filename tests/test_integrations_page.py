"""Integration navigation preserves edits, identities and operations in flight."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit

from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.skills_sh_client import SkillsShClient, SkillsShSkill
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.settings.integrations_page import IntegrationsPage
from roomkit_ui.widgets.settings.panel import SettingsPanel


async def test_failed_marketplace_download_stays_installable_after_render(
    qapp, monkeypatch, tmp_path
):
    from roomkit_ui import skill_git, skill_manager

    monkeypatch.setattr(skill_manager, "get_repos_dir", lambda: tmp_path)
    skill = SkillsShSkill(
        id="acme/skills/notes", skill_id="notes", name="Notes", source="acme/skills"
    )

    async def fail_clone(_url):
        raise RuntimeError("Download failed")

    monkeypatch.setattr(skill_git, "clone_repo", fail_clone)
    page = IntegrationsPage({})
    try:
        marketplace = page.skills._marketplace_tab
        marketplace._render([skill])
        await marketplace._do_install(skill)
        assert "Install failed" in marketplace._status.text()
        assert not page.skills._is_marketplace_source_installed(skill)
        marketplace._render([skill])
        assert marketplace._cards[skill.id].action_btn.isEnabled()
        assert len(page.skills._sources) == 1
        dest = tmp_path / skill_manager.repo_dir_name(skill.github_url)

        async def clone(_url):
            dest.mkdir()
            return dest

        monkeypatch.setattr(skill_git, "clone_repo", clone)
        await marketplace._do_install(skill)
        assert page.skills._is_marketplace_source_installed(skill)
        assert len(page.skills._sources) == 1
        marketplace._render([skill])
        assert not marketplace._cards[skill.id].action_btn.isEnabled()
    finally:
        shiboken6.delete(page)


def test_mcp_list_reports_invalid_http_url_as_needing_setup(qapp):
    page = IntegrationsPage(
        {
            "mcp_servers": json.dumps(
                [{"name": "Docs", "transport": "streamable_http", "url": "invalid"}]
            )
        }
    )
    try:
        assert "Needs setup" in page.mcp.catalog.rows[0].accessibleName()
        page.mcp._show_edit(0)
        page.mcp._url_edit.setText("https://example.com/mcp")
        assert "Enabled" in page.mcp.catalog.rows[0].accessibleName()
    finally:
        shiboken6.delete(page)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_existing_cli_fields_stay_readable_after_the_skills_tab_was_rendered(qapp, theme):
    save_settings(
        {
            "cli_tools": json.dumps(
                [{"name": "Git", "command": "git", "description": "Inspect repositories"}]
            )
        }
    )
    apply_theme(theme)
    panel = SettingsPanel()
    try:
        panel.resize(1060, 920)
        panel.show()
        panel._sidebar.select_page("integrations")
        qapp.processEvents()
        panel.grab()
        group = panel.page("integrations")
        group.tabs.bar.setCurrentIndex(1)
        group.cli._show_edit(0)
        qapp.processEvents()
        panel.grab()
        for field in (group.cli._name_edit, group.cli._command_edit, group.cli._description_edit):
            assert field.height() >= field.minimumSizeHint().height()
    finally:
        shiboken6.delete(panel)


@pytest.fixture
def panel(qapp):
    page = SettingsPanel()
    yield page
    shiboken6.delete(page)


@pytest.mark.parametrize(
    ("query", "tab", "subtab", "path"),
    [
        ("installed skills", 2, 0, "skills._my_skills_tab.empty.button"),
        ("skills marketplace", 2, 1, "skills._marketplace_tab._search_input"),
        ("skill sources", 2, 2, "skills.sources.search"),
        ("MCP servers", 0, None, "mcp.catalog.search"),
        ("CLI tools", 1, None, "cli.catalog.search"),
    ],
)
def test_global_search_opens_each_integration_destination(panel, qapp, query, tab, subtab, path):
    panel.show()
    panel.activateWindow()
    qapp.processEvents()
    group = panel.page("integrations")
    group.mcp._add_server()
    group.mcp._name_edit.setText("Unsaved server")
    group.skills._add_source()
    group.skills._label_edit.setText("Unsaved source")
    group.cli._add_tool()
    group.cli._name_edit.setText("Unsaved CLI")
    panel._search.setText(query)
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._stack.currentWidget() is panel._scrolls["integrations"]
    assert group.tabs.bar.currentIndex() == tab
    if subtab is not None:
        assert group.skills.views.currentIndex() == subtab
    assert panel._resolve(group, path).hasFocus()
    assert group.mcp._servers[0]["name"] == "Unsaved server"
    assert group.skills._sources[0]["label"] == "Unsaved source"
    assert group.cli._tools[0]["name"] == "Unsaved CLI"
    assert json.loads(load_settings()["cli_tools"]) == []


def test_all_integration_edits_survive_tabs_live_theme_and_close(panel, qapp):
    group = panel.page("integrations")
    group.mcp._add_server()
    group.mcp._name_edit.setText("Knowledge")
    group.mcp._transport_combo.setCurrentIndex(2)
    group.mcp._url_edit.setText("https://example.com/mcp")
    group.mcp._auth_combo.setCurrentIndex(1)
    group.mcp._oauth_client_secret.setText("test-oauth-secret")
    group.cli._add_tool()
    group.cli._name_edit.setText("Echo")
    group.cli._command_edit.setText("echo")
    group.cli._env_edit.setPlainText("TOKEN=test-cli-secret")
    group.skills._add_source()
    group.skills._label_edit.setText("My sources")
    group.skills._url_edit.setText("https://example.com/skills.git")
    group.skills._on_skill_toggled("Notes", True)
    group.tool_search.threshold.setValue(12)
    expected = group.get_settings()
    cli_field = group.cli._env_edit
    for index in (1, 0, 2):
        group.tabs.bar.setCurrentIndex(index)
        apply_theme("light" if index % 2 else "dark")
        qapp.processEvents()
        assert group.get_settings() == expected
        assert group.cli._env_edit is cli_field
    panel.reject()
    saved = load_settings()
    for key, value in expected.items():
        if key.startswith("tool_search"):  # numbers and a mode, not JSON
            assert str(saved[key]) == str(value)
        else:
            assert json.loads(saved[key]) == json.loads(value)
    assert str(saved["tool_search_threshold"]) == "12"


@pytest.mark.parametrize("kind", ["mcp", "cli", "sources"])
def test_filtering_keeps_original_indices_and_keyboard_manages_the_matching_entry(qapp, kind):
    group = IntegrationsPage({})
    try:
        if kind == "sources":
            page = group.skills
            add, name, catalog = page._add_source, page._label_edit, page.sources
        else:
            page = getattr(group, kind)
            add = page._add_server if kind == "mcp" else page._add_tool
            name, catalog = page._name_edit, page.catalog
        for text in ("First", "Second"):
            add()
            name.setText(text)
        page._show_overview() if kind == "sources" else page._show_list()
        catalog.search.setText("Second")
        assert catalog.rows[0].isHidden()
        assert not catalog.rows[1].isHidden()
        QTest.keyClick(catalog.rows[1].manage, Qt.Key_Space)
        assert page._editing_row == 1
        name.setText("Edited second")
        page._show_overview() if kind == "sources" else page._show_list()
        catalog.rows[1].remove_button.click()
        assert len(catalog.rows) == 1
        assert catalog.rows[0].title.text() == "First"
    finally:
        shiboken6.delete(group)


@pytest.mark.parametrize("tab", [0, 1, 2])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("minimum", [False, True])
def test_lists_and_editors_keep_fields_readable_after_rendering(panel, qapp, tab, theme, minimum):
    apply_theme(theme)
    panel.show()
    panel.resize(panel.minimumSize() if minimum else panel.sizeHint().expandedTo(panel.size()))
    panel._sidebar.select_page("integrations")
    group = panel.page("integrations")
    qapp.processEvents()
    panel.grab()  # Render the initial tab before revealing a hidden editor.
    group.tabs.bar.setCurrentIndex(tab)
    qapp.processEvents()
    assert panel._scrolls["integrations"].horizontalScrollBar().maximum() == 0
    empty = (group.mcp.catalog.empty, group.cli.catalog.empty, group.skills._my_skills_tab.empty)[
        tab
    ]
    for text in (empty.title, empty.description):
        assert text.height() >= text.heightForWidth(text.width())
    if tab == 2:
        page = group.skills
        group.skills._add_source()
    else:
        page = group.mcp if tab == 0 else group.cli
        page._add_server() if tab == 0 else page._add_tool()
    for expanded in (False, True):
        if tab != 2:
            page.advanced.set_expanded(expanded)
        qapp.processEvents()
        assert panel._scrolls["integrations"].horizontalScrollBar().maximum() == 0
        for field in page.findChildren(QLineEdit):
            if field.isVisible():
                minimum_height = (
                    field.fontMetrics().height()
                    if isinstance(field.parentWidget(), QAbstractSpinBox)
                    else field.minimumSizeHint().height()
                )
                assert field.height() >= minimum_height


def test_skill_filters_keep_toggles_and_removing_a_source_keeps_its_files(
    qapp, monkeypatch, tmp_path
):
    import roomkit_ui.skill_manager as manager

    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("Sample skill")
    monkeypatch.setattr(
        manager,
        "discover_all_skills",
        lambda sources: (
            [(SimpleNamespace(name="Notes", description="Summarize notes."), tmp_path, "Local")]
            if sources
            else []
        ),
    )
    group = IntegrationsPage(
        {
            "skill_sources": json.dumps(
                [{"type": "local", "path": str(tmp_path), "label": "Workspace"}]
            )
        }
    )
    try:
        skills = group.skills._my_skills_tab
        card = skills._cards[0]
        card.checkbox.click()
        skills.search.setText("unknown")
        assert card.isHidden()
        skills.search.clear()
        assert card.checkbox.isChecked()
        assert skills._cards[0] is card
        assert group.skills._enabled == {"Notes"}
        group.skills._remove_source(0)
        assert skill_file.exists()
        assert group.skills._sources == []
    finally:
        shiboken6.delete(group)


async def test_git_completion_updates_its_source_when_another_is_being_edited(
    qapp, monkeypatch, tmp_path
):
    import roomkit_ui.skill_git as git
    import roomkit_ui.skill_manager as manager

    gate = asyncio.Event()
    monkeypatch.setattr(manager, "get_repos_dir", lambda: tmp_path)

    async def clone(url):
        await gate.wait()
        (tmp_path / manager.repo_dir_name(url)).mkdir()

    monkeypatch.setattr(git, "clone_repo", clone)
    group = IntegrationsPage({})
    try:
        page = group.skills
        page._add_source()
        page._url_edit.setText("https://example.com/first.git")
        before = asyncio.all_tasks()
        page._on_clone_update()
        tasks = asyncio.all_tasks() - before
        page._add_source()
        page._url_edit.setText("https://example.com/second.git")
        gate.set()
        await asyncio.gather(*tasks)
        assert page._action_status.text() == ""
        assert page._clone_btn.isEnabled()
        assert page._clone_btn.text() == "Download source"
        page._show_edit(0)
        assert page._action_status.text() == "Downloaded successfully"
        assert page._clone_btn.text() == "Update source"
    finally:
        shiboken6.delete(group)


def test_row_actions_follow_the_entry_after_removing_an_earlier_row(qapp):
    group = IntegrationsPage({})
    try:
        page = group.mcp
        for name in ("First", "Second", "Third"):
            page._add_server()
            page._name_edit.setText(name)
        page._show_list()
        page.catalog.rows[0].remove_button.click()
        page.catalog.rows[1].manage.click()
        assert page._editing_row == 1
        assert page._name_edit.text() == "Third"
        page._show_list()
        page.catalog.rows[0].remove_button.click()
        assert [server["name"] for server in page._servers] == ["Third"]
    finally:
        shiboken6.delete(group)


def test_empty_integration_actions_open_the_matching_editor(panel, qapp):
    panel.show()
    panel.activateWindow()
    panel._navigate("integrations")
    qapp.processEvents()
    group = panel.page("integrations")
    assert group.tabs.bar.currentIndex() == 0
    for index, page in enumerate((group.mcp, group.cli)):
        group.tabs.bar.setCurrentIndex(index)
        assert page.catalog.empty.isVisible()
        assert not page.catalog.search.isVisible()
        QTest.keyClick(page.catalog.empty.button, Qt.Key_Space)
        qapp.processEvents()
        assert page._name_edit.isVisible()
        assert page._name_edit.hasFocus()
    group.tabs.bar.setCurrentIndex(2)
    group.skills._my_skills_tab.empty.button.click()
    assert group.skills._type_combo.isVisible()
    assert group.skills._editing_row == 0
    group.skills._show_overview()
    group.skills.show_view(0)
    group.skills.sources_link.click()
    assert group.skills.views.currentIndex() == 2
    group.skills.overview_back.click()
    assert group.skills.views.currentIndex() == 0


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("installed_count", [0, 12])
def test_skills_sh_is_reachable_without_scrolling(
    qapp, monkeypatch, tmp_path, theme, installed_count
):
    from roomkit_ui import skill_manager

    monkeypatch.setattr(
        skill_manager,
        "discover_all_skills",
        lambda sources: [
            (SimpleNamespace(name=f"Skill {i}", description="Instructions."), tmp_path, "Local")
            for i in range(installed_count)
        ],
    )
    apply_theme(theme)
    panel = SettingsPanel()
    try:
        panel.resize(panel.minimumSize())
        panel.show()
        panel.activateWindow()
        panel._navigate("integrations")
        panel.page("integrations").tabs.bar.setCurrentIndex(2)
        qapp.processEvents()
        panel.grab()
        skills = panel.page("integrations").skills
        before = skills.get_settings()
        browse = skills._my_skills_tab.browse_marketplace
        scroll = panel._scrolls["integrations"]
        viewport = scroll.viewport()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().value() == 0
        assert browse.isVisible()
        assert "skills.sh" in browse.text()
        for point in (browse.rect().topLeft(), browse.rect().bottomRight()):
            assert viewport.rect().contains(browse.mapTo(viewport, point))

        QTest.keyClick(browse, Qt.Key_Space)
        qapp.processEvents()
        assert skills.views.currentIndex() == 1
        assert skills._marketplace_tab.loaded
        assert skills._marketplace_tab._search_input.hasFocus()
        assert scroll.horizontalScrollBar().maximum() == 0
        skills.overview_back.click()
        qapp.processEvents()
        assert skills.views.currentIndex() == 0
        assert len(skills._my_skills_tab._cards) == installed_count
        assert skills.get_settings() == before
    finally:
        shiboken6.delete(panel)


async def test_skills_sh_search_install_and_return_to_installed_skills(
    qapp, qtbot, monkeypatch, tmp_path
):
    from roomkit_ui import skill_git, skill_manager

    monkeypatch.setattr(skill_manager, "get_repos_dir", lambda: tmp_path)
    skill = SkillsShSkill(
        id="acme/skills/notes", skill_id="notes", name="notes", source="acme/skills"
    )
    queries = []

    async def search(_client, query, *, limit=50):
        queries.append(query)
        return [skill]

    async def clone(url):
        dest = tmp_path / skill_manager.repo_dir_name(url)
        dest.mkdir()
        (dest / "SKILL.md").write_text(
            "---\nname: notes\ndescription: Summarize notes.\n---\nWrite a short summary.\n"
        )
        return dest

    monkeypatch.setattr(SkillsShClient, "search", search)
    monkeypatch.setattr(skill_git, "clone_repo", clone)
    panel = SettingsPanel()
    try:
        panel.show()
        panel._navigate("integrations")
        panel.page("integrations").tabs.bar.setCurrentIndex(2)
        skills = panel.page("integrations").skills
        skills._my_skills_tab.browse_marketplace.click()
        marketplace = skills._marketplace_tab
        before = asyncio.all_tasks()
        QTest.keyClicks(marketplace._search_input, "notes")
        qtbot.wait(450)
        await asyncio.gather(*(asyncio.all_tasks() - before))
        assert queries == ["notes"]
        card = marketplace._cards[skill.id]
        assert card.action_btn.isEnabled()

        before = asyncio.all_tasks()
        card.action_btn.click()
        await asyncio.gather(*(asyncio.all_tasks() - before))
        assert card.action_btn.text() == "Installed ✓"
        skills.overview_back.click()
        qapp.processEvents()
        [installed] = skills._my_skills_tab._cards
        assert installed.name == "notes"
        installed.checkbox.click()
        panel.reject()
        saved = load_settings()
        assert json.loads(saved["enabled_skills"]) == ["notes"]
        assert json.loads(saved["skill_sources"])[0]["url"] == skill.github_url
    finally:
        shiboken6.delete(panel)
