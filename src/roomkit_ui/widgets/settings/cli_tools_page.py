"""Local command-line tools with explicit actions and optional execution settings."""

from __future__ import annotations

import json
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QSpinBox,
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
from roomkit_ui.env_config import invalid_env_lines, parse_env_block
from roomkit_ui.widgets.settings.catalog_controls import CatalogNotice
from roomkit_ui.widgets.settings.controls import (
    AdvancedSection,
    FeedbackLabel,
    SettingsForm,
    SettingsSection,
    SettingsToggle,
    label,
    navigation_link,
)
from roomkit_ui.widgets.settings.integration_controls import (
    DetailStack,
    IntegrationCatalog,
)


class _CliToolsPage(QWidget):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._tools = parse_cli_tools(settings.get("cli_tools", "[]"))
        self._editing_row = -1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        self._stack = DetailStack()
        layout.addWidget(self._stack)
        self.catalog = IntegrationCatalog(
            "Command-line tools",
            "Make selected local commands available to your assistant.",
            "+ Add CLI tool",
            "No CLI tools yet",
            "Declare a command and describe when the assistant should use it.",
            "command-line",
        )
        self.catalog.add_requested.connect(self._add_tool)
        self.catalog.edit_requested.connect(self._show_edit)
        self.catalog.remove_requested.connect(self._remove_tool)
        self._stack.addWidget(self.catalog)
        layout.addWidget(self._grant_warning())
        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(20)
        self.back_button = navigation_link("← Back to CLI tools")
        self.back_button.clicked.connect(self._show_list)
        edit_layout.addWidget(self.back_button, 0, Qt.AlignLeft)
        self._edit_title = label("", "settingsSectionTitle")
        self._edit_title.setTextFormat(Qt.PlainText)
        edit_layout.addWidget(self._edit_title)
        enabled = SettingsSection("Availability")
        self._enabled_check = SettingsToggle("Enable CLI tool", True)
        enabled.add_row(
            "Enable CLI tool", "Allow the assistant to call this program.", self._enabled_check
        )
        edit_layout.addWidget(enabled)
        section = SettingsSection("Program")
        section.content.setContentsMargins(18, 16, 18, 16)
        form = SettingsForm()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. GitHub CLI")
        form.addRow("Name", self._name_edit)
        self._name_status = FeedbackLabel()
        form.addRow(self._name_status)
        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("e.g. gh")
        form.addRow("Command", self._command_edit)
        self._command_status = FeedbackLabel()
        form.addRow(self._command_status)
        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText("What it does — the assistant reads this")
        form.addRow("Description", self._description_edit)
        section.content.addLayout(form)
        edit_layout.addWidget(section)
        advanced = QWidget()
        details = SettingsForm(advanced)
        self._env_edit = QTextEdit()
        self._env_edit.setAcceptRichText(False)
        self._env_edit.setPlaceholderText("KEY=VALUE (one per line)")
        self._env_edit.setFixedHeight(90)
        details.addRow("Environment variables", self._env_edit)
        self._env_status = FeedbackLabel()
        details.addRow(self._env_status)
        self._seed_help_check = QCheckBox("Read --help so the assistant learns the commands")
        self._seed_help_check.setChecked(True)
        details.addRow(self._seed_help_check)
        self._help_depth_spin = QSpinBox()
        self._help_depth_spin.setRange(1, 3)
        self._help_depth_spin.setValue(DEFAULT_HELP_DEPTH)
        self._help_depth_spin.setToolTip(
            "1 = top-level help only.\n2 = also read each subcommand's help.\n"
            "3 = explore one level deeper."
        )
        self._help_depth_label = QLabel("Help depth")
        details.addRow(self._help_depth_label, self._help_depth_spin)
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 120)
        self._timeout_spin.setValue(int(DEFAULT_TIMEOUT))
        self._timeout_spin.setSuffix(" s")
        details.addRow("Timeout", self._timeout_spin)
        self.advanced = AdvancedSection("Advanced options", advanced)
        self._advanced_notice = FeedbackLabel()
        edit_layout.addWidget(self._advanced_notice)
        edit_layout.addWidget(self.advanced)
        self._stack.addWidget(edit_page)
        for tool in self._tools:
            self.catalog.append(*self._entry(tool))
        self._enabled_check.toggled.connect(self._sync_to_model)
        for field in (self._name_edit, self._command_edit, self._description_edit):
            field.textChanged.connect(self._sync_to_model)
        self._env_edit.textChanged.connect(self._sync_to_model)
        self._seed_help_check.toggled.connect(self._sync_to_model)
        self._help_depth_spin.valueChanged.connect(self._sync_to_model)
        self._timeout_spin.valueChanged.connect(self._sync_to_model)

    @staticmethod
    def _entry(tool: dict) -> tuple[str, str, str, str]:
        name = tool.get("name") or "Unnamed CLI tool"
        detail = tool.get("description") or "Local command-line program"
        if not tool.get("enabled", True):
            return name, detail, "Disabled", "neutral"
        if not slugify_tool_name(tool.get("name", "")) or not tool.get("command"):
            return name, detail, "Needs setup", "error"
        if resolve_command(tool["command"]) is None:
            return name, detail, "Command missing", "error"
        return name, detail, "Enabled", "active"

    @staticmethod
    def _grant_warning() -> CatalogNotice:
        """What declaring a CLI grants, said before anyone declares one.

        The argv is never run through a shell, but the CLI itself can run
        code: ``git -c alias.x='!sh -c …' x``, ``docker run``,
        ``kubectl exec``, ``npm exec``. And the arguments come from the
        model, which reads text it did not write (MCP results, skills).
        """
        note = CatalogNotice(
            "A declared CLI runs with your permissions and any arguments the "
            "assistant chooses — nothing asks you first. Many CLIs can run "
            "arbitrary code (git aliases, docker run, kubectl exec, npm exec), "
            "and what the assistant reads from MCP tools or skills can steer it. "
            "Declare only CLIs you would let it use freely, and give tokens in "
            "Env the least access that works.",
        )
        return note

    # -- navigation ----------------------------------------------------------

    def _show_list(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)
        self.catalog.refresh()

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
        self._refresh_env_status()
        self._update_field_visibility()
        self._stack.setCurrentIndex(1)

    # -- add / remove --------------------------------------------------------

    def _add_tool(self) -> None:
        tool = {
            # Keys the tool's env secrets in the keyring (settings.py), so it
            # must not change when the tool is renamed or saved again.
            "id": uuid.uuid4().hex,
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
        self.catalog.append(*self._entry(tool))
        self._show_edit(len(self._tools) - 1)
        self._name_edit.setFocus()

    def _remove_tool(self, row: int) -> None:
        if row < 0 or row >= len(self._tools):
            return
        self._tools.pop(row)
        self.catalog.remove(row)
        self._show_list()

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

        self.catalog.update_entry(row, *self._entry(tool))
        self._edit_title.setText(tool["name"] or "New CLI Tool")
        self._refresh_name_status()
        self._refresh_command_status()
        self._refresh_env_status()
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

    def _refresh_env_status(self) -> None:
        raw = self._env_edit.toPlainText().strip()
        self._advanced_notice.set_status(
            "Check environment variables in Advanced options." if invalid_env_lines(raw) else "",
            "error",
        )
        if not raw:
            self._env_status.setText("")
            return
        ignored = invalid_env_lines(raw)
        if ignored:
            self._set_status(
                self._env_status, f"Ignored, needs KEY=VALUE: {', '.join(ignored)}", ok=False
            )
            return
        # Names only: a value here is as likely to be an API token as a flag,
        # and settings pages get screen-shared.
        self._set_status(self._env_status, f"Sets: {', '.join(parse_env_block(raw))}", ok=True)

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
    def _set_status(label: FeedbackLabel, text: str, *, ok: bool) -> None:
        label.set_status(text, "success" if ok else "error")

    # -- persistence ---------------------------------------------------------

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {"cli_tools": json.dumps(self._tools)}
