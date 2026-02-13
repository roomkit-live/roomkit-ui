"""Agent Skills configuration page — orchestrator."""

from __future__ import annotations

import asyncio
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.skills.marketplace import MarketplaceTab
from roomkit_ui.widgets.settings.skills.my_skills import MySkillsTab, source_display
from roomkit_ui.widgets.settings.skills.widgets import make_tab_toggle


class _SkillsPage(QWidget):
    """Agent Skills configuration page with card-based UI and ClawHub marketplace."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._sources: list[dict] = []
        try:
            self._sources = json.loads(settings.get("skill_sources", "[]"))
        except (json.JSONDecodeError, TypeError):
            self._sources = []

        self._enabled: set[str] = set()
        try:
            self._enabled = set(json.loads(settings.get("enabled_skills", "[]")))
        except (json.JSONDecodeError, TypeError):
            self._enabled = set()

        self._editing_row = -1

        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Page 0: Overview (tabs) ──
        overview = QWidget()
        ov_layout = QVBoxLayout(overview)
        ov_layout.setContentsMargins(0, 0, 0, 0)
        ov_layout.setSpacing(12)

        title = QLabel("Agent Skills")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        ov_layout.addWidget(title)

        desc = QLabel(
            "Manage local skills and browse the ClawHub marketplace."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        ov_layout.addWidget(desc)

        # Tab toggle
        self._tab_toggle, self._tab_buttons = make_tab_toggle(
            ["My Skills", "Marketplace"], self._on_tab_switch
        )
        ov_layout.addWidget(self._tab_toggle)

        # ── Tab content stack ──
        self._tab_stack = QStackedWidget()
        ov_layout.addWidget(self._tab_stack, 1)

        # -- My Skills tab --
        self._my_skills_tab = MySkillsTab(
            on_add_source=self._add_source,
            on_remove_source=self._remove_source,
            on_source_activated=self._on_source_activated,
            on_skill_toggled=self._on_skill_toggled,
            on_refresh=self._refresh_skills,
            on_uninstall=self._uninstall_clawhub_skill,
        )
        self._tab_stack.addWidget(self._my_skills_tab)

        # -- Marketplace tab --
        self._marketplace_tab = MarketplaceTab(on_installed=self._refresh_skills)
        self._tab_stack.addWidget(self._marketplace_tab)

        self._tab_stack.setCurrentIndex(0)

        self._stack.addWidget(overview)

        # ── Page 1: Edit Source ──
        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(12)

        back_btn = QPushButton("\u2190  Back to overview")
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {c['ACCENT_BLUE']}; font-size: 13px;"
            f" text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
        back_btn.clicked.connect(self._show_overview)
        edit_layout.addWidget(back_btn)

        self._edit_title = QLabel()
        self._edit_title.setStyleSheet(
            "font-size: 18px; font-weight: 600; background: transparent;"
        )
        edit_layout.addWidget(self._edit_title)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("e.g. My Skills Collection")
        form.addRow("Label", self._label_edit)

        self._type_combo = QComboBox()
        self._type_combo.addItem("Git Repository", "git")
        self._type_combo.addItem("Local Directory", "local")
        form.addRow("Type", self._type_combo)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. https://github.com/org/skills")
        self._url_label = QLabel("URL")
        form.addRow(self._url_label, self._url_edit)

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("/path/to/skills")
        self._path_label = QLabel("Path")
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.addWidget(self._path_edit, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        self._path_widget = QWidget()
        self._path_widget.setLayout(path_row)
        form.addRow(self._path_label, self._path_widget)

        edit_layout.addLayout(form)

        # Clone / Update button + status
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._clone_btn = QPushButton("Clone")
        self._clone_btn.setCursor(Qt.PointingHandCursor)
        self._clone_btn.clicked.connect(self._on_clone_update)
        action_row.addWidget(self._clone_btn)
        self._action_status = QLabel("")
        self._action_status.setWordWrap(True)
        self._action_status.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        action_row.addWidget(self._action_status, 1)
        self._action_row_widget = QWidget()
        self._action_row_widget.setLayout(action_row)
        edit_layout.addWidget(self._action_row_widget)

        edit_layout.addStretch()

        self._stack.addWidget(edit_page)

        # Start on overview
        self._stack.setCurrentIndex(0)

        # Populate source list
        for src in self._sources:
            self._my_skills_tab.source_list.addItem(source_display(src))

        # Connections
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._label_edit.textChanged.connect(self._sync_source_to_model)
        self._url_edit.textChanged.connect(self._sync_source_to_model)
        self._path_edit.textChanged.connect(self._sync_source_to_model)

        # Initial skill discovery
        self._refresh_skills()

    # -- tab navigation ------------------------------------------------------

    def _on_tab_switch(self, idx: int) -> None:
        self._tab_toggle._apply_styles(idx)  # type: ignore[attr-defined]
        self._tab_stack.setCurrentIndex(idx)
        if idx == 1 and not self._marketplace_tab.loaded:
            self._marketplace_tab.load()

    # -- page navigation -----------------------------------------------------

    def _show_overview(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)

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
        self._action_status.setText("")
        self._stack.setCurrentIndex(1)

    def _on_source_activated(self, row: int) -> None:
        self._show_edit(row)

    # -- source management ---------------------------------------------------

    def _add_source(self) -> None:
        src: dict = {"type": "git", "url": "", "path": "", "label": ""}
        self._sources.append(src)
        self._my_skills_tab.source_list.addItem(source_display(src))
        self._show_edit(len(self._sources) - 1)
        self._label_edit.setFocus()

    def _remove_source(self, row: int) -> None:
        if row < 0:
            return
        self._sources.pop(row)
        self._my_skills_tab.source_list.takeItem(row)
        self._refresh_skills()

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
        if is_git:
            from roomkit_ui.skill_manager import get_repos_dir, repo_dir_name

            url = self._url_edit.text().strip()
            if url and (get_repos_dir() / repo_dir_name(url)).exists():
                self._clone_btn.setText("Update")
            else:
                self._clone_btn.setText("Clone")

    def _sync_source_to_model(self) -> None:
        row = self._editing_row
        if row < 0 or row >= len(self._sources):
            return
        src = self._sources[row]
        src["label"] = self._label_edit.text().strip()
        src["type"] = self._type_combo.currentData()
        src["url"] = self._url_edit.text().strip()
        src["path"] = self._path_edit.text().strip()
        item = self._my_skills_tab.source_list.item(row)
        if item:
            item.setText(source_display(src))
        self._edit_title.setText(src["label"] or "New Source")

    def _browse_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Skills Directory")
        if path:
            self._path_edit.setText(path)

    def _on_clone_update(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            self._action_status.setText("Enter a URL first")
            self._action_status.setStyleSheet(
                "font-size: 12px; color: #f44336; background: transparent;"
            )
            return

        self._clone_btn.setEnabled(False)
        self._action_status.setText("Working...")
        self._action_status.setStyleSheet(
            "font-size: 12px; color: #ff9800; background: transparent;"
        )

        asyncio.ensure_future(self._run_git_op(url))

    async def _run_git_op(self, url: str) -> None:
        """Clone or pull a git repo in the background."""
        try:
            from roomkit_ui.skill_manager import (
                clone_repo,
                get_repos_dir,
                pull_repo,
                repo_dir_name,
            )

            dest = get_repos_dir() / repo_dir_name(url)
            if dest.exists():
                ok = await pull_repo(dest)
                if ok:
                    self._action_status.setText("Updated successfully")
                    self._action_status.setStyleSheet(
                        "font-size: 12px; color: #4caf50; background: transparent;"
                    )
                else:
                    self._action_status.setText("Update failed")
                    self._action_status.setStyleSheet(
                        "font-size: 12px; color: #f44336; background: transparent;"
                    )
            else:
                await clone_repo(url)
                self._action_status.setText("Cloned successfully")
                self._action_status.setStyleSheet(
                    "font-size: 12px; color: #4caf50; background: transparent;"
                )
                self._clone_btn.setText("Update")
        except Exception as exc:
            self._action_status.setText(f"Error: {exc}")
            self._action_status.setStyleSheet(
                "font-size: 12px; color: #f44336; background: transparent;"
            )
        finally:
            try:
                self._clone_btn.setEnabled(True)
            except Exception:
                pass
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

    def _uninstall_clawhub_skill(self, slug: str) -> None:
        """Remove a ClawHub-installed skill and refresh."""
        from roomkit_ui.skill_manager import remove_clawhub_skill

        remove_clawhub_skill(slug)
        self._refresh_skills()

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
