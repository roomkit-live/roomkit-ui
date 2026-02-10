"""Settings dialog with vertical tab navigation."""

from __future__ import annotations

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


class _GeneralPage(QWidget):
    """General settings: audio device selection."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("General")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # Audio devices
        section = QLabel("Audio Devices")
        section.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #8E8E93;"
            " text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(section)

        form = QFormLayout()
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


class _AboutPage(QWidget):
    """About page with license and credits."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        title = QLabel("About")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # App name + version
        app_name = QLabel("RoomKit UI")
        app_name.setStyleSheet(
            "font-size: 24px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(app_name)

        desc = QLabel("A desktop voice assistant powered by RoomKit.")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #8E8E93; background: transparent;")
        layout.addWidget(desc)

        website = QLabel('<a href="https://www.roomkit.live" style="color: #0A84FF;">www.roomkit.live</a>')
        website.setOpenExternalLinks(True)
        website.setStyleSheet("font-size: 13px; background: transparent;")
        layout.addWidget(website)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #2C2C2E;")
        layout.addWidget(sep)

        # License
        license_title = QLabel("License")
        license_title.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #8E8E93;"
            " text-transform: uppercase; letter-spacing: 1px; background: transparent;"
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
            "font-size: 12px; color: #AEAEB2; line-height: 1.5; background: transparent;"
            " padding: 12px; border: 1px solid #2C2C2E; border-radius: 8px;"
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
        self.setFixedSize(640, 480)
        self.setModal(True)

        settings = load_settings()

        # ── Sidebar ──
        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(150)
        self._sidebar.setFrameShape(QListWidget.NoFrame)
        self._sidebar.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item {"
            "  padding: 10px 14px; border-radius: 8px; color: #8E8E93;"
            "  font-size: 13px; font-weight: 500;"
            "}"
            "QListWidget::item:selected {"
            "  background-color: #2C2C2E; color: #FFFFFF;"
            "}"
            "QListWidget::item:hover:!selected {"
            "  background-color: rgba(44, 44, 46, 0.5);"
            "}"
        )

        for label in ("General", "AI Provider", "About"):
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 38)))
            self._sidebar.addItem(item)

        # ── Pages ──
        self._stack = QStackedWidget()
        self._general = _GeneralPage(settings)
        self._ai = _AIPage(settings)
        self._about = _AboutPage()
        for page in (self._general, self._ai, self._about):
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
            "QPushButton { background-color: #0A84FF; color: white;"
            " font-weight: 600; padding: 8px 24px; border-radius: 10px; }"
            "QPushButton:hover { background-color: #0070E0; }"
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
        sep.setStyleSheet("background-color: #2C2C2E;")
        content.addWidget(sep)

        right = QVBoxLayout()
        right.setContentsMargins(20, 16, 20, 16)
        right.addWidget(self._stack, 1)
        right.addLayout(btn_row)
        content.addLayout(right, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(content)

    def _save(self) -> None:
        settings = {
            "provider": PROVIDERS[self._ai.provider.currentIndex()][1],
            "api_key": self._ai.gemini_api_key.text().strip(),
            "openai_api_key": self._ai.openai_api_key.text().strip(),
            "model": self._ai.gemini_model.currentText().strip(),
            "openai_model": self._ai.openai_model.currentText().strip(),
            "voice": self._ai.gemini_voice.currentText(),
            "openai_voice": self._ai.openai_voice.currentText(),
            "system_prompt": self._ai.prompt.toPlainText().strip(),
            "aec_mode": AEC_MODES[self._ai.aec.currentIndex()][1],
            "denoise": self._ai.denoise.isChecked(),
            "input_device": self._general.input_combo.currentData(),
            "output_device": self._general.output_combo.currentData(),
        }
        save_settings(settings)
        self.accept()
