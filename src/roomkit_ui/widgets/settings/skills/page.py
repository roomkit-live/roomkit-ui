"""Skill activation, marketplace and sources inside Settings integrations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from roomkit_ui.skills_sh_client import SkillsShClient, SkillsShSkill
from roomkit_ui.widgets.settings.controls import (
    FeedbackLabel,
    SettingsForm,
    SettingsSection,
    label,
    navigation_link,
)
from roomkit_ui.widgets.settings.integration_controls import (
    DetailStack,
    IntegrationCatalog,
)
from roomkit_ui.widgets.settings.skills.marketplace import MarketplaceTab
from roomkit_ui.widgets.settings.skills.my_skills import MySkillsTab


class _SkillsPage(QWidget):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        try:
            raw = json.loads(settings.get("skill_sources", "[]"))
        except (json.JSONDecodeError, TypeError):
            raw = []
        self._sources = (
            [s for s in raw if isinstance(s, dict) and s.get("type") in {"git", "local"}]
            if isinstance(raw, list)
            else []
        )
        try:
            raw_enabled = json.loads(settings.get("enabled_skills", "[]"))
        except (json.JSONDecodeError, TypeError):
            raw_enabled = []
        self._enabled = (
            {name for name in raw_enabled if isinstance(name, str)}
            if isinstance(raw_enabled, list)
            else set()
        )
        self._editing_row = -1
        self._git_states: dict[str, tuple[str, str, bool]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._stack = DetailStack()
        layout.addWidget(self._stack)
        self._my_skills_tab = MySkillsTab(
            on_skill_toggled=self._on_skill_toggled,
            on_refresh=self._refresh_skills,
            on_add_source=self._add_source,
            on_browse_marketplace=self._browse_marketplace,
        )
        self._marketplace_tab = MarketplaceTab(
            on_install_source=self._install_marketplace_source,
            is_source_installed=self._is_marketplace_source_installed,
        )
        self.sources = IntegrationCatalog(
            "Skill sources",
            "Read skills from a Git repository or a local folder. "
            "Removing a source here keeps its files on disk.",
            "+ Add source",
            "No skill sources yet",
            "Add a local folder or a Git repository to discover skills.",
            "sparkles",
        )
        self.sources.add_requested.connect(self._add_source)
        self.sources.edit_requested.connect(self._show_edit)
        self.sources.remove_requested.connect(self._remove_source)
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(20)
        self.overview_back = navigation_link("← Back to skills")
        self.overview_back.clicked.connect(lambda: self.show_view(0))
        self.overview_back.hide()
        overview_layout.addWidget(self.overview_back, 0, Qt.AlignLeft)
        self.views = DetailStack()
        for view in (self._my_skills_tab, self._marketplace_tab, self.sources):
            self.views.addWidget(view)
        overview_layout.addWidget(self.views)
        self.sources_link = navigation_link("Manage sources →")
        self.sources_link.clicked.connect(lambda: self.show_view(2))
        overview_layout.addWidget(self.sources_link, 0, Qt.AlignLeft)
        self._stack.addWidget(overview)

        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(20)
        self.back_button = navigation_link("← Back to sources")
        self.back_button.clicked.connect(self._show_overview)
        edit_layout.addWidget(self.back_button, 0, Qt.AlignLeft)
        self._edit_title = label("", "settingsSectionTitle")
        self._edit_title.setTextFormat(Qt.PlainText)
        edit_layout.addWidget(self._edit_title)
        section = SettingsSection("Skill source")
        section.content.setContentsMargins(18, 16, 18, 16)
        form = SettingsForm()
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("e.g. My skills collection")
        form.addRow("Name", self._label_edit)
        self._type_combo = QComboBox()
        self._type_combo.addItem("Git repository", "git")
        self._type_combo.addItem("Local folder", "local")
        form.addRow("Source type", self._type_combo)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. https://github.com/org/skills")
        self._url_label = QLabel("Repository URL")
        form.addRow(self._url_label, self._url_edit)
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("/path/to/skills")
        self._path_label = QLabel("Folder")
        self._path_widget = QWidget()
        path_row = QHBoxLayout(self._path_widget)
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self._path_edit, 1)
        browse = QPushButton("Browse")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse_path)
        path_row.addWidget(browse)
        form.addRow(self._path_label, self._path_widget)
        section.content.addLayout(form)
        edit_layout.addWidget(section)
        self._action_row_widget = QWidget()
        action = QVBoxLayout(self._action_row_widget)
        action.setContentsMargins(0, 0, 0, 0)
        self._action_status = FeedbackLabel()
        action.addWidget(self._action_status)
        self._clone_btn = QPushButton("Download source")
        self._clone_btn.setAutoDefault(False)
        self._clone_btn.clicked.connect(self._on_clone_update)
        action.addWidget(self._clone_btn, 0, Qt.AlignLeft)
        edit_layout.addWidget(self._action_row_widget)
        self._stack.addWidget(edit_page)
        for source in self._sources:
            self._append_source(source)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._label_edit.textChanged.connect(self._sync_source_to_model)
        self._url_edit.textChanged.connect(self._sync_source_to_model)
        self._path_edit.textChanged.connect(self._sync_source_to_model)
        self._refresh_skills()

    def show_view(self, index: int) -> None:
        self.views.setCurrentIndex(index)
        self.overview_back.setVisible(index != 0)
        self.sources_link.setVisible(index == 0)
        if index == 1 and not self._marketplace_tab.loaded:
            self._marketplace_tab.load()
        if index == 0:
            self._refresh_skills()

    def _browse_marketplace(self) -> None:
        self.show_view(1)
        self._marketplace_tab._search_input.setFocus()

    def _source_entry(self, source: dict) -> tuple[str, str, str, str]:
        name = source.get("label") or "Unnamed source"
        if source.get("type") == "local":
            exists = bool(source.get("path")) and Path(source["path"]).is_dir()
            return (
                name,
                "Local folder",
                "Available" if exists else "Folder missing",
                "success" if exists else "error",
            )
        from roomkit_ui.skill_manager import get_repos_dir, repo_dir_name

        url = source.get("url", "")
        if state := self._git_states.get(url):
            _text, tone, running = state
            status = (
                "Working…" if running else "Update failed" if tone == "error" else "Downloaded"
            )
            return name, "Git repository", status, tone
        exists = bool(url) and (get_repos_dir() / repo_dir_name(url)).is_dir()
        return (
            name,
            "Git repository",
            "Downloaded" if exists else "Download needed",
            "success" if exists else "neutral",
        )

    def _append_source(self, source: dict) -> None:
        self.sources.append(*self._source_entry(source))

    def _refresh_source_entries(self) -> None:
        for i, source in enumerate(self._sources):
            self.sources.update_entry(i, *self._source_entry(source))

    # -- page navigation -----------------------------------------------------

    def _show_overview(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)
        self._refresh_skills()

    def _show_edit(self, row: int) -> None:
        if row < 0 or row >= len(self._sources):
            return
        self._editing_row = row
        src = self._sources[row]

        self._edit_title.setText(src.get("label") or "New Source")

        for w in (self._label_edit, self._url_edit, self._path_edit, self._type_combo):
            w.blockSignals(True)

        self._label_edit.setText(src.get("label", ""))
        self._url_edit.setText(src.get("url", ""))
        self._path_edit.setText(src.get("path", ""))

        src_type = src.get("type", "git")
        idx = self._type_combo.findData(src_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)

        for w in (self._label_edit, self._url_edit, self._path_edit, self._type_combo):
            w.blockSignals(False)

        self._update_type_visibility(src_type)
        self._refresh_source_action()
        self._stack.setCurrentIndex(1)

    # -- source management ---------------------------------------------------

    def _add_source(self) -> None:
        src: dict = {"type": "git", "url": "", "path": "", "label": ""}
        self._sources.append(src)
        self._append_source(src)
        self.show_view(2)
        self._show_edit(len(self._sources) - 1)
        self._label_edit.setFocus()

    def _remove_source(self, row: int) -> None:
        if row < 0 or row >= len(self._sources):
            return
        self._sources.pop(row)
        self.sources.remove(row)
        self._editing_row = -1
        self._refresh_skills()

    def _matching_git_source_index(self, url: str) -> int:
        from roomkit_ui.skill_manager import repo_dir_name

        target = repo_dir_name(url)
        for idx, src in enumerate(self._sources):
            if src.get("type") != "git":
                continue
            src_url = src.get("url", "")
            if src_url and repo_dir_name(src_url) == target:
                return idx
        return -1

    def _matching_local_source_index(self, path: str) -> int:
        for idx, src in enumerate(self._sources):
            if src.get("type") == "local" and src.get("path") == path:
                return idx
        return -1

    def _is_marketplace_source_installed(self, skill: SkillsShSkill) -> bool:
        from roomkit_ui.skill_manager import get_repos_dir, repo_dir_name, well_known_skill_dir

        github_url = skill.github_url
        if github_url:
            return (
                self._matching_git_source_index(github_url) >= 0
                and (get_repos_dir() / repo_dir_name(github_url)).is_dir()
            )

        if skill.is_well_known_source:
            dest = well_known_skill_dir(skill.source, skill.skill_id)
            return self._matching_local_source_index(str(dest)) >= 0 and dest.is_dir()
        return False

    async def _install_marketplace_source(self, skill: SkillsShSkill) -> None:
        github_url = skill.github_url
        if github_url:
            await self._install_git_marketplace_source(skill, github_url)
        elif skill.is_well_known_source:
            await self._install_well_known_marketplace_source(skill)
        else:
            raise ValueError("Unsupported skills.sh source type")
        if isValid(self):  # the Settings dialog may have closed meanwhile
            self._refresh_skills()

    async def _install_git_marketplace_source(
        self,
        skill: SkillsShSkill,
        github_url: str,
    ) -> None:
        row = self._matching_git_source_index(github_url)
        if row < 0:
            src: dict = {
                "type": "git",
                "url": github_url,
                "path": "",
                "label": f"skills.sh · {skill.source}",
            }
            self._sources.append(src)
            self._append_source(src)

        from roomkit_ui.skill_git import clone_repo, pull_repo
        from roomkit_ui.skill_manager import get_repos_dir, repo_dir_name

        dest = get_repos_dir() / repo_dir_name(github_url)
        if dest.exists():
            ok = await pull_repo(dest)
            if not ok:
                raise RuntimeError("Git update failed")
        else:
            await clone_repo(github_url)

    async def _install_well_known_marketplace_source(self, skill: SkillsShSkill) -> None:
        resolved = await SkillsShClient().with_install_url(skill)
        install_url = resolved.install_url
        if not install_url:
            raise ValueError("skills.sh page does not expose a well-known install URL")

        from roomkit_ui.skill_well_known import install_well_known_skill

        dest = await install_well_known_skill(
            install_url,
            skill_name=skill.skill_id,
            source=skill.source,
        )
        src: dict = {
            "type": "local",
            "url": "",
            "path": str(dest),
            "label": f"skills.sh · {skill.source}/{skill.skill_id}",
        }
        if not isValid(self):
            # Settings closed during the download and already saved its
            # sources: record this one directly, or the skill sits on disk
            # unused.
            _save_source_after_close(src)
            return
        if self._matching_local_source_index(src["path"]) < 0:
            self._sources.append(src)
            self._append_source(src)

    # -- edit form -----------------------------------------------------------

    def _on_type_changed(self, _index: int) -> None:
        src_type = self._type_combo.currentData()
        self._update_type_visibility(src_type)
        self._sync_source_to_model()

    def _update_type_visibility(self, src_type: str) -> None:
        is_git = src_type == "git"
        self._url_label.setVisible(is_git)
        self._url_edit.setVisible(is_git)
        self._path_label.setVisible(not is_git)
        self._path_widget.setVisible(not is_git)
        self._action_row_widget.setVisible(is_git)
        self._refresh_source_action()

    def _sync_source_to_model(self) -> None:
        row = self._editing_row
        if row < 0 or row >= len(self._sources):
            return
        src = self._sources[row]
        src["label"] = self._label_edit.text().strip()
        src["type"] = self._type_combo.currentData()
        src["url"] = self._url_edit.text().strip()
        src["path"] = self._path_edit.text().strip()
        self.sources.update_entry(row, *self._source_entry(src))
        self._refresh_source_action()
        self._edit_title.setText(src["label"] or "New Source")

    def _browse_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Skills Directory")
        if path:
            self._path_edit.setText(path)

    def _refresh_source_action(self) -> None:
        url = self._url_edit.text().strip()
        if state := self._git_states.get(url):
            text, tone, running = state
            self._action_status.set_status(text, tone)
            self._clone_btn.setEnabled(not running)
        else:
            self._action_status.set_status("")
            self._clone_btn.setEnabled(True)
        from roomkit_ui.skill_manager import get_repos_dir, repo_dir_name

        exists = bool(url) and (get_repos_dir() / repo_dir_name(url)).exists()
        self._clone_btn.setText("Update source" if exists else "Download source")

    def _on_clone_update(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            self._action_status.set_status("Enter a repository URL first", "error")
            return
        if self._git_states.get(url, ("", "", False))[2]:
            return
        self._git_states[url] = ("Working…", "active", True)
        self._refresh_source_action()
        self._refresh_source_entries()
        asyncio.ensure_future(self._run_git_op(url))

    async def _run_git_op(self, url: str) -> None:
        """An operation's result stays attached to its URL when another source is edited."""
        try:
            from roomkit_ui.skill_git import clone_repo, pull_repo
            from roomkit_ui.skill_manager import get_repos_dir, repo_dir_name

            dest = get_repos_dir() / repo_dir_name(url)
            if dest.exists():
                if not await pull_repo(dest):
                    raise RuntimeError("Git update failed")
                text = "Updated successfully"
            else:
                await clone_repo(url)
                text = "Downloaded successfully"
            self._git_states[url] = (text, "success", False)
        except Exception as exc:
            self._git_states[url] = (f"Error: {exc}", "error", False)
        if isValid(self):
            self._refresh_source_action()
            self._refresh_skills()

    # -- My Skills: discovery & cards ----------------------------------------

    def _on_skill_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self._enabled.add(name)
        else:
            self._enabled.discard(name)

    def _refresh_skills(self) -> None:
        """Re-scan sources and rebuild the skill card grid."""
        self._my_skills_tab.refresh(self._sources, self._enabled)
        self._refresh_source_entries()

    # -- serialization -------------------------------------------------------

    def get_sources_json(self) -> str:
        """Return source configs as a JSON string for saving."""
        return json.dumps(self._sources)

    def get_enabled_json(self) -> str:
        """Return enabled skill names as a JSON string for saving."""
        return json.dumps(sorted(self._enabled))

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "skill_sources": self.get_sources_json(),
            "enabled_skills": self.get_enabled_json(),
        }


def _save_source_after_close(src: dict) -> None:
    """Add *src* to the saved skill sources, unless one already has its path."""
    from roomkit_ui.settings import load_setting, save_settings

    try:
        sources = json.loads(load_setting("skill_sources") or "[]")
    except (TypeError, ValueError):
        sources = []
    if any(s.get("type") == "local" and s.get("path") == src["path"] for s in sources):
        return
    sources.append(src)
    save_settings({"skill_sources": json.dumps(sources)})
