"""Settings dialog with vertical tab navigation."""

from __future__ import annotations

import json
from dataclasses import dataclass

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
    QProgressBar,
    QPushButton,
    QRadioButton,
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

DENOISE_MODES = [
    ("None", "none"),
    ("RNNoise (Linux/macOS)", "rnnoise"),
    ("GTCRN (cross-platform)", "gtcrn"),
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

        # Audio processing
        proc_section = QLabel("Audio Processing")
        proc_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(proc_section)

        proc_form = QFormLayout()
        proc_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        proc_form.setSpacing(10)
        proc_form.setLabelAlignment(Qt.AlignRight)

        # AEC
        self.aec = QComboBox()
        for label, _value in AEC_MODES:
            self.aec.addItem(label)
        current_aec = settings.get("aec_mode", "webrtc")
        for i, (_, val) in enumerate(AEC_MODES):
            if val == current_aec:
                self.aec.setCurrentIndex(i)
                break
        proc_form.addRow("Echo Cancel", self.aec)

        # Denoise
        self.denoise = QComboBox()
        for label, _value in DENOISE_MODES:
            self.denoise.addItem(label)
        current_denoise = settings.get("denoise", "none")
        for i, (_, val) in enumerate(DENOISE_MODES):
            if val == current_denoise:
                self.denoise.setCurrentIndex(i)
                break
        proc_form.addRow("Denoise", self.denoise)

        # Inference device
        from room_ui.model_manager import detect_providers

        self._inference_providers = detect_providers()
        self.inference_device = QComboBox()
        for label, _value in self._inference_providers:
            self.inference_device.addItem(label)
        current_device = settings.get("inference_device", "cpu")
        for i, (_, val) in enumerate(self._inference_providers):
            if val == current_device:
                self.inference_device.setCurrentIndex(i)
                break
        proc_form.addRow("Inference Device", self.inference_device)

        self._device_hint = QLabel()
        self._device_hint.setWordWrap(True)
        self._device_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        proc_form.addRow("", self._device_hint)
        self.inference_device.currentIndexChanged.connect(self._on_device_changed)
        self._on_device_changed(self.inference_device.currentIndex())

        layout.addLayout(proc_form)
        layout.addStretch()

    def _on_device_changed(self, index: int) -> None:
        val = self._inference_providers[index][1]
        if val == "cuda":
            self._device_hint.setText(
                "Affects local STT models only. Requires the sherpa-onnx CUDA wheel "
                "and cuDNN 9: uv pip install sherpa-onnx==1.12.23+cuda12.cudnn9 "
                "-f https://k2-fsa.github.io/sherpa/onnx/cuda.html"
            )
            self._device_hint.show()
        elif val == "coreml":
            self._device_hint.setText("Affects local STT models only.")
            self._device_hint.show()
        else:
            self._device_hint.hide()


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

        layout.addLayout(form)

        # System prompt
        c = colors()
        section = QLabel("System Prompt")
        section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
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


STT_PROVIDERS = [
    ("OpenAI", "openai"),
    ("Local", "local"),
]


class _ModelRow(QWidget):
    """A single row in the local model list: radio + name + type + size + action + progress."""

    def __init__(self, model, c: dict, show_radio: bool = True, parent=None) -> None:
        super().__init__(parent)
        from room_ui.model_manager import is_model_downloaded

        self.model = model
        self._c = c

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Top line: radio + info + buttons
        top = QHBoxLayout()
        top.setSpacing(8)

        self.radio = QRadioButton()
        if not show_radio:
            self.radio.hide()
        top.addWidget(self.radio)

        name_label = QLabel(model.name)
        name_label.setStyleSheet(
            "font-size: 13px; font-weight: 500; background: transparent;"
        )
        top.addWidget(name_label)

        type_label = QLabel(model.type)
        type_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" background: {c['BG_TERTIARY']}; border-radius: 4px;"
            f" padding: 1px 6px;"
        )
        top.addWidget(type_label)

        size_label = QLabel(model.size)
        size_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        top.addWidget(size_label)

        top.addStretch()

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {c['ACCENT_GREEN']}; background: transparent;"
        )
        top.addWidget(self.status_label)

        self.action_btn = QPushButton()
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setFixedHeight(26)
        top.addWidget(self.action_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedHeight(26)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
            f" background: transparent; border: 1px solid {c['ACCENT_RED']};"
            f" color: {c['ACCENT_RED']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {c['ACCENT_RED']};"
            f" color: white; }}"
        )
        top.addWidget(self.delete_btn)

        outer.addLayout(top)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {c['BG_TERTIARY']};"
            f" border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {c['ACCENT_BLUE']};"
            f" border-radius: 3px; }}"
        )
        self.progress_bar.hide()
        outer.addWidget(self.progress_bar)

        self._refresh_state(is_model_downloaded(model.id))

    def _refresh_state(self, downloaded: bool) -> None:
        c = self._c
        self.progress_bar.hide()
        if downloaded:
            self.status_label.setText("\u2713 Ready")
            self.status_label.setStyleSheet(
                f"font-size: 12px; color: {c['ACCENT_GREEN']};"
                f" background: transparent;"
            )
            self.action_btn.hide()
            self.delete_btn.show()
        else:
            self.status_label.setText("")
            self.action_btn.setText("Download")
            self.action_btn.setStyleSheet(
                f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
                f" background: {c['ACCENT_BLUE']}; color: white;"
                f" border: none; border-radius: 4px; }}"
                f"QPushButton:hover {{ opacity: 0.8; }}"
            )
            self.action_btn.setEnabled(True)
            self.action_btn.show()
            self.delete_btn.hide()

    def set_downloading(self, pct: int) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.show()
        self.status_label.setText(f"{pct}%")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']};"
            f" background: transparent;"
        )

    def set_resolving(self) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.show()
        self.status_label.setText("Resolving…")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']};"
            f" background: transparent;"
        )

    def set_downloaded(self) -> None:
        self.progress_bar.setRange(0, 100)  # restore determinate mode
        self._refresh_state(True)

    def set_not_downloaded(self) -> None:
        self.progress_bar.setRange(0, 100)
        self._refresh_state(False)

    def set_error(self) -> None:
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 100)
        self.action_btn.setText("Retry")
        self.action_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
            f" background: {self._c['ACCENT_BLUE']}; color: white;"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ opacity: 0.8; }}"
        )
        self.action_btn.setEnabled(True)
        self.action_btn.show()
        self.status_label.setText("Error")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['ACCENT_RED']};"
            f" background: transparent;"
        )


class _ModelsPage(QWidget):
    """AI Models catalog: browse, download, and delete local STT models."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        c = colors()

        title = QLabel("AI Models")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Download local speech-to-text models for offline dictation. "
            "Downloaded models will appear in the Dictation settings."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        model_section = QLabel("Available Models")
        model_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(model_section)

        model_frame = QWidget()
        model_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        frame_layout = QVBoxLayout(model_frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        frame_layout.setSpacing(0)

        from room_ui.model_manager import STT_MODELS

        self._model_rows: list[_ModelRow] = []
        for model in STT_MODELS:
            row = _ModelRow(model, c, show_radio=False)
            row.action_btn.clicked.connect(
                lambda _checked=False, m=model.id: self._download_model(m)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, m=model.id: self._delete_model(m)
            )
            frame_layout.addWidget(row)
            self._model_rows.append(row)

        layout.addWidget(model_frame)

        # -- Denoiser Models section -----------------------------------------
        denoise_section = QLabel("Denoiser Models")
        denoise_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(denoise_section)

        from room_ui.model_manager import (
            GTCRN_MODEL_ID,
            GTCRN_SIZE,
            is_gtcrn_downloaded,
        )

        @dataclass(frozen=True)
        class _DenoiserModel:
            id: str
            name: str
            type: str
            size: str

        gtcrn_info = _DenoiserModel(
            id=GTCRN_MODEL_ID, name="GTCRN", type="denoiser", size=GTCRN_SIZE,
        )

        denoise_frame = QWidget()
        denoise_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        denoise_frame_layout = QVBoxLayout(denoise_frame)
        denoise_frame_layout.setContentsMargins(4, 4, 4, 4)
        denoise_frame_layout.setSpacing(0)

        self._gtcrn_row = _ModelRow(gtcrn_info, c, show_radio=False)
        # Override the initial state check since _ModelRow uses is_model_downloaded
        self._gtcrn_row._refresh_state(is_gtcrn_downloaded())
        self._gtcrn_row.action_btn.clicked.connect(self._download_gtcrn)
        self._gtcrn_row.delete_btn.clicked.connect(self._delete_gtcrn)
        denoise_frame_layout.addWidget(self._gtcrn_row)

        layout.addWidget(denoise_frame)
        layout.addStretch()

    def _find_row(self, model_id: str) -> _ModelRow | None:
        for row in self._model_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from room_ui.model_manager import download_model

        row = self._find_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("Model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_model(self, model_id: str) -> None:
        from room_ui.model_manager import delete_model

        delete_model(model_id)
        row = self._find_row(model_id)
        if row is not None:
            row.set_not_downloaded()

    def _download_gtcrn(self) -> None:
        import asyncio
        import logging

        from room_ui.model_manager import download_gtcrn

        row = self._gtcrn_row
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_gtcrn(_progress)
                row.set_downloaded()
            except Exception:
                logging.exception("GTCRN download failed")
                row.set_error()

        loop.create_task(_run())

    def _delete_gtcrn(self) -> None:
        from room_ui.model_manager import delete_gtcrn

        delete_gtcrn()
        self._gtcrn_row.set_not_downloaded()


class _DictationPage(QWidget):
    """Dictation settings: enable, STT provider, hotkey, language."""

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
            "transcription into the focused input field."
        )
        desc.setWordWrap(True)
        c = colors()
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Enable
        self.enabled = QCheckBox("Enable dictation")
        self.enabled.setChecked(bool(settings.get("stt_enabled", True)))
        form.addRow("", self.enabled)

        # STT Provider
        self.stt_provider = QComboBox()
        for label, _value in STT_PROVIDERS:
            self.stt_provider.addItem(label)
        current_stt = settings.get("stt_provider", "openai")
        for i, (_, val) in enumerate(STT_PROVIDERS):
            if val == current_stt:
                self.stt_provider.setCurrentIndex(i)
                break
        form.addRow("STT Provider", self.stt_provider)

        # OpenAI API key (shown only for OpenAI provider)
        self.openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("Required for dictation STT")
        self._openai_key_label = QLabel("OpenAI Key")
        form.addRow(self._openai_key_label, self.openai_api_key)

        # Local model combo (shown only for Local provider)
        self._model_combo = QComboBox()
        self._model_label = QLabel("Model")
        form.addRow(self._model_label, self._model_combo)

        self._no_models_hint = QLabel(
            "No models downloaded \u2014 go to the AI Models tab to download one."
        )
        self._no_models_hint.setWordWrap(True)
        self._no_models_hint.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        form.addRow("", self._no_models_hint)

        self._saved_model = settings.get("stt_model", "")

        # Hotkey / Language
        self.hotkey = HotkeyButton()
        self.hotkey.set_value(settings.get("stt_hotkey", "<ctrl>+<shift>+h"))
        form.addRow("Hotkey", self.hotkey)

        self.language = QComboBox()
        for label, _value in STT_LANGUAGES:
            self.language.addItem(label)
        current_lang = settings.get("stt_language", "")
        for i, (_, val) in enumerate(STT_LANGUAGES):
            if val == current_lang:
                self.language.setCurrentIndex(i)
                break
        form.addRow("Language", self.language)

        # Translate to English (Whisper only)
        self.translate = QCheckBox("Translate to English (Whisper only)")
        self.translate.setChecked(bool(settings.get("stt_translate", False)))
        form.addRow("", self.translate)

        layout.addLayout(form)

        hint = QLabel("Click the button above, then press your desired key combination.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(hint)

        layout.addStretch()

        # Populate model combo and wire provider switch
        self.refresh_model_combo()
        self.stt_provider.currentIndexChanged.connect(self._on_stt_provider_changed)
        self._model_combo.currentIndexChanged.connect(self._update_translate_visibility)
        self._on_stt_provider_changed(self.stt_provider.currentIndex())

    def _on_stt_provider_changed(self, index: int) -> None:
        is_openai = STT_PROVIDERS[index][1] == "openai"
        self._openai_key_label.setVisible(is_openai)
        self.openai_api_key.setVisible(is_openai)
        self._model_label.setVisible(not is_openai)
        self._model_combo.setVisible(not is_openai)
        self._no_models_hint.setVisible(not is_openai and self._model_combo.count() == 0)
        self._update_translate_visibility()

    def _update_translate_visibility(self) -> None:
        is_local = STT_PROVIDERS[self.stt_provider.currentIndex()][1] == "local"
        model_id = self._model_combo.currentData() or ""
        is_whisper = model_id.startswith("whisper")
        self.translate.setVisible(is_local and is_whisper)

    def selected_model_id(self) -> str:
        """Return the model ID selected in the combo box."""
        return self._model_combo.currentData() or ""

    def refresh_model_combo(self) -> None:
        """Rebuild the model combo with currently downloaded models."""
        from room_ui.model_manager import STT_MODELS, is_model_downloaded

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for m in STT_MODELS:
            if is_model_downloaded(m.id):
                self._model_combo.addItem(f"{m.name} ({m.type})", m.id)

        # Restore previous selection
        target = self._saved_model or self._model_combo.itemData(0)
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == target:
                self._model_combo.setCurrentIndex(i)
                break
        self._model_combo.blockSignals(False)

        has_models = self._model_combo.count() > 0
        is_local = STT_PROVIDERS[self.stt_provider.currentIndex()][1] == "local"
        self._no_models_hint.setVisible(is_local and not has_models)


MCP_TRANSPORTS = [
    ("Stdio", "stdio"),
    ("SSE", "sse"),
    ("Streamable HTTP", "streamable_http"),
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
        self._args_edit.setPlaceholderText(
            "e.g. -y @modelcontextprotocol/server-filesystem /home"
        )
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
        self._enabled_check.toggled.connect(self._sync_to_model)
        self._name_edit.textChanged.connect(self._sync_to_model)
        self._command_edit.textChanged.connect(self._sync_to_model)
        self._args_edit.textChanged.connect(self._sync_to_model)
        self._url_edit.textChanged.connect(self._sync_to_model)
        self._env_edit.textChanged.connect(self._sync_to_model)

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

        for w in (
            self._enabled_check,
            self._name_edit,
            self._command_edit,
            self._args_edit,
            self._url_edit,
            self._env_edit,
            self._transport_combo,
        ):
            w.blockSignals(False)

        self._update_field_visibility(transport)
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

    def _update_field_visibility(self, transport: str) -> None:
        is_stdio = transport == "stdio"
        self._command_label.setVisible(is_stdio)
        self._command_edit.setVisible(is_stdio)
        self._args_label.setVisible(is_stdio)
        self._args_edit.setVisible(is_stdio)
        self._url_label.setVisible(not is_stdio)
        self._url_edit.setVisible(not is_stdio)

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
        # Update list item text
        item = self._server_list.item(row)
        if item:
            item.setText(self._display_name(srv))
        # Update edit title
        self._edit_title.setText(srv["name"] or "New Server")

    @staticmethod
    def _display_name(srv: dict) -> str:
        name = srv.get("name") or "Unnamed"
        if not srv.get("enabled", True):
            return f"{name} (disabled)"
        return name

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
            "Copyright (c) 2026 Sylvain Boily\n\n"
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
        self.setFixedSize(740, 600)
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

        for label in ("General", "AI Provider", "Dictation", "AI Models", "MCP Servers", "About"):
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 38)))
            self._sidebar.addItem(item)

        # ── Pages ──
        self._stack = QStackedWidget()
        self._general = _GeneralPage(settings)
        self._ai = _AIPage(settings)
        self._dictation = _DictationPage(settings)
        self._models = _ModelsPage(settings)
        self._mcp = _MCPPage(settings)
        self._about = _AboutPage()
        pages = (self._general, self._ai, self._dictation, self._models, self._mcp, self._about)
        for page in pages:
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            self._stack.addWidget(scroll)

        self._sidebar.currentRowChanged.connect(self._on_tab_changed)
        self._sidebar.setCurrentRow(0)

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
        content.addLayout(right, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(content)

    _DICTATION_TAB = 2

    def _on_tab_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == self._DICTATION_TAB:
            self._dictation.refresh_model_combo()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save()
        super().closeEvent(event)

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
            "aec_mode": AEC_MODES[self._general.aec.currentIndex()][1],
            "denoise": DENOISE_MODES[self._general.denoise.currentIndex()][1],
            "inference_device": self._general._inference_providers[
                self._general.inference_device.currentIndex()
            ][1],
            "input_device": self._general.input_combo.currentData(),
            "output_device": self._general.output_combo.currentData(),
            "stt_enabled": self._dictation.enabled.isChecked(),
            "stt_hotkey": self._dictation.hotkey.value(),
            "stt_provider": STT_PROVIDERS[self._dictation.stt_provider.currentIndex()][1],
            "stt_model": self._dictation.selected_model_id(),
            "stt_language": STT_LANGUAGES[self._dictation.language.currentIndex()][1],
            "stt_translate": self._dictation.translate.isChecked(),
            "mcp_servers": self._mcp.get_servers_json(),
        }
        save_settings(settings)

        # Apply the new theme stylesheet immediately
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(settings["theme"]))
