"""Attitudes management page with list/edit navigation."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.constants import ATTITUDE_PRESETS


class _AttitudesPage(QWidget):
    """Attitudes management page with list/edit navigation."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._custom: list[dict] = []
        try:
            self._custom = json.loads(settings.get("custom_attitudes", "[]"))
        except (json.JSONDecodeError, TypeError):
            self._custom = []

        self._editing_row = -1
        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Page 0: Attitude list ──
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        title = QLabel("Attitudes")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        list_layout.addWidget(title)

        desc = QLabel(
            "Define personality presets for the assistant. Select which one to use in AI Provider."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        list_layout.addWidget(desc)

        self._att_list = QListWidget()
        self._att_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
        )
        list_layout.addWidget(self._att_list, 1)

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
        add_btn.clicked.connect(self._add_attitude)
        self._remove_btn = QPushButton("\u2212")
        self._remove_btn.setFixedSize(28, 28)
        self._remove_btn.setStyleSheet(_btn_style)
        self._remove_btn.clicked.connect(self._remove_attitude)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch()
        list_layout.addLayout(btn_row)

        self._stack.addWidget(list_page)

        # ── Page 1: Edit form ──
        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(12)

        back_btn = QPushButton("\u2190  Back to list")
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {c['ACCENT_BLUE']}; font-size: 13px;"
            f" text-align: left; padding: 0; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
        back_btn.clicked.connect(self._show_list)
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

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Pirate")
        form.addRow("Name", self._name_edit)

        self._text_edit = QTextEdit()
        self._text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self._text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setFixedHeight(120)
        self._text_edit.setPlaceholderText(
            "Describe the assistant's personality and communication style."
        )
        form.addRow("Text", self._text_edit)

        edit_layout.addLayout(form)
        edit_layout.addStretch()

        self._stack.addWidget(edit_page)

        # Start on list page
        self._stack.setCurrentIndex(0)

        # Populate list
        self._rebuild_list()

        # Connections
        self._att_list.itemDoubleClicked.connect(self._on_item_activated)
        self._att_list.currentRowChanged.connect(self._on_selection_changed)
        self._name_edit.textChanged.connect(self._sync_to_model)
        self._text_edit.textChanged.connect(self._sync_to_model)

    # -- helpers -------------------------------------------------------------

    @property
    def _preset_count(self) -> int:
        return len(ATTITUDE_PRESETS)

    def _is_preset(self, row: int) -> bool:
        return 0 <= row < self._preset_count

    def _rebuild_list(self) -> None:
        self._att_list.clear()
        for name, _text in ATTITUDE_PRESETS:
            self._att_list.addItem(f"{name}  (preset)")
        for att in self._custom:
            self._att_list.addItem(att.get("name", "Unnamed"))

    # -- navigation ----------------------------------------------------------

    def _show_list(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)

    def _show_edit(self, row: int) -> None:
        total = self._preset_count + len(self._custom)
        if row < 0 or row >= total:
            return
        self._editing_row = row
        is_preset = self._is_preset(row)

        if is_preset:
            name, text = ATTITUDE_PRESETS[row]
        else:
            att = self._custom[row - self._preset_count]
            name = att.get("name", "")
            text = att.get("text", "")

        self._edit_title.setText(name or "New Attitude")

        for w in (self._name_edit, self._text_edit):
            w.blockSignals(True)

        self._name_edit.setText(name)
        self._name_edit.setReadOnly(is_preset)
        self._text_edit.setPlainText(text)
        self._text_edit.setReadOnly(is_preset)

        for w in (self._name_edit, self._text_edit):
            w.blockSignals(False)

        self._stack.setCurrentIndex(1)

    def _on_item_activated(self, _item: QListWidgetItem) -> None:
        row = self._att_list.currentRow()
        self._show_edit(row)

    def _on_selection_changed(self, row: int) -> None:
        # Disable remove button for presets
        self._remove_btn.setEnabled(not self._is_preset(row))

    # -- add / remove --------------------------------------------------------

    def _add_attitude(self) -> None:
        att = {"name": "", "text": ""}
        self._custom.append(att)
        self._att_list.addItem("Unnamed")
        new_row = self._preset_count + len(self._custom) - 1
        self._att_list.setCurrentRow(new_row)
        self._show_edit(new_row)

    def _remove_attitude(self) -> None:
        row = self._att_list.currentRow()
        if self._is_preset(row) or row < 0:
            return
        idx = row - self._preset_count
        if 0 <= idx < len(self._custom):
            self._custom.pop(idx)
            self._rebuild_list()

    # -- sync ----------------------------------------------------------------

    def _sync_to_model(self) -> None:
        row = self._editing_row
        if row < 0 or self._is_preset(row):
            return
        idx = row - self._preset_count
        if idx < 0 or idx >= len(self._custom):
            return
        self._custom[idx]["name"] = self._name_edit.text().strip()
        self._custom[idx]["text"] = self._text_edit.toPlainText().strip()
        # Update list item text
        item = self._att_list.item(row)
        if item:
            item.setText(self._custom[idx]["name"] or "Unnamed")
        self._edit_title.setText(self._custom[idx]["name"] or "New Attitude")

    # -- public API ----------------------------------------------------------

    def get_custom_json(self) -> str:
        return json.dumps(self._custom)

    def all_attitude_names(self) -> list[str]:
        names = [name for name, _text in ATTITUDE_PRESETS]
        names.extend(att.get("name", "") for att in self._custom if att.get("name"))
        return names

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "custom_attitudes": self.get_custom_json(),
        }
