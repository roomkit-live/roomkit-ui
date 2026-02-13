"""MCP Servers configuration page with list/edit navigation."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

MCP_TRANSPORTS = [
    ("Stdio", "stdio"),
    ("SSE", "sse"),
    ("Streamable HTTP", "streamable_http"),
]

MCP_AUTH_MODES = [
    ("None", "none"),
    ("OAuth2", "oauth2"),
]


class _MCPPage(QWidget):
    """MCP Servers configuration page with list/edit navigation."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._servers: list[dict] = []
        try:
            self._servers = json.loads(settings.get("mcp_servers", "[]"))
        except (json.JSONDecodeError, TypeError):
            self._servers = []

        self._editing_row = -1
        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── Page 0: Server list ──
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        title = QLabel("MCP Servers")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        list_layout.addWidget(title)

        desc = QLabel(
            "Configure Model Context Protocol servers to give the "
            "voice assistant access to external tools."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        list_layout.addWidget(desc)

        self._server_list = QListWidget()
        self._server_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
        )
        list_layout.addWidget(self._server_list, 1)

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
        add_btn.clicked.connect(self._add_server)
        remove_btn = QPushButton("\u2212")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setStyleSheet(_btn_style)
        remove_btn.clicked.connect(self._remove_server)
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

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setChecked(True)
        form.addRow("", self._enabled_check)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Filesystem")
        form.addRow("Name", self._name_edit)

        self._transport_combo = QComboBox()
        for label, _val in MCP_TRANSPORTS:
            self._transport_combo.addItem(label)
        form.addRow("Transport", self._transport_combo)

        self._command_edit = QLineEdit()
        self._command_edit.setPlaceholderText("e.g. npx")
        self._command_label = QLabel("Command")
        form.addRow(self._command_label, self._command_edit)

        self._args_edit = QLineEdit()
        self._args_edit.setPlaceholderText("e.g. -y @modelcontextprotocol/server-filesystem /home")
        self._args_label = QLabel("Args")
        form.addRow(self._args_label, self._args_edit)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("e.g. http://localhost:8000/mcp")
        self._url_label = QLabel("URL")
        form.addRow(self._url_label, self._url_edit)

        self._env_edit = QTextEdit()
        self._env_edit.setPlaceholderText("KEY=VALUE (one per line)")
        self._env_edit.setFixedHeight(60)
        form.addRow("Env", self._env_edit)

        # -- OAuth2 fields (visible for HTTP transports only) --
        self._auth_combo = QComboBox()
        for label, _val in MCP_AUTH_MODES:
            self._auth_combo.addItem(label)
        self._auth_label = QLabel("Auth")
        form.addRow(self._auth_label, self._auth_combo)

        self._oauth_client_id = QLineEdit()
        self._oauth_client_id.setPlaceholderText("Auto-detected via dynamic registration")
        self._oauth_client_id_label = QLabel("Client ID")
        form.addRow(self._oauth_client_id_label, self._oauth_client_id)

        self._oauth_client_secret = QLineEdit()
        self._oauth_client_secret.setEchoMode(QLineEdit.Password)
        self._oauth_client_secret.setPlaceholderText("Leave empty for public clients")
        self._oauth_client_secret_label = QLabel("Client Secret")
        form.addRow(self._oauth_client_secret_label, self._oauth_client_secret)

        self._oauth_scopes = QLineEdit()
        self._oauth_scopes.setPlaceholderText("e.g. read write")
        self._oauth_scopes_label = QLabel("Scopes")
        form.addRow(self._oauth_scopes_label, self._oauth_scopes)

        # Token status row
        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self._oauth_status = QLabel("")
        self._oauth_status.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        token_row.addWidget(self._oauth_status, 1)
        self._authorize_btn = QPushButton("Authorize")
        self._authorize_btn.setCursor(Qt.PointingHandCursor)
        self._authorize_btn.setFixedHeight(28)
        self._authorize_btn.clicked.connect(self._on_authorize_clicked)
        token_row.addWidget(self._authorize_btn)
        self._clear_token_btn = QPushButton("Clear Token")
        self._clear_token_btn.setCursor(Qt.PointingHandCursor)
        self._clear_token_btn.setFixedHeight(28)
        self._clear_token_btn.clicked.connect(self._on_clear_token_clicked)
        token_row.addWidget(self._clear_token_btn)
        self._oauth_token_row_widget = QWidget()
        self._oauth_token_row_widget.setLayout(token_row)
        form.addRow("", self._oauth_token_row_widget)

        edit_layout.addLayout(form)
        edit_layout.addStretch()

        self._stack.addWidget(edit_page)

        # Start on list page
        self._stack.setCurrentIndex(0)

        # Populate list
        for srv in self._servers:
            self._server_list.addItem(self._display_name(srv))

        # Connections
        self._server_list.itemDoubleClicked.connect(self._on_item_activated)
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        self._auth_combo.currentIndexChanged.connect(self._on_auth_changed)
        self._enabled_check.toggled.connect(self._sync_to_model)
        self._name_edit.textChanged.connect(self._sync_to_model)
        self._command_edit.textChanged.connect(self._sync_to_model)
        self._args_edit.textChanged.connect(self._sync_to_model)
        self._url_edit.textChanged.connect(self._sync_to_model)
        self._env_edit.textChanged.connect(self._sync_to_model)
        self._oauth_client_id.textChanged.connect(self._sync_to_model)
        self._oauth_client_secret.textChanged.connect(self._sync_to_model)
        self._oauth_scopes.textChanged.connect(self._sync_to_model)

    # -- navigation ----------------------------------------------------------

    def _show_list(self) -> None:
        self._editing_row = -1
        self._stack.setCurrentIndex(0)

    def _show_edit(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            return
        self._editing_row = row
        srv = self._servers[row]

        self._edit_title.setText(srv.get("name") or "New Server")

        # Block signals while populating
        for w in (
            self._enabled_check,
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
        self._refresh_oauth_status(srv.get("name", ""))
        self._stack.setCurrentIndex(1)

    def _on_item_activated(self, _item: QListWidgetItem) -> None:
        row = self._server_list.currentRow()
        self._show_edit(row)

    # -- add / remove --------------------------------------------------------

    def _add_server(self) -> None:
        srv = {
            "enabled": True,
            "name": "",
            "transport": "stdio",
            "command": "",
            "args": "",
            "url": "",
            "env": "",
            "auth": "none",
            "oauth_client_id": "",
            "oauth_client_secret": "",  # nosec B105 — empty default, not a real secret
            "oauth_scopes": "",
        }
        self._servers.append(srv)
        self._server_list.addItem(self._display_name(srv))
        self._show_edit(len(self._servers) - 1)
        self._name_edit.setFocus()

    def _remove_server(self) -> None:
        row = self._server_list.currentRow()
        if row < 0:
            return
        self._servers.pop(row)
        self._server_list.takeItem(row)

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
        # Update list item text
        item = self._server_list.item(row)
        if item:
            item.setText(self._display_name(srv))
        # Update edit title
        self._edit_title.setText(srv["name"] or "New Server")

    # -- OAuth actions -------------------------------------------------------

    def _refresh_oauth_status(self, server_name: str) -> None:
        """Update the token status label for the current server."""
        if not server_name:
            self._oauth_status.setText("")
            return
        from roomkit_ui.mcp_auth import has_oauth_tokens

        if has_oauth_tokens(server_name):
            self._oauth_status.setText("Token stored")
            self._oauth_status.setStyleSheet(
                "font-size: 12px; color: #4caf50; background: transparent;"
            )
        else:
            self._oauth_status.setText("Not authorized")
            c = colors()
            self._oauth_status.setStyleSheet(
                f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
            )

    def _on_authorize_clicked(self) -> None:
        server_name = self._name_edit.text().strip()
        server_url = self._url_edit.text().strip()
        if not server_name or not server_url:
            self._oauth_status.setText("Set server name and URL first")
            self._oauth_status.setStyleSheet(
                "font-size: 12px; color: #f44336; background: transparent;"
            )
            return
        self._authorize_btn.setEnabled(False)
        self._oauth_status.setText("Waiting for browser...")
        self._oauth_status.setStyleSheet(
            "font-size: 12px; color: #ff9800; background: transparent;"
        )
        import asyncio

        asyncio.ensure_future(self._run_oauth_flow(server_name, server_url))

    async def _run_oauth_flow(self, server_name: str, server_url: str) -> None:
        """Trigger the OAuth authorization flow in the background."""
        try:
            from roomkit_ui.mcp_auth import create_oauth_provider

            provider, callback_server = await create_oauth_provider(
                server_url=server_url,
                server_name=server_name,
                client_id=self._oauth_client_id.text().strip() or None,
                client_secret=self._oauth_client_secret.text().strip() or None,
                scopes=self._oauth_scopes.text().strip() or None,
            )
            try:
                # Make a probe request to trigger the SDK's OAuth flow
                # (401 → discovery → browser → callback → token exchange)
                import httpx

                async with httpx.AsyncClient(auth=provider, timeout=320) as client:
                    await client.get(server_url)
            finally:
                await callback_server.stop()

            self._oauth_status.setText("Token stored")
            self._oauth_status.setStyleSheet(
                "font-size: 12px; color: #4caf50; background: transparent;"
            )
        except TimeoutError:
            self._oauth_status.setText("Authorization timed out")
            self._oauth_status.setStyleSheet(
                "font-size: 12px; color: #f44336; background: transparent;"
            )
        except Exception as exc:
            self._oauth_status.setText(f"Error: {exc}")
            self._oauth_status.setStyleSheet(
                "font-size: 12px; color: #f44336; background: transparent;"
            )
        finally:
            try:
                self._authorize_btn.setEnabled(True)
            except Exception:
                pass

    def _on_clear_token_clicked(self) -> None:
        server_name = self._name_edit.text().strip()
        if not server_name:
            return
        from roomkit_ui.mcp_auth import clear_oauth_tokens

        clear_oauth_tokens(server_name)
        self._refresh_oauth_status(server_name)

    @staticmethod
    def _display_name(srv: dict) -> str:
        name = srv.get("name") or "Unnamed"
        if not srv.get("enabled", True):
            return f"{name} (disabled)"
        return name

    def get_servers_json(self) -> str:
        """Return server configs as a JSON string for saving."""
        return json.dumps(self._servers)

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "mcp_servers": self.get_servers_json(),
        }
