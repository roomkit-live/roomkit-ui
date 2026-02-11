"""Settings dialog with vertical tab navigation."""

from __future__ import annotations

import json

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from room_ui.settings import load_settings, save_settings
from room_ui.theme import colors
from room_ui.widgets.hotkey_button import HotkeyButton

GEMINI_MODELS = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.0-flash-live-001",
]
GEMINI_VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Puck"]

OPENAI_MODELS = [
    "gpt-4o-realtime-preview",
]
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

PROVIDERS = [
    ("Google Gemini", "gemini"),
    ("OpenAI", "openai"),
]

AEC_MODES = [
    ("WebRTC (recommended)", "webrtc"),
    ("Speex", "speex"),
    ("None", "none"),
]


def _list_audio_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (input_devices, output_devices) as lists of (index, name)."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs: list[tuple[int, str]] = []
        outputs: list[tuple[int, str]] = []
        for i, d in enumerate(devices):
            name = d["name"]
            if d["max_input_channels"] > 0:
                inputs.append((i, name))
            if d["max_output_channels"] > 0:
                outputs.append((i, name))
        return inputs, outputs
    except Exception:
        return [], []


# ---------------------------------------------------------------------------
# Tab pages
# ---------------------------------------------------------------------------


THEMES = [
    ("Dark", "dark"),
    ("Light", "light"),
]


class _GeneralPage(QWidget):
    """General settings: audio device selection + theme."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        c = colors()

        title = QLabel("General")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # Theme selector
        theme_section = QLabel("Appearance")
        theme_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(theme_section)

        theme_form = QFormLayout()
        theme_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        theme_form.setSpacing(10)
        theme_form.setLabelAlignment(Qt.AlignRight)
        self.theme_combo = QComboBox()
        for label, _value in THEMES:
            self.theme_combo.addItem(label)
        current_theme = settings.get("theme", "dark")
        for i, (_, val) in enumerate(THEMES):
            if val == current_theme:
                self.theme_combo.setCurrentIndex(i)
                break
        theme_form.addRow("Theme", self.theme_combo)
        layout.addLayout(theme_form)

        # Audio devices
        section = QLabel("Audio Devices")
        section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(section)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        inputs, outputs = _list_audio_devices()

        self.input_combo = QComboBox()
        self.input_combo.addItem("System Default", None)
        for idx, name in inputs:
            self.input_combo.addItem(name, idx)
        saved_input = settings.get("input_device")
        if saved_input is not None:
            for i in range(self.input_combo.count()):
                if self.input_combo.itemData(i) == saved_input:
                    self.input_combo.setCurrentIndex(i)
                    break
        form.addRow("Microphone", self.input_combo)

        self.output_combo = QComboBox()
        self.output_combo.addItem("System Default", None)
        for idx, name in outputs:
            self.output_combo.addItem(name, idx)
        saved_output = settings.get("output_device")
        if saved_output is not None:
            for i in range(self.output_combo.count()):
                if self.output_combo.itemData(i) == saved_output:
                    self.output_combo.setCurrentIndex(i)
                    break
        form.addRow("Speaker", self.output_combo)

        layout.addLayout(form)
        layout.addStretch()


class _AIPage(QWidget):
    """AI settings: provider selector, API key, model, voice, AEC, denoise, prompt."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("AI Provider")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Provider selector
        self.provider = QComboBox()
        for label, _value in PROVIDERS:
            self.provider.addItem(label)
        current_provider = settings.get("provider", "gemini")
        for i, (_, val) in enumerate(PROVIDERS):
            if val == current_provider:
                self.provider.setCurrentIndex(i)
                break
        form.addRow("Provider", self.provider)

        # API keys (one per provider, shown/hidden)
        self.gemini_api_key = QLineEdit(settings.get("api_key", ""))
        self.gemini_api_key.setEchoMode(QLineEdit.Password)
        self.gemini_api_key.setPlaceholderText("Enter your Google API key")
        self._gemini_key_label = QLabel("API Key")
        form.addRow(self._gemini_key_label, self.gemini_api_key)

        self.openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("Enter your OpenAI API key")
        self._openai_key_label = QLabel("API Key")
        form.addRow(self._openai_key_label, self.openai_api_key)

        # Model (Gemini)
        self.gemini_model = QComboBox()
        self.gemini_model.setEditable(True)
        self.gemini_model.addItems(GEMINI_MODELS)
        current_model = settings.get("model", GEMINI_MODELS[0])
        idx = self.gemini_model.findText(current_model)
        if idx >= 0:
            self.gemini_model.setCurrentIndex(idx)
        else:
            self.gemini_model.setCurrentText(current_model)
        self._gemini_model_label = QLabel("Model")
        form.addRow(self._gemini_model_label, self.gemini_model)

        # Model (OpenAI)
        self.openai_model = QComboBox()
        self.openai_model.setEditable(True)
        self.openai_model.addItems(OPENAI_MODELS)
        current_oai_model = settings.get("openai_model", OPENAI_MODELS[0])
        oidx = self.openai_model.findText(current_oai_model)
        if oidx >= 0:
            self.openai_model.setCurrentIndex(oidx)
        else:
            self.openai_model.setCurrentText(current_oai_model)
        self._openai_model_label = QLabel("Model")
        form.addRow(self._openai_model_label, self.openai_model)

        # Voice (Gemini)
        self.gemini_voice = QComboBox()
        self.gemini_voice.addItems(GEMINI_VOICES)
        current_voice = settings.get("voice", "Aoede")
        vidx = self.gemini_voice.findText(current_voice)
        if vidx >= 0:
            self.gemini_voice.setCurrentIndex(vidx)
        self._gemini_voice_label = QLabel("Voice")
        form.addRow(self._gemini_voice_label, self.gemini_voice)

        # Voice (OpenAI)
        self.openai_voice = QComboBox()
        self.openai_voice.addItems(OPENAI_VOICES)
        current_oai_voice = settings.get("openai_voice", "alloy")
        ovidx = self.openai_voice.findText(current_oai_voice)
        if ovidx >= 0:
            self.openai_voice.setCurrentIndex(ovidx)
        self._openai_voice_label = QLabel("Voice")
        form.addRow(self._openai_voice_label, self.openai_voice)

        # AEC
        self.aec = QComboBox()
        for label, _value in AEC_MODES:
            self.aec.addItem(label)
        current_aec = settings.get("aec_mode", "webrtc")
        for i, (_, val) in enumerate(AEC_MODES):
            if val == current_aec:
                self.aec.setCurrentIndex(i)
                break
        form.addRow("Echo Cancel", self.aec)

        # Denoise
        self.denoise = QCheckBox("Enable RNNoise denoiser")
        self.denoise.setChecked(bool(settings.get("denoise", False)))
        form.addRow("", self.denoise)

        layout.addLayout(form)

        # System prompt
        section = QLabel("System Prompt")
        section.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #8E8E93;"
            " text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(section)
        self.prompt = QTextEdit()
        self.prompt.setLineWrapMode(QTextEdit.WidgetWidth)
        self.prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.prompt.setPlainText(
            settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
        )
        self.prompt.setFixedHeight(80)
        layout.addWidget(self.prompt)
        layout.addStretch()

        # Wire provider switch
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        self._on_provider_changed(self.provider.currentIndex())

    def _on_provider_changed(self, index: int) -> None:
        is_gemini = PROVIDERS[index][1] == "gemini"
        # Gemini fields
        self._gemini_key_label.setVisible(is_gemini)
        self.gemini_api_key.setVisible(is_gemini)
        self._gemini_model_label.setVisible(is_gemini)
        self.gemini_model.setVisible(is_gemini)
        self._gemini_voice_label.setVisible(is_gemini)
        self.gemini_voice.setVisible(is_gemini)
        # OpenAI fields
        self._openai_key_label.setVisible(not is_gemini)
        self.openai_api_key.setVisible(not is_gemini)
        self._openai_model_label.setVisible(not is_gemini)
        self.openai_model.setVisible(not is_gemini)
        self._openai_voice_label.setVisible(not is_gemini)
        self.openai_voice.setVisible(not is_gemini)


STT_LANGUAGES = [
    ("Auto-detect", ""),
    ("English", "en"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("German", "de"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Japanese", "ja"),
    ("Chinese", "zh"),
    ("Korean", "ko"),
    ("Russian", "ru"),
    ("Arabic", "ar"),
    ("Hindi", "hi"),
]


class _DictationPage(QWidget):
    """Dictation settings: enable, hotkey, language."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Dictation")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Press a global hotkey to record speech and paste the "
            "transcription into the focused input field. Uses OpenAI "
            "Realtime for speech-to-text."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #8E8E93; background: transparent;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Enable
        self.enabled = QCheckBox("Enable dictation")
        self.enabled.setChecked(bool(settings.get("stt_enabled", True)))
        form.addRow("", self.enabled)

        # OpenAI API key (required for STT regardless of main provider)
        self.openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("Required for dictation STT")
        form.addRow("OpenAI Key", self.openai_api_key)

        # Hotkey
        self.hotkey = HotkeyButton()
        self.hotkey.set_value(settings.get("stt_hotkey", "<ctrl>+<shift>+h"))
        form.addRow("Hotkey", self.hotkey)

        # Language
        self.language = QComboBox()
        for label, _value in STT_LANGUAGES:
            self.language.addItem(label)
        current_lang = settings.get("stt_language", "")
        for i, (_, val) in enumerate(STT_LANGUAGES):
            if val == current_lang:
                self.language.setCurrentIndex(i)
                break
        form.addRow("Language", self.language)

        layout.addLayout(form)

        hint = QLabel("Click the button above, then press your desired key combination.")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11px; color: #636366; background: transparent;")
        layout.addWidget(hint)

        layout.addStretch()


MCP_TRANSPORTS = [
    ("Stdio", "stdio"),
    ("SSE", "sse"),
    ("Streamable HTTP", "streamable_http"),
]


class _MCPPage(QWidget):
    """MCP Servers configuration page."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._servers: list[dict] = []
        try:
            self._servers = json.loads(settings.get("mcp_servers", "[]"))
        except (json.JSONDecodeError, TypeError):
            self._servers = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("MCP Servers")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Configure Model Context Protocol servers to give the "
            "voice assistant access to external tools."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #8E8E93; background: transparent;")
        layout.addWidget(desc)

        # Server list
        self._server_list = QListWidget()
        self._server_list.setFixedHeight(90)
        c = colors()
        self._server_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
        )
        layout.addWidget(self._server_list)

        # Add / Remove buttons below the list
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
        layout.addLayout(btn_row)

        # Per-server config form
        self._form_container = QWidget()
        form = QFormLayout(self._form_container)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

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
        self._env_edit.setFixedHeight(48)
        form.addRow("Env", self._env_edit)

        layout.addWidget(self._form_container)
        self._form_container.setVisible(False)

        layout.addStretch()

        # Populate list
        for srv in self._servers:
            self._server_list.addItem(srv.get("name", "Unnamed"))

        # Connections
        self._server_list.currentRowChanged.connect(self._on_selection_changed)
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        self._name_edit.textChanged.connect(self._sync_to_model)
        self._command_edit.textChanged.connect(self._sync_to_model)
        self._args_edit.textChanged.connect(self._sync_to_model)
        self._url_edit.textChanged.connect(self._sync_to_model)
        self._env_edit.textChanged.connect(self._sync_to_model)

    def _add_server(self) -> None:
        srv = {
            "name": "New Server",
            "transport": "stdio",
            "command": "",
            "args": "",
            "url": "",
            "env": "",
        }
        self._servers.append(srv)
        self._server_list.addItem(srv["name"])
        self._server_list.setCurrentRow(len(self._servers) - 1)

    def _remove_server(self) -> None:
        row = self._server_list.currentRow()
        if row < 0:
            return
        self._servers.pop(row)
        self._server_list.takeItem(row)

    def _on_selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._servers):
            self._form_container.setVisible(False)
            return
        self._form_container.setVisible(True)
        srv = self._servers[row]

        # Block signals while populating to avoid feedback loop
        for w in (
            self._name_edit,
            self._command_edit,
            self._args_edit,
            self._url_edit,
            self._env_edit,
            self._transport_combo,
        ):
            w.blockSignals(True)

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

        for w in (
            self._name_edit,
            self._command_edit,
            self._args_edit,
            self._url_edit,
            self._env_edit,
            self._transport_combo,
        ):
            w.blockSignals(False)

        self._update_field_visibility(transport)

    def _on_transport_changed(self, _index: int) -> None:
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

    def _sync_to_model(self) -> None:
        row = self._server_list.currentRow()
        if row < 0 or row >= len(self._servers):
            return
        srv = self._servers[row]
        srv["name"] = self._name_edit.text().strip()
        srv["transport"] = MCP_TRANSPORTS[self._transport_combo.currentIndex()][1]
        srv["command"] = self._command_edit.text().strip()
        srv["args"] = self._args_edit.text().strip()
        srv["url"] = self._url_edit.text().strip()
        srv["env"] = self._env_edit.toPlainText()
        # Update list item text
        item = self._server_list.item(row)
        if item:
            item.setText(srv["name"] or "Unnamed")

    def get_servers_json(self) -> str:
        """Return server configs as a JSON string for saving."""
        return json.dumps(self._servers)


class _AboutPage(QWidget):
    """About page with license and credits."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        c = colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        title = QLabel("About")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # App name + version
        app_name = QLabel("RoomKit UI")
        app_name.setStyleSheet("font-size: 24px; font-weight: 700; background: transparent;")
        layout.addWidget(app_name)

        desc = QLabel("A desktop voice assistant powered by RoomKit.")
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        url = "https://www.roomkit.live"
        color = c["ACCENT_BLUE"]
        website = QLabel(f'<a href="{url}" style="color: {color};">www.roomkit.live</a>')
        website.setOpenExternalLinks(True)
        website.setStyleSheet("font-size: 13px; background: transparent;")
        layout.addWidget(website)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        layout.addWidget(sep)

        # License
        license_title = QLabel("License")
        license_title.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(license_title)

        license_text = QLabel(
            "MIT License\n\n"
            "Copyright (c) 2025 Sylvain Boily\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining "
            "a copy of this software and associated documentation files, to deal in "
            "the Software without restriction, including without limitation the rights "
            "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
            "copies of the Software, and to permit persons to whom the Software is "
            "furnished to do so, subject to the following conditions:\n\n"
            "The above copyright notice and this permission notice shall be included "
            "in all copies or substantial portions of the Software.\n\n"
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS '
            "OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, "
            "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT."
        )
        license_text.setWordWrap(True)
        license_text.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" line-height: 1.5; background: transparent;"
            f" padding: 12px; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        layout.addWidget(license_text)

        layout.addStretch()


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class SettingsPanel(QDialog):
    """Modal settings dialog with vertical tab navigation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(740, 540)
        self.setModal(True)

        settings = load_settings()
        c = colors()

        # ── Sidebar ──
        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(150)
        self._sidebar.setFrameShape(QListWidget.NoFrame)
        self._sidebar.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{"
            f"  padding: 10px 14px; border-radius: 8px; color: {c['TEXT_SECONDARY']};"
            f"  font-size: 13px; font-weight: 500;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background-color: {c['BG_TERTIARY']}; color: {c['TEXT_PRIMARY']};"
            f"}}"
            f"QListWidget::item:hover:!selected {{"
            f"  background-color: rgba(142, 142, 147, 0.12);"
            f"}}"
        )

        for label in ("General", "AI Provider", "Dictation", "MCP Servers", "About"):
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 38)))
            self._sidebar.addItem(item)

        # ── Pages ──
        self._stack = QStackedWidget()
        self._general = _GeneralPage(settings)
        self._ai = _AIPage(settings)
        self._dictation = _DictationPage(settings)
        self._mcp = _MCPPage(settings)
        self._about = _AboutPage()
        for page in (self._general, self._ai, self._dictation, self._mcp, self._about):
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            self._stack.addWidget(scroll)

        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._sidebar.setCurrentRow(0)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {c['ACCENT_BLUE']}; color: white;"
            f" font-weight: 600; padding: 8px 24px; border-radius: 10px; }}"
            f"QPushButton:hover {{ background-color: #0070E0; }}"
        )
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)

        # ── Layout ──
        content = QHBoxLayout()
        content.setSpacing(0)
        content.addWidget(self._sidebar)

        # Vertical separator
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        content.addWidget(sep)

        right = QVBoxLayout()
        right.setContentsMargins(20, 16, 20, 16)
        right.setSpacing(12)
        right.addWidget(self._stack, 1)
        right.addLayout(btn_row)
        content.addLayout(right, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(content)

    def _save(self) -> None:
        from room_ui.theme import get_stylesheet

        settings = {
            "theme": THEMES[self._general.theme_combo.currentIndex()][1],
            "provider": PROVIDERS[self._ai.provider.currentIndex()][1],
            "api_key": self._ai.gemini_api_key.text().strip(),
            "openai_api_key": (
                self._ai.openai_api_key.text().strip()
                or self._dictation.openai_api_key.text().strip()
            ),
            "model": self._ai.gemini_model.currentText().strip(),
            "openai_model": self._ai.openai_model.currentText().strip(),
            "voice": self._ai.gemini_voice.currentText(),
            "openai_voice": self._ai.openai_voice.currentText(),
            "system_prompt": self._ai.prompt.toPlainText().strip(),
            "aec_mode": AEC_MODES[self._ai.aec.currentIndex()][1],
            "denoise": self._ai.denoise.isChecked(),
            "input_device": self._general.input_combo.currentData(),
            "output_device": self._general.output_combo.currentData(),
            "stt_enabled": self._dictation.enabled.isChecked(),
            "stt_hotkey": self._dictation.hotkey.value(),
            "stt_language": STT_LANGUAGES[self._dictation.language.currentIndex()][1],
            "mcp_servers": self._mcp.get_servers_json(),
        }
        save_settings(settings)

        # Apply the new theme stylesheet immediately
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(settings["theme"]))

        self.accept()
