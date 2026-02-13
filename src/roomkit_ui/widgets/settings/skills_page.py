"""Agent Skills configuration page with sources and skill enable/disable."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors


class _SkillsPage(QWidget):
    """Agent Skills configuration page with sources and skill enable/disable."""

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

        # ── Page 0: Overview ──
        overview = QWidget()
        ov_layout = QVBoxLayout(overview)
        ov_layout.setContentsMargins(0, 0, 0, 0)
        ov_layout.setSpacing(12)

        title = QLabel("Agent Skills")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        ov_layout.addWidget(title)

        desc = QLabel(
            "Add skill sources and enable skills to give the "
            "voice assistant specialized knowledge and capabilities."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        ov_layout.addWidget(desc)

        # Sources section
        src_label = QLabel("Sources")
        src_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        ov_layout.addWidget(src_label)

        self._source_list = QListWidget()
        self._source_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
        )
        self._source_list.setMaximumHeight(140)
        ov_layout.addWidget(self._source_list)

        _btn_style = (
            f"QPushButton {{ font-size: 18px; font-weight: 700;"
            f" color: {c['TEXT_PRIMARY']}; background-color: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['BG_TERTIARY']}; border-radius: 6px;"
            f" padding: 0px; margin: 0px;"
            f" min-width: 28px; min-height: 28px; }}"
            f"QPushButton:hover {{ background-color: {c['BG_TERTIARY']}; }}"
        )
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        add_btn = QPushButton("+")
        add_btn.setFixedSize(28, 28)
        add_btn.setStyleSheet(_btn_style)
        add_btn.clicked.connect(self._add_source)
        remove_btn = QPushButton("\u2212")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setStyleSheet(_btn_style)
        remove_btn.clicked.connect(self._remove_source)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        ov_layout.addLayout(btn_row)

        # Skills section
        skills_label = QLabel("Discovered Skills")
        skills_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        ov_layout.addWidget(skills_label)

        # Scrollable area for skill checkboxes
        self._skills_container = QWidget()
        self._skills_layout = QVBoxLayout(self._skills_container)
        self._skills_layout.setContentsMargins(0, 0, 0, 0)
        self._skills_layout.setSpacing(4)
        self._skills_layout.addStretch()

        skills_scroll = QScrollArea()
        skills_scroll.setWidget(self._skills_container)
        skills_scroll.setWidgetResizable(True)
        skills_scroll.setFrameShape(QScrollArea.NoFrame)
        skills_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        ov_layout.addWidget(skills_scroll, 1)

        # Refresh button
        refresh_btn = QPushButton("Refresh Skills")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_skills)
        ov_layout.addWidget(refresh_btn)

        hint = QLabel("Skills are active in Voice Channel mode.")
        hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        ov_layout.addWidget(hint)

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
            self._source_list.addItem(self._source_display(src))

        # Connections
        self._source_list.itemDoubleClicked.connect(self._on_source_activated)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._label_edit.textChanged.connect(self._sync_source_to_model)
        self._url_edit.textChanged.connect(self._sync_source_to_model)
        self._path_edit.textChanged.connect(self._sync_source_to_model)

        # Initial skill discovery
        self._refresh_skills()

    # -- navigation ----------------------------------------------------------

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

    def _on_source_activated(self, _item: QListWidgetItem) -> None:
        row = self._source_list.currentRow()
        self._show_edit(row)

    # -- add / remove --------------------------------------------------------

    def _add_source(self) -> None:
        src: dict = {"type": "git", "url": "", "path": "", "label": ""}
        self._sources.append(src)
        self._source_list.addItem(self._source_display(src))
        self._show_edit(len(self._sources) - 1)
        self._label_edit.setFocus()

    def _remove_source(self) -> None:
        row = self._source_list.currentRow()
        if row < 0:
            return
        self._sources.pop(row)
        self._source_list.takeItem(row)
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
        # Update button text based on whether repo exists
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
        # Update list item text
        item = self._source_list.item(row)
        if item:
            item.setText(self._source_display(src))
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

        import asyncio

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
        # Auto-refresh skill list after git operation
        self._refresh_skills()

    # -- skill discovery & checkboxes ----------------------------------------

    def _refresh_skills(self) -> None:
        """Re-scan sources and rebuild the skill checkbox list."""
        # Clear existing checkboxes
        while self._skills_layout.count() > 1:
            item = self._skills_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        c = colors()
        try:
            from roomkit_ui.skill_manager import discover_all_skills

            skills = discover_all_skills(self._sources)
        except Exception:
            skills = []

        for meta, _path, source_label in skills:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(8)

            cb = QCheckBox(meta.name)
            cb.setChecked(meta.name in self._enabled)
            cb.toggled.connect(
                lambda checked, name=meta.name: self._on_skill_toggled(name, checked)
            )
            row_layout.addWidget(cb)

            desc_text = meta.description
            if len(desc_text) > 80:
                desc_text = desc_text[:77] + "..."
            desc_label = QLabel(desc_text)
            desc_label.setStyleSheet(
                f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
            )
            row_layout.addWidget(desc_label, 1)

            tag = QLabel(source_label)
            tag.setStyleSheet(
                f"font-size: 10px; color: {c['TEXT_SECONDARY']};"
                f" background: {c['BG_TERTIARY']};"
                f" border-radius: 4px; padding: 2px 6px;"
            )
            row_layout.addWidget(tag)

            # Insert before the stretch
            self._skills_layout.insertWidget(self._skills_layout.count() - 1, row_widget)

    def _on_skill_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self._enabled.add(name)
        else:
            self._enabled.discard(name)

    # -- serialization -------------------------------------------------------

    @staticmethod
    def _source_display(src: dict) -> str:
        label = src.get("label") or "Unnamed"
        src_type = src.get("type", "git")
        return f"{label} ({src_type})"

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
