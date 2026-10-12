"""MCP server configuration, with explicit list actions and optional connection details."""

from __future__ import annotations

import json
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from roomkit_ui.mcp_config import (
    is_blank_mcp_server,
    mcp_server_problem,
    parse_mcp_servers,
    uses_instructions,
    uses_skills,
    validate_mcp_http_url,
)
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

MCP_TRANSPORTS = [
    ("Local process (stdio)", "stdio"),
    ("Server-sent events (SSE)", "sse"),
    ("Streamable HTTP", "streamable_http"),
]
MCP_AUTH_MODES = [("None", "none"), ("OAuth2", "oauth2")]


class _MCPPage(QWidget):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._servers = parse_mcp_servers(settings.get("mcp_servers", "[]"))
        self._editing_row = -1
        self._oauth_pending: set[str] = set()
        self._oauth_outcomes: dict[tuple[str, str], tuple[str, bool]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        self._stack = DetailStack()
        layout.addWidget(self._stack)
        self.catalog = IntegrationCatalog(
            "Connected tools",
            "MCP servers expose tools your assistant can use.",
            "+ Add server",
            "No MCP servers yet",
            "Connect a server to bring external tools into your conversations.",
            "plug",
        )
        self.catalog.add_requested.connect(self._add_server)
        self.catalog.edit_requested.connect(self._show_edit)
        self.catalog.remove_requested.connect(self._remove_server)
        self._stack.addWidget(self.catalog)
        layout.addWidget(
            CatalogNotice(
                "Enabled servers connect when a conversation starts. Configuration, authorization "
                "and connection are separate states; connectivity is not tested here.",
            )
        )
        edit_page = QWidget()
        edit_layout = QVBoxLayout(edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(20)
        self.back_button = navigation_link("← Back to servers")
        self.back_button.clicked.connect(self._show_list)
        edit_layout.addWidget(self.back_button, 0, Qt.AlignLeft)
        self._edit_title = label("", "settingsSectionTitle")
        self._edit_title.setTextFormat(Qt.PlainText)
        edit_layout.addWidget(self._edit_title)
        enabled = SettingsSection("Availability")
        self._enabled_check = SettingsToggle("Enable server", True)
        enabled.add_row(
            "Enable server",
            "Make this server available for your next conversation.",
            self._enabled_check,
        )
        self._skills_check = SettingsToggle("Use its skills", True)
        enabled.add_row(
            "Use its skills",
            "Skills the server publishes reach the assistant, which reads one when it needs "
            "it. Before a CLI tool runs on a skill's behalf, you are asked.",
            self._skills_check,
        )
        self._instructions_check = SettingsToggle("Pass its instructions to the model", True)
        enabled.add_row(
            "Pass its instructions to the model",
            "What the server says about using its tools joins the assistant's instructions, "
            "marked as the server's text. Very long instructions are cut; the log says so.",
            self._instructions_check,
        )
        edit_layout.addWidget(enabled)
        section = SettingsSection("Connection")
        section.content.setContentsMargins(18, 16, 18, 16)
        section.content.setSpacing(10)
        form = SettingsForm()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Filesystem")
        form.addRow("Name", self._name_edit)
        self._transport_combo = QComboBox()
        for title, _value in MCP_TRANSPORTS:
            self._transport_combo.addItem(title)
        form.addRow("Transport", self._transport_combo)
        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("e.g. npx")
        self._command_label = QLabel("Command")
        form.addRow(self._command_label, self._command_edit)
        self._args_edit = QLineEdit()
        self._args_edit.setPlaceholderText("e.g. -y @modelcontextprotocol/server-filesystem /home")
        self._args_label = QLabel("Arguments")
        form.addRow(self._args_label, self._args_edit)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. https://example.com/mcp")
        self._url_label = QLabel("Server URL")
        form.addRow(self._url_label, self._url_edit)
        self._auth_combo = QComboBox()
        for title, _value in MCP_AUTH_MODES:
            self._auth_combo.addItem(title)
        self._auth_label = QLabel("Authentication")
        form.addRow(self._auth_label, self._auth_combo)
        section.content.addLayout(form)
        self._connection_status = FeedbackLabel()
        section.content.addWidget(self._connection_status)
        edit_layout.addWidget(section)

        self._oauth_token_row_widget = QWidget()
        token_layout = QVBoxLayout(self._oauth_token_row_widget)
        token_layout.setContentsMargins(0, 0, 0, 0)
        self._oauth_status = FeedbackLabel()
        token_layout.addWidget(self._oauth_status)
        token_row = QHBoxLayout()
        self._authorize_btn = QPushButton("Authorize in browser")
        self._authorize_btn.setAutoDefault(False)
        self._authorize_btn.clicked.connect(self._on_authorize_clicked)
        token_row.addWidget(self._authorize_btn)
        self._clear_token_btn = QPushButton("Clear token")
        self._clear_token_btn.setAutoDefault(False)
        self._clear_token_btn.clicked.connect(self._on_clear_token_clicked)
        token_row.addWidget(self._clear_token_btn)
        token_row.addStretch()
        token_layout.addLayout(token_row)
        edit_layout.addWidget(self._oauth_token_row_widget)

        advanced = QWidget()
        details = SettingsForm(advanced)
        self._env_edit = QTextEdit()
        self._env_edit.setAcceptRichText(False)
        self._env_edit.setPlaceholderText("KEY=VALUE (one per line)")
        self._env_edit.setFixedHeight(90)
        details.addRow("Environment variables", self._env_edit)
        self._oauth_client_id = QLineEdit()
        self._oauth_client_id.setPlaceholderText("Auto-detected via dynamic registration")
        self._oauth_client_id_label = QLabel("OAuth client ID")
        details.addRow(self._oauth_client_id_label, self._oauth_client_id)
        self._oauth_client_secret = QLineEdit()
        self._oauth_client_secret.setEchoMode(QLineEdit.Password)
        self._oauth_client_secret.setPlaceholderText("Leave empty for public clients")
        self._oauth_client_secret_label = QLabel("OAuth client secret")
        details.addRow(self._oauth_client_secret_label, self._oauth_client_secret)
        self._oauth_scopes = QLineEdit()
        self._oauth_scopes.setPlaceholderText("e.g. read write")
        self._oauth_scopes_label = QLabel("OAuth scopes")
        details.addRow(self._oauth_scopes_label, self._oauth_scopes)
        self.advanced = AdvancedSection("Advanced options", advanced)
        edit_layout.addWidget(self.advanced)
        self._stack.addWidget(edit_page)
        for server in self._servers:
            self.catalog.append(*self._entry(server))
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        self._auth_combo.currentIndexChanged.connect(self._on_auth_changed)
        self._enabled_check.toggled.connect(self._sync_to_model)
        self._skills_check.toggled.connect(self._sync_to_model)
        self._instructions_check.toggled.connect(self._sync_to_model)
        for field in (
            self._name_edit,
            self._command_edit,
            self._args_edit,
            self._url_edit,
            self._oauth_client_id,
            self._oauth_client_secret,
            self._oauth_scopes,
        ):
            field.textChanged.connect(self._sync_to_model)
        self._env_edit.textChanged.connect(self._sync_to_model)

    @staticmethod
    def _entry(server: dict) -> tuple[str, str, str, str]:
        name = server.get("name") or "Unnamed server"
        detail = dict((value, title) for title, value in MCP_TRANSPORTS).get(
            server.get("transport", "stdio"), "MCP server"
        )
        address = (
            server.get("command")
            if server.get("transport", "stdio") == "stdio"
            else server.get("url")
        )
        if address:
            detail += f" · {address}"
        if not server.get("enabled", True):
            return name, detail, "Disabled", "neutral"
        if mcp_server_problem(server):
            return name, detail, "Needs setup", "error"
        if server.get("transport", "stdio") != "stdio":
            try:
                validate_mcp_http_url(server.get("url"))
            except ValueError:
                return name, detail, "Needs setup", "error"
        return name, detail, "Enabled", "active"

    # -- navigation ----------------------------------------------------------

    def _show_list(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)
        self.catalog.refresh()

    def _show_edit(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            return
        self._editing_row = row
        srv = self._servers[row]
        if not str(srv.get("id", "") or "").strip():
            srv["id"] = uuid.uuid4().hex

        self._edit_title.setText(srv.get("name") or "New Server")

        # Block signals while populating
        for w in (
            self._enabled_check,
            self._skills_check,
            self._instructions_check,
            self._name_edit,
            self._command_edit,
            self._args_edit,
            self._url_edit,
            self._env_edit,
            self._transport_combo,
            self._auth_combo,
            self._oauth_client_id,
            self._oauth_client_secret,
            self._oauth_scopes,
        ):
            w.blockSignals(True)

        self._enabled_check.setChecked(srv.get("enabled", True))
        self._skills_check.setChecked(uses_skills(srv))
        self._instructions_check.setChecked(uses_instructions(srv))
        self._name_edit.setText(srv.get("name", ""))
        self._command_edit.setText(srv.get("command", ""))
        self._args_edit.setText(srv.get("args", ""))
        self._url_edit.setText(srv.get("url", ""))
        self._env_edit.setPlainText(srv.get("env", ""))

        transport = srv.get("transport", "stdio")
        for i, (_label, val) in enumerate(MCP_TRANSPORTS):
            if val == transport:
                self._transport_combo.setCurrentIndex(i)
                break

        auth = srv.get("auth", "none")
        for i, (_label, val) in enumerate(MCP_AUTH_MODES):
            if val == auth:
                self._auth_combo.setCurrentIndex(i)
                break

        self._oauth_client_id.setText(srv.get("oauth_client_id", ""))
        self._oauth_client_secret.setText(srv.get("oauth_client_secret", ""))
        self._oauth_scopes.setText(srv.get("oauth_scopes", ""))

        for w in (
            self._enabled_check,
            self._skills_check,
            self._instructions_check,
            self._name_edit,
            self._command_edit,
            self._args_edit,
            self._url_edit,
            self._env_edit,
            self._transport_combo,
            self._auth_combo,
            self._oauth_client_id,
            self._oauth_client_secret,
            self._oauth_scopes,
        ):
            w.blockSignals(False)

        self._update_field_visibility(transport)
        self._refresh_oauth_status(
            str(srv.get("id", "") or srv.get("name", "")), str(srv.get("url", ""))
        )
        self._stack.setCurrentIndex(1)
        self._refresh_connection_status()

    # -- add / remove --------------------------------------------------------

    def _add_server(self) -> None:
        srv = {
            "id": uuid.uuid4().hex,
            "enabled": True,
            "skills": True,
            "instructions": True,
            "name": "",
            "transport": "stdio",
            "command": "",
            "args": "",
            "url": "",
            "env": "",
            "auth": "none",
            "oauth_client_id": "",
            # Empty until the user supplies their own client secret.
            "oauth_client_secret": "",  # nosec B105
            "oauth_scopes": "",
        }
        self._servers.append(srv)
        self.catalog.append(*self._entry(srv))
        self._show_edit(len(self._servers) - 1)
        self._name_edit.setFocus()

    def _remove_server(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            return
        self._servers.pop(row)
        self.catalog.remove(row)
        self._show_list()

    # -- edit form -----------------------------------------------------------

    def _on_transport_changed(self, _index: int) -> None:
        transport = MCP_TRANSPORTS[self._transport_combo.currentIndex()][1]
        self._update_field_visibility(transport)
        self._sync_to_model()

    def _on_auth_changed(self, _index: int) -> None:
        transport = MCP_TRANSPORTS[self._transport_combo.currentIndex()][1]
        self._update_field_visibility(transport)
        self._sync_to_model()

    def _update_field_visibility(self, transport: str) -> None:
        is_stdio = transport == "stdio"
        self._command_label.setVisible(is_stdio)
        self._command_edit.setVisible(is_stdio)
        self._args_label.setVisible(is_stdio)
        self._args_edit.setVisible(is_stdio)
        self._url_label.setVisible(not is_stdio)
        self._url_edit.setVisible(not is_stdio)

        # Auth fields: only for HTTP transports
        is_http = not is_stdio
        auth = MCP_AUTH_MODES[self._auth_combo.currentIndex()][1]
        is_oauth = is_http and auth == "oauth2"

        self._auth_label.setVisible(is_http)
        self._auth_combo.setVisible(is_http)
        self._oauth_client_id_label.setVisible(is_oauth)
        self._oauth_client_id.setVisible(is_oauth)
        self._oauth_client_secret_label.setVisible(is_oauth)
        self._oauth_client_secret.setVisible(is_oauth)
        self._oauth_scopes_label.setVisible(is_oauth)
        self._oauth_scopes.setVisible(is_oauth)
        self._oauth_token_row_widget.setVisible(is_oauth)

    def _sync_to_model(self) -> None:
        row = self._editing_row
        if row < 0 or row >= len(self._servers):
            return
        srv = self._servers[row]
        srv["enabled"] = self._enabled_check.isChecked()
        srv["skills"] = self._skills_check.isChecked()
        srv["instructions"] = self._instructions_check.isChecked()
        srv["name"] = self._name_edit.text().strip()
        srv["transport"] = MCP_TRANSPORTS[self._transport_combo.currentIndex()][1]
        srv["command"] = self._command_edit.text().strip()
        srv["args"] = self._args_edit.text().strip()
        srv["url"] = self._url_edit.text().strip()
        srv["env"] = self._env_edit.toPlainText()
        srv["auth"] = MCP_AUTH_MODES[self._auth_combo.currentIndex()][1]
        srv["oauth_client_id"] = self._oauth_client_id.text().strip()
        srv["oauth_client_secret"] = self._oauth_client_secret.text().strip()
        srv["oauth_scopes"] = self._oauth_scopes.text().strip()
        self.catalog.update_entry(row, *self._entry(srv))
        self._edit_title.setText(srv["name"] or "New Server")
        self._refresh_connection_status()
        self._refresh_oauth_status(str(srv["id"]), str(srv.get("url", "")))

    def _refresh_connection_status(self) -> None:
        if self._editing_row < 0:
            return
        server = self._servers[self._editing_row]
        problem = mcp_server_problem(server)
        if not problem and server.get("transport") != "stdio":
            try:
                validate_mcp_http_url(server.get("url"))
            except ValueError as exc:
                problem = str(exc)
        self._connection_status.set_status(
            f"Check connection settings: {problem}"
            if problem
            else "Connection will be attempted when a conversation starts.",
            "error" if problem else "neutral",
        )

    # -- OAuth actions -------------------------------------------------------

    def _refresh_oauth_status(self, server_name: str, server_url: str | None = None) -> None:
        """Authorization belongs to a server identity and URL, not the visible form."""
        from roomkit_ui.mcp_auth import has_oauth_tokens

        pending = server_name in self._oauth_pending
        self._authorize_btn.setEnabled(not pending)
        self._clear_token_btn.setEnabled(not pending)
        if pending:
            self._oauth_status.set_status("Authorization in progress in your browser…", "active")
        elif outcome := self._oauth_outcomes.get((server_name, server_url or "")):
            text, ok = outcome
            self._oauth_status.set_status(text, "success" if ok else "error")
        elif server_name and has_oauth_tokens(server_name, server_url):
            self._oauth_status.set_status(
                "Token stored · server connectivity not tested", "success"
            )
        else:
            self._oauth_status.set_status("Not authorized")

    def _on_authorize_clicked(self) -> None:
        server_name = self._name_edit.text().strip()
        server_id = self._current_server_id()
        if server_id in self._oauth_pending:
            return
        try:
            server_url = validate_mcp_http_url(self._url_edit.text())
        except ValueError as exc:
            self._oauth_status.set_status(str(exc), "error")
            return
        if not server_id or not server_name:
            self._oauth_status.set_status("Set server name and URL first", "error")
            return
        self._oauth_pending.add(server_id)
        self._refresh_oauth_status(server_id, server_url)
        import asyncio

        # Capture credentials before yielding: changing rows must never swap them.
        asyncio.ensure_future(
            self._run_oauth_flow(
                server_id,
                server_url,
                client_id=self._oauth_client_id.text().strip() or None,
                client_secret=self._oauth_client_secret.text().strip() or None,
                scopes=self._oauth_scopes.text().strip() or None,
            )
        )

    async def _run_oauth_flow(
        self,
        server_name: str,
        server_url: str,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        scopes: str | None = None,
    ) -> None:
        """The token can finish storing after the dialog or this editor is left."""
        self._oauth_pending.add(server_name)
        try:
            from roomkit_ui.mcp_auth import create_oauth_provider, has_oauth_tokens

            provider, callback_server = await create_oauth_provider(
                server_url=server_url,
                server_name=server_name,
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
            )
            try:
                import httpx

                async with httpx.AsyncClient(auth=provider, timeout=320) as client:
                    await client.get(server_url)
            finally:
                await callback_server.stop()
            ok = has_oauth_tokens(server_name, server_url)
            self._oauth_outcomes[(server_name, server_url)] = (
                "Token stored · server connectivity not tested"
                if ok
                else "No OAuth token received",
                ok,
            )
        except TimeoutError:
            self._oauth_outcomes[(server_name, server_url)] = ("Authorization timed out", False)
        except Exception as exc:
            self._oauth_outcomes[(server_name, server_url)] = (
                f"Authorization failed: {exc}",
                False,
            )
        finally:
            self._oauth_pending.discard(server_name)
            if isValid(self) and self._editing_row >= 0:
                self._refresh_oauth_status(
                    self._current_server_id(), self._url_edit.text().strip()
                )

    def _on_clear_token_clicked(self) -> None:
        server_id = self._current_server_id()
        if not server_id or server_id in self._oauth_pending:
            return
        from roomkit_ui.mcp_auth import clear_oauth_tokens

        clear_oauth_tokens(server_id)
        self._oauth_outcomes = {
            key: value for key, value in self._oauth_outcomes.items() if key[0] != server_id
        }
        self._refresh_oauth_status(server_id, self._url_edit.text().strip())

    def _current_server_id(self) -> str:
        row = self._editing_row
        if row < 0 or row >= len(self._servers):
            return ""
        srv = self._servers[row]
        server_id = str(srv.get("id", "") or "").strip()
        if not server_id:
            server_id = uuid.uuid4().hex
            srv["id"] = server_id
        return server_id

    def get_servers_json(self) -> str:
        """Return server configs as a JSON string for saving.

        An entry "Add server" made and nobody filled in is not saved: it is
        not a server, and the next session would try to launch it.
        """
        return json.dumps([srv for srv in self._servers if not is_blank_mcp_server(srv)])

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "mcp_servers": self.get_servers_json(),
        }
