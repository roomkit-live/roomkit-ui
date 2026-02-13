"""Agent Skills configuration page with card-based UI and ClawHub marketplace."""

from __future__ import annotations

import asyncio
import json
import logging

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from roomkit_ui.theme import colors

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flow layout — wraps cards into rows
# ---------------------------------------------------------------------------


class _FlowLayout(QLayout):
    """A layout that arranges widgets in a flowing left-to-right, top-to-bottom grid."""

    def __init__(self, parent=None, h_spacing: int = 10, v_spacing: int = 10) -> None:
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list[QWidgetItem] = []

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > effective.right() + 1 and row_height > 0:
                x = effective.x()
                y += row_height + self._v_spacing
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(x, y, w, h))
            x += w + self._h_spacing
            row_height = max(row_height, h)
        return y + row_height - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# Skill card widget
# ---------------------------------------------------------------------------

CARD_WIDTH = 255


class _SkillCard(QWidget):
    """A card displaying a single skill in "my skills" or "marketplace" mode."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        source_label: str = "",
        checked: bool = False,
        marketplace: bool = False,
        installed: bool = False,
        downloads: int = 0,
        version: str | None = None,
        slug: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.slug = slug
        self._marketplace = marketplace
        c = colors()

        self.setFixedWidth(CARD_WIDTH)
        self.setStyleSheet(
            f"_SkillCard {{"
            f" background: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 10px;"
            f"}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header row: checkbox (my skills) or just the name (marketplace)
        header = QHBoxLayout()
        header.setSpacing(8)
        if not marketplace:
            self.checkbox = QCheckBox()
            self.checkbox.setChecked(checked)
            header.addWidget(self.checkbox)
        else:
            self.checkbox = None

        name_label = QLabel(name)
        name_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {c['TEXT_PRIMARY']};"
            " background: transparent;"
        )
        header.addWidget(name_label, 1)
        layout.addLayout(header)

        # Description (2-line clamp)
        if description:
            desc_text = description if len(description) <= 100 else description[:97] + "..."
            desc = QLabel(desc_text)
            desc.setWordWrap(True)
            desc.setMaximumHeight(36)
            desc.setStyleSheet(
                f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
            )
            layout.addWidget(desc)

        # Footer row
        footer = QHBoxLayout()
        footer.setSpacing(6)

        if marketplace:
            stats_parts: list[str] = []
            if downloads:
                stats_parts.append(f"\u2b07 {_format_count(downloads)}")
            if version:
                stats_parts.append(f"v{version}")
            if stats_parts:
                stats = QLabel("  ".join(stats_parts))
                stats.setStyleSheet(
                    f"font-size: 10px; color: {c['TEXT_SECONDARY']}; background: transparent;"
                )
                footer.addWidget(stats)
            footer.addStretch()

            self.action_btn = QPushButton("Installed \u2713" if installed else "Install")
            self.action_btn.setEnabled(not installed)
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.setFixedHeight(26)
            btn_bg = c["ACCENT_GREEN"] if not installed else c["BG_TERTIARY"]
            btn_fg = "#000000" if not installed else c["TEXT_SECONDARY"]
            self.action_btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; font-weight: 600;"
                f" background: {btn_bg}; color: {btn_fg};"
                f" border: none; border-radius: 6px; padding: 0 12px; }}"
                f"QPushButton:hover {{ opacity: 0.9; }}"
                f"QPushButton:disabled {{ background: {c['BG_TERTIARY']};"
                f" color: {c['TEXT_SECONDARY']}; }}"
            )
            footer.addWidget(self.action_btn)
        else:
            # Source tag badge
            if source_label:
                tag = QLabel(source_label)
                tag.setStyleSheet(
                    f"font-size: 10px; color: {c['TEXT_SECONDARY']};"
                    f" background: {c['BG_TERTIARY']};"
                    f" border-radius: 4px; padding: 2px 6px;"
                )
                footer.addWidget(tag)
            footer.addStretch()
            self.action_btn = None

        layout.addLayout(footer)

    def sizeHint(self):  # noqa: N802
        h = self.layout().sizeHint().height()
        return QSize(CARD_WIDTH, max(h, 90))


def _format_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ---------------------------------------------------------------------------
# Tab toggle (segmented control)
# ---------------------------------------------------------------------------


def _make_tab_toggle(
    labels: list[str], on_switch, parent=None
) -> tuple[QWidget, list[QPushButton]]:
    """Create a segmented-control style tab toggle."""
    c = colors()
    container = QWidget(parent)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    buttons: list[QPushButton] = []
    for i, label in enumerate(labels):
        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        btn.setChecked(i == 0)
        btn.setFixedHeight(32)
        btn.clicked.connect(lambda _checked, idx=i: on_switch(idx))
        buttons.append(btn)
        layout.addWidget(btn)
    layout.addStretch()

    def _apply_styles(active_idx: int) -> None:
        for j, b in enumerate(buttons):
            b.setChecked(j == active_idx)
            if j == active_idx:
                b.setStyleSheet(
                    f"QPushButton {{ font-size: 13px; font-weight: 600;"
                    f" background: {c['ACCENT_BLUE']}; color: #FFFFFF;"
                    f" border: none; border-radius: 8px; padding: 0 18px; }}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton {{ font-size: 13px; font-weight: 500;"
                    f" background: {c['BG_SECONDARY']}; color: {c['TEXT_SECONDARY']};"
                    f" border: 1px solid {c['SEPARATOR']}; border-radius: 8px;"
                    f" padding: 0 18px; }}"
                    f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
                )

    container._apply_styles = _apply_styles  # type: ignore[attr-defined]
    _apply_styles(0)
    return container, buttons


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------


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
        self._marketplace_loaded = False
        self._marketplace_skills: list = []
        self._marketplace_cursor: str | None = None
        self._installing_slug: str | None = None
        self._search_timer: QTimer | None = None

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
        self._tab_toggle, self._tab_buttons = _make_tab_toggle(
            ["My Skills", "Marketplace"], self._on_tab_switch
        )
        ov_layout.addWidget(self._tab_toggle)

        # ── Tab content stack ──
        self._tab_stack = QStackedWidget()
        ov_layout.addWidget(self._tab_stack, 1)

        # -- My Skills tab --
        my_skills_page = QWidget()
        ms_layout = QVBoxLayout(my_skills_page)
        ms_layout.setContentsMargins(0, 4, 0, 0)
        ms_layout.setSpacing(8)

        # Source management row
        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_label = QLabel("Sources")
        src_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        src_row.addWidget(src_label)
        src_row.addStretch()
        add_src_btn = QPushButton("+ Add Source")
        add_src_btn.setCursor(Qt.PointingHandCursor)
        add_src_btn.setFixedHeight(26)
        add_src_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; font-weight: 600;"
            f" background: {c['BG_SECONDARY']}; color: {c['ACCENT_BLUE']};"
            f" border: 1px solid {c['SEPARATOR']}; border-radius: 6px;"
            f" padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
        )
        add_src_btn.clicked.connect(self._add_source)
        src_row.addWidget(add_src_btn)
        manage_btn = QPushButton("\u2699")
        manage_btn.setToolTip("Manage sources")
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.setFixedSize(26, 26)
        manage_btn.setStyleSheet(
            f"QPushButton {{ font-size: 14px; background: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['SEPARATOR']}; border-radius: 6px; padding: 0; }}"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
        )
        manage_btn.clicked.connect(self._toggle_source_list)
        src_row.addWidget(manage_btn)
        ms_layout.addLayout(src_row)

        # Collapsible source list
        self._source_list_wrapper = QWidget()
        sl_layout = QVBoxLayout(self._source_list_wrapper)
        sl_layout.setContentsMargins(0, 0, 0, 0)
        sl_layout.setSpacing(4)
        self._source_list = QListWidget()
        self._source_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
        )
        self._source_list.setMaximumHeight(120)
        sl_layout.addWidget(self._source_list)

        _btn_style = (
            f"QPushButton {{ font-size: 16px; font-weight: 700;"
            f" color: {c['TEXT_PRIMARY']}; background-color: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['BG_TERTIARY']}; border-radius: 6px;"
            f" padding: 0px; min-width: 26px; min-height: 26px; }}"
            f"QPushButton:hover {{ background-color: {c['BG_TERTIARY']}; }}"
        )
        sl_btn_row = QHBoxLayout()
        sl_btn_row.setSpacing(4)
        remove_btn = QPushButton("\u2212")
        remove_btn.setFixedSize(26, 26)
        remove_btn.setStyleSheet(_btn_style)
        remove_btn.clicked.connect(self._remove_source)
        sl_btn_row.addWidget(remove_btn)
        sl_btn_row.addStretch()
        sl_layout.addLayout(sl_btn_row)

        self._source_list_wrapper.setVisible(False)
        ms_layout.addWidget(self._source_list_wrapper)

        # My skills cards (scroll area)
        self._my_skills_container = QWidget()
        self._my_skills_flow = _FlowLayout(self._my_skills_container, h_spacing=10, v_spacing=10)

        my_skills_scroll = QScrollArea()
        my_skills_scroll.setWidget(self._my_skills_container)
        my_skills_scroll.setWidgetResizable(True)
        my_skills_scroll.setFrameShape(QScrollArea.NoFrame)
        my_skills_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        ms_layout.addWidget(my_skills_scroll, 1)

        # Refresh button
        refresh_btn = QPushButton("Refresh Skills")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_skills)
        ms_layout.addWidget(refresh_btn)

        self._tab_stack.addWidget(my_skills_page)

        # -- Marketplace tab --
        marketplace_page = QWidget()
        mp_layout = QVBoxLayout(marketplace_page)
        mp_layout.setContentsMargins(0, 4, 0, 0)
        mp_layout.setSpacing(8)

        # Search bar
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_icon = QLabel("\U0001f50d")
        search_icon.setStyleSheet("background: transparent; font-size: 14px;")
        search_row.addWidget(search_icon)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search skills...")
        self._search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_input, 1)
        mp_layout.addLayout(search_row)

        # Marketplace status
        self._mp_status = QLabel("")
        self._mp_status.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        mp_layout.addWidget(self._mp_status)

        # Marketplace cards (scroll area)
        self._mp_container = QWidget()
        self._mp_flow = _FlowLayout(self._mp_container, h_spacing=10, v_spacing=10)

        mp_scroll = QScrollArea()
        mp_scroll.setWidget(self._mp_container)
        mp_scroll.setWidgetResizable(True)
        mp_scroll.setFrameShape(QScrollArea.NoFrame)
        mp_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        mp_layout.addWidget(mp_scroll, 1)

        self._tab_stack.addWidget(marketplace_page)
        self._tab_stack.setCurrentIndex(0)

        self._stack.addWidget(overview)

        # ── Page 1: Edit Source (unchanged from original) ──
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

    # -- tab navigation ------------------------------------------------------

    def _on_tab_switch(self, idx: int) -> None:
        self._tab_toggle._apply_styles(idx)  # type: ignore[attr-defined]
        self._tab_stack.setCurrentIndex(idx)
        if idx == 1 and not self._marketplace_loaded:
            self._load_marketplace()

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

    def _on_source_activated(self, _item: QListWidgetItem) -> None:
        row = self._source_list.currentRow()
        self._show_edit(row)

    # -- source management ---------------------------------------------------

    def _toggle_source_list(self) -> None:
        self._source_list_wrapper.setVisible(not self._source_list_wrapper.isVisible())

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

    def _refresh_skills(self) -> None:
        """Re-scan sources and rebuild the skill card grid."""
        # Clear existing cards
        while self._my_skills_flow.count():
            item = self._my_skills_flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # Auto-inject clawhub source if not present
        sources_with_clawhub = list(self._sources)
        has_clawhub = any(s.get("type") == "clawhub" for s in sources_with_clawhub)
        if not has_clawhub:
            sources_with_clawhub.append({"type": "clawhub", "label": "ClawHub"})

        try:
            from roomkit_ui.skill_manager import discover_all_skills

            skills = discover_all_skills(sources_with_clawhub)
        except Exception:
            skills = []

        for meta, _path, source_label in skills:
            card = _SkillCard(
                name=meta.name,
                description=meta.description,
                source_label=source_label,
                checked=meta.name in self._enabled,
                marketplace=False,
            )
            if card.checkbox:
                card.checkbox.toggled.connect(
                    lambda checked, name=meta.name: self._on_skill_toggled(name, checked)
                )
            self._my_skills_flow.addWidget(card)

        self._my_skills_container.updateGeometry()

    def _on_skill_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self._enabled.add(name)
        else:
            self._enabled.discard(name)

    # -- Marketplace ---------------------------------------------------------

    def _load_marketplace(self) -> None:
        self._mp_status.setText("Loading...")
        asyncio.ensure_future(self._fetch_marketplace())

    async def _fetch_marketplace(self) -> None:
        try:
            from roomkit_ui.clawhub_client import ClawHubClient

            client = ClawHubClient()
            items, cursor = await client.list_skills(self._marketplace_cursor)
            self._marketplace_skills = items
            self._marketplace_cursor = cursor
            self._marketplace_loaded = True
            self._render_marketplace(items)
            self._mp_status.setText(f"{len(items)} skills")
        except Exception as exc:
            logger.exception("Failed to load marketplace")
            self._mp_status.setText(f"Error: {exc}")

    def _on_search_changed(self, text: str) -> None:
        if self._search_timer:
            self._search_timer.stop()
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self._do_search(text))
        self._search_timer.start(400)

    def _do_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            if self._marketplace_skills:
                self._render_marketplace(self._marketplace_skills)
                self._mp_status.setText(f"{len(self._marketplace_skills)} skills")
            else:
                self._load_marketplace()
            return
        self._mp_status.setText("Searching...")
        asyncio.ensure_future(self._run_search(query))

    async def _run_search(self, query: str) -> None:
        try:
            from roomkit_ui.clawhub_client import ClawHubClient

            client = ClawHubClient()
            results = await client.search(query)
            self._render_marketplace(results)
            self._mp_status.setText(f"{len(results)} results")
        except Exception as exc:
            logger.exception("Marketplace search failed")
            self._mp_status.setText(f"Error: {exc}")

    def _render_marketplace(self, items) -> None:
        # Clear existing
        while self._mp_flow.count():
            item = self._mp_flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        from roomkit_ui.skill_manager import list_clawhub_installed

        installed_slugs = set(list_clawhub_installed())

        for skill_info in items:
            is_installed = skill_info.slug in installed_slugs
            card = _SkillCard(
                name=skill_info.display_name,
                description=skill_info.summary or "",
                marketplace=True,
                installed=is_installed,
                downloads=skill_info.downloads,
                version=skill_info.version,
                slug=skill_info.slug,
            )
            if card.action_btn and not is_installed:
                card.action_btn.clicked.connect(
                    lambda _checked, s=skill_info.slug, n=skill_info.display_name, c=card: (
                        self._install_skill(s, n, c)
                    )
                )
            self._mp_flow.addWidget(card)

        self._mp_container.updateGeometry()

    def _install_skill(self, slug: str, name: str, card: _SkillCard) -> None:
        if self._installing_slug:
            return
        self._installing_slug = slug
        if card.action_btn:
            card.action_btn.setText("Installing...")
            card.action_btn.setEnabled(False)
        asyncio.ensure_future(self._do_install(slug, name, card))

    async def _do_install(self, slug: str, name: str, card: _SkillCard) -> None:
        try:
            from roomkit_ui.clawhub_client import ClawHubClient

            client = ClawHubClient()
            await client.download_skill(slug)
            if card.action_btn:
                c = colors()
                card.action_btn.setText("Installed \u2713")
                card.action_btn.setStyleSheet(
                    f"QPushButton {{ font-size: 11px; font-weight: 600;"
                    f" background: {c['BG_TERTIARY']}; color: {c['TEXT_SECONDARY']};"
                    f" border: none; border-radius: 6px; padding: 0 12px; }}"
                )
            logger.info("Installed ClawHub skill: %s (%s)", name, slug)
        except Exception as exc:
            logger.exception("Failed to install %s", slug)
            if card.action_btn:
                card.action_btn.setText("Error")
                card.action_btn.setEnabled(True)
            self._mp_status.setText(f"Install failed: {exc}")
        finally:
            self._installing_slug = None

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
