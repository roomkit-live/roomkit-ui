"""CLI Tools configuration page with list/edit navigation."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.cli_exec import resolve_command
from roomkit_ui.cli_tools_config import (
    DEFAULT_HELP_DEPTH,
    DEFAULT_TIMEOUT,
    parse_cli_tools,
    slugify_tool_name,
)
from roomkit_ui.theme import colors

_OK_COLOR = "#4caf50"
_ERR_COLOR = "#f44336"


class _CliToolsPage(QWidget):
    """CLI Tools configuration page with list/edit navigation."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._tools = parse_cli_tools(settings.get("cli_tools", "[]"))

        self._editing_row = -1
        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Page 0: Tool list ──
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        title = QLabel("CLI Tools")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        list_layout.addWidget(title)

        desc = QLabel(
            "Let the voice assistant run local command-line programs. "
            "Declare a binary once — the assistant reads its --help and works out "
            "the rest on its own."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        list_layout.addWidget(desc)

        self._tool_list = QListWidget()
        self._tool_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
        )
        list_layout.addWidget(self._tool_list, 1)

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
        add_btn.clicked.connect(self._add_tool)
        remove_btn = QPushButton("−")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setStyleSheet(_btn_style)
        remove_btn.clicked.connect(self._remove_tool)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        list_layout.addLayout(btn_row)

        self._stack.addWidget(list_page)

        # ── Page 1: Edit form ──
        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(12)

        back_btn = QPushButton("←  Back to list")
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

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setChecked(True)
        form.addRow("", self._enabled_check)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. GitHub CLI")
        form.addRow("Name", self._name_edit)

        # Providers only accept letters/digits/_/- in a function name, so the
        # name gets slugified. Show the result rather than deriving in silence.
        self._name_status = QLabel("")
        self._name_status.setWordWrap(True)
        self._name_status.setStyleSheet("font-size: 12px; background: transparent;")
        form.addRow("", self._name_status)

        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("e.g. gh")
        form.addRow("Command", self._command_edit)

        # Resolving here rather than at session start: a typo should surface
        # while you are typing it, not as silence three screens later.
        self._command_status = QLabel("")
        self._command_status.setWordWrap(True)
        self._command_status.setStyleSheet("font-size: 12px; background: transparent;")
        form.addRow("", self._command_status)

        # The command is not run through a shell, so "FOO=1 mycli" cannot work
        # there — variables belong here, same as an MCP server's env.
        self._env_edit = QTextEdit()
        self._env_edit.setPlaceholderText("KEY=VALUE (one per line)")
        self._env_edit.setFixedHeight(60)
        form.addRow("Env", self._env_edit)

        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("What it does — the assistant reads this")
        form.addRow("Description", self._description_edit)

        self._seed_help_check = QCheckBox("Read --help so the assistant learns the commands")
        self._seed_help_check.setChecked(True)
        form.addRow("", self._seed_help_check)

        self._help_depth_spin = QSpinBox()
        self._help_depth_spin.setRange(1, 3)
        self._help_depth_spin.setValue(DEFAULT_HELP_DEPTH)
        self._help_depth_spin.setToolTip(
            "1 = top-level help only (small, the assistant explores as it goes).\n"
            "2 = also read each subcommand's help (bigger, fewer round trips)."
        )
        self._help_depth_label = QLabel("Help depth")
        form.addRow(self._help_depth_label, self._help_depth_spin)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 120)
        self._timeout_spin.setValue(int(DEFAULT_TIMEOUT))
        self._timeout_spin.setSuffix(" s")
        form.addRow("Timeout", self._timeout_spin)

        edit_layout.addLayout(form)
        edit_layout.addStretch()
        self._stack.addWidget(edit_page)

        for tool in self._tools:
            self._tool_list.addItem(self._display_name(tool))

        # Connections
        self._tool_list.itemDoubleClicked.connect(self._on_item_activated)
        self._enabled_check.toggled.connect(self._sync_to_model)
        self._name_edit.textChanged.connect(self._sync_to_model)
        self._command_edit.textChanged.connect(self._sync_to_model)
        self._env_edit.textChanged.connect(self._sync_to_model)
        self._description_edit.textChanged.connect(self._sync_to_model)
        self._seed_help_check.toggled.connect(self._sync_to_model)
        self._help_depth_spin.valueChanged.connect(self._sync_to_model)
        self._timeout_spin.valueChanged.connect(self._sync_to_model)

    # -- navigation ----------------------------------------------------------

    def _show_list(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)

    def _show_edit(self, row: int) -> None:
        if row < 0 or row >= len(self._tools):
            return
        self._editing_row = row
        tool = self._tools[row]

        self._edit_title.setText(tool.get("name") or "New CLI Tool")

        widgets = (
            self._enabled_check,
            self._name_edit,
            self._command_edit,
            self._env_edit,
            self._description_edit,
            self._seed_help_check,
            self._help_depth_spin,
            self._timeout_spin,
        )
        for w in widgets:
            w.blockSignals(True)

        self._enabled_check.setChecked(tool.get("enabled", True))
        self._name_edit.setText(tool.get("name", ""))
        self._command_edit.setText(tool.get("command", ""))
        self._env_edit.setPlainText(tool.get("env", ""))
        self._description_edit.setText(tool.get("description", ""))
        self._seed_help_check.setChecked(tool.get("seed_help", True))
        self._help_depth_spin.setValue(int(tool.get("help_depth", DEFAULT_HELP_DEPTH) or 1))
        self._timeout_spin.setValue(int(tool.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT))

        for w in widgets:
            w.blockSignals(False)

        self._refresh_name_status()
        self._refresh_command_status()
        self._update_field_visibility()
        self._stack.setCurrentIndex(1)

    def _on_item_activated(self, _item: QListWidgetItem) -> None:
        self._show_edit(self._tool_list.currentRow())

    # -- add / remove --------------------------------------------------------

    def _add_tool(self) -> None:
        tool = {
            "enabled": True,
            "name": "",
            "command": "",
            "env": "",
            "description": "",
            "seed_help": True,
            "help_depth": DEFAULT_HELP_DEPTH,
            "timeout": DEFAULT_TIMEOUT,
        }
        self._tools.append(tool)
        self._tool_list.addItem(self._display_name(tool))
        self._show_edit(len(self._tools) - 1)
        self._name_edit.setFocus()

    def _remove_tool(self) -> None:
        row = self._tool_list.currentRow()
        if row < 0:
            return
        self._tools.pop(row)
        self._tool_list.takeItem(row)

    # -- edit form -----------------------------------------------------------

    def _sync_to_model(self) -> None:
        row = self._editing_row
        if row < 0 or row >= len(self._tools):
            return
        tool = self._tools[row]
        tool["enabled"] = self._enabled_check.isChecked()
        tool["name"] = self._name_edit.text().strip()
        tool["command"] = self._command_edit.text().strip()
        tool["env"] = self._env_edit.toPlainText().strip()
        tool["description"] = self._description_edit.text().strip()
        tool["seed_help"] = self._seed_help_check.isChecked()
        tool["help_depth"] = self._help_depth_spin.value()
        tool["timeout"] = float(self._timeout_spin.value())

        item = self._tool_list.item(row)
        if item:
            item.setText(self._display_name(tool))
        self._edit_title.setText(tool["name"] or "New CLI Tool")
        self._refresh_name_status()
        self._refresh_command_status()
        self._update_field_visibility()

    def _update_field_visibility(self) -> None:
        seeding = self._seed_help_check.isChecked()
        self._help_depth_label.setVisible(seeding)
        self._help_depth_spin.setVisible(seeding)

    def _refresh_name_status(self) -> None:
        typed = self._name_edit.text().strip()
        slug = slugify_tool_name(typed)
        if not typed:
            self._name_status.setText("")
            return
        if not slug:
            self._set_status(self._name_status, f"Unusable name: {typed}", ok=False)
            return
        self._set_status(self._name_status, f"The assistant calls this: {slug}", ok=True)

    def _refresh_command_status(self) -> None:
        command = self._command_edit.text().strip()
        if not command:
            self._command_status.setText("")
            return
        argv = resolve_command(command)
        if argv is None:
            self._set_status(self._command_status, f"Not found on PATH: {command}", ok=False)
        else:
            self._set_status(self._command_status, " ".join(argv), ok=True)

    @staticmethod
    def _set_status(label: QLabel, text: str, *, ok: bool) -> None:
        label.setText(text)
        label.setStyleSheet(
            f"font-size: 12px; color: {_OK_COLOR if ok else _ERR_COLOR}; background: transparent;"
        )

    @staticmethod
    def _display_name(tool: dict) -> str:
        name = tool.get("name") or "Unnamed"
        if not tool.get("enabled", True):
            return f"{name} (disabled)"
        return name

    # -- persistence ---------------------------------------------------------

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {"cli_tools": json.dumps(self._tools)}
