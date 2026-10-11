"""Attitudes management page with list/edit navigation."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLineEdit, QTextEdit, QVBoxLayout, QWidget

from roomkit_ui.constants import ATTITUDE_PRESETS
from roomkit_ui.widgets.settings.controls import SettingsForm, label, navigation_link
from roomkit_ui.widgets.settings.integration_controls import DetailStack, IntegrationList


class _AttitudesPage(QWidget):
    """Attitudes management page with list/edit navigation."""

    changed = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._custom: list[dict] = []
        try:
            self._custom = json.loads(settings.get("custom_attitudes", "[]"))
        except (json.JSONDecodeError, TypeError):
            self._custom = []

        self._editing_row = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._stack = DetailStack()
        layout.addWidget(self._stack)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(12)
        overview_layout.addWidget(label("Personality presets", "settingsSectionTitle"))
        self.entries = IntegrationList(
            "Personality presets",
            "View a built-in style or create and edit your own.",
            "personality",
        )
        overview_layout.addWidget(self.entries)
        self._att_list = self.entries.list
        self._remove_btn = self.entries.remove_button
        self.entries.add_requested.connect(self._add_attitude)
        self.entries.edit_requested.connect(self._show_edit)
        self.entries.remove_requested.connect(lambda _row: self._remove_attitude())
        self._att_list.currentRowChanged.connect(self._on_selection_changed)
        self.entries.search.textChanged.connect(lambda: self._on_selection_changed())
        self._stack.addWidget(overview)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(16)
        back = navigation_link("← Back to personalities")
        back.clicked.connect(self._show_list)
        editor_layout.addWidget(back, 0, Qt.AlignLeft)
        self._edit_title = label("", "settingsSectionTitle")
        self._edit_title.setTextFormat(Qt.PlainText)
        editor_layout.addWidget(self._edit_title)
        self._edit_hint = label("", "settingsHint")
        editor_layout.addWidget(self._edit_hint)
        card = QFrame()
        card.setObjectName("settingsCard")
        form = SettingsForm(card)
        form.setContentsMargins(20, 20, 20, 20)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Calm and concise")
        form.addRow("Name", self._name_edit)
        self._text_edit = QTextEdit()
        self._text_edit.setAcceptRichText(False)
        self._text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self._text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setMinimumHeight(160)
        self._text_edit.setPlaceholderText(
            "Describe the assistant's personality and communication style."
        )
        form.addRow("Communication style", self._text_edit)
        editor_layout.addWidget(card)
        self._stack.addWidget(editor)
        self._rebuild_list()
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
            self.entries.append(name, "Included with RoomKit · view only", "Built-in")
        for att in self._custom:
            self.entries.append(att.get("name") or "Unnamed", "Your communication style", "Custom")
        self.entries.refresh()
        self._on_selection_changed()

    # -- navigation ----------------------------------------------------------

    def _show_list(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)
        self._att_list.setFocus()

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

        self._edit_title.setText(name or "New personality")

        for w in (self._name_edit, self._text_edit):
            w.blockSignals(True)

        self._name_edit.setText(name)
        self._name_edit.setReadOnly(is_preset)
        self._text_edit.setPlainText(text)
        self._text_edit.setReadOnly(is_preset)

        for w in (self._name_edit, self._text_edit):
            w.blockSignals(False)

        self._edit_hint.setText(
            "Built-in personalities are read-only. Add a personality to create your own style."
            if is_preset
            else "Changes are saved when you close Settings."
        )
        self._stack.setCurrentIndex(1)
        (self._text_edit if is_preset else self._name_edit).setFocus()

    def _on_selection_changed(self, _row: int = -1) -> None:
        row = self._att_list.currentRow()
        item = self._att_list.currentItem()
        selected = item is not None and not item.isHidden()
        self.entries.edit_button.setEnabled(selected)
        self.entries.edit_button.setText(
            "View selected" if self._is_preset(row) else "Edit selected"
        )
        self._remove_btn.setEnabled(selected and not self._is_preset(row))

    # -- add / remove --------------------------------------------------------

    def _add_attitude(self) -> None:
        att = {"name": "", "text": ""}
        self._custom.append(att)
        self.entries.search.clear()
        self.entries.append("Unnamed", "Your communication style", "Custom")
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
            self.changed.emit()

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
        self.entries.update_entry(
            row, self._custom[idx]["name"] or "Unnamed", "Your communication style", "Custom"
        )
        self._on_selection_changed()
        self._edit_title.setText(self._custom[idx]["name"] or "New personality")
        self.changed.emit()

    # -- public API ----------------------------------------------------------

    def get_custom_json(self) -> str:
        return json.dumps(self._custom)

    def all_attitude_names(self) -> list[str]:
        names = [name for name, _text in ATTITUDE_PRESETS]
        names.extend(att.get("name", "") for att in self._custom if att.get("name"))
        return names

    def personality_text(self, name: str) -> str:
        for preset, text in ATTITUDE_PRESETS:
            if preset == name:
                return text
        return next((a.get("text", "") for a in self._custom if a.get("name") == name), "")

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "custom_attitudes": self.get_custom_json(),
        }
