"""Settings dialog with vertical tab navigation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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

from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.theme import colors
from roomkit_ui.widgets.hotkey_button import HotkeyButton

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

CONVERSATION_MODES = [
    ("Speech-to-Speech (Realtime)", "realtime"),
    ("Voice Channel (STT \u2192 LLM \u2192 TTS)", "voice_channel"),
]

VC_LLM_PROVIDERS = [
    ("Anthropic", "anthropic"),
    ("OpenAI", "openai"),
    ("Google Gemini", "gemini"),
    ("Local (vLLM / Ollama)", "local"),
]

VC_ANTHROPIC_MODELS = ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]
VC_OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini"]
VC_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash"]

VC_TTS_PROVIDERS = [
    ("Piper (sherpa-onnx)", "piper"),
    ("Qwen3-TTS (voice clone)", "qwen3"),
    ("NeuTTS (voice clone)", "neutts"),
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

        # Assistant hotkey
        hotkey_section = QLabel("Assistant Hotkey")
        hotkey_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(hotkey_section)

        hotkey_form = QFormLayout()
        hotkey_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        hotkey_form.setSpacing(10)
        hotkey_form.setLabelAlignment(Qt.AlignRight)

        self.assistant_hotkey_enabled = QCheckBox("Enable global hotkey to start/stop session")
        self.assistant_hotkey_enabled.setChecked(
            bool(settings.get("assistant_hotkey_enabled", True))
        )
        hotkey_form.addRow("", self.assistant_hotkey_enabled)

        self.assistant_hotkey = HotkeyButton()
        self.assistant_hotkey.set_value(settings.get("assistant_hotkey", "<ctrl>+<shift>+a"))
        hotkey_form.addRow("Hotkey", self.assistant_hotkey)

        hotkey_hint = QLabel("Press the button, then press your desired key combination.")
        hotkey_hint.setWordWrap(True)
        hotkey_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        hotkey_form.addRow("", hotkey_hint)

        layout.addLayout(hotkey_form)

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
        from roomkit_ui.model_manager import detect_providers

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
    """AI settings: conversation mode, provider, API key, model, voice, prompt."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        c = colors()

        title = QLabel("AI Provider")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # -- Conversation mode selector --
        mode_form = QFormLayout()
        mode_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        mode_form.setSpacing(10)
        mode_form.setLabelAlignment(Qt.AlignRight)

        self.mode_combo = QComboBox()
        for label, _value in CONVERSATION_MODES:
            self.mode_combo.addItem(label)
        current_mode = settings.get("conversation_mode", "realtime")
        for i, (_, val) in enumerate(CONVERSATION_MODES):
            if val == current_mode:
                self.mode_combo.setCurrentIndex(i)
                break
        mode_form.addRow("Mode", self.mode_combo)
        layout.addLayout(mode_form)

        # ── Speech-to-Speech (Realtime) section ──
        self._realtime_section = QWidget()
        rt_layout = QVBoxLayout(self._realtime_section)
        rt_layout.setContentsMargins(0, 0, 0, 0)
        rt_layout.setSpacing(10)

        rt_section_label = QLabel("Realtime Provider")
        rt_section_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        rt_layout.addWidget(rt_section_label)

        rt_form = QFormLayout()
        rt_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        rt_form.setSpacing(10)
        rt_form.setLabelAlignment(Qt.AlignRight)

        # Provider selector
        self.provider = QComboBox()
        for label, _value in PROVIDERS:
            self.provider.addItem(label)
        current_provider = settings.get("provider", "gemini")
        for i, (_, val) in enumerate(PROVIDERS):
            if val == current_provider:
                self.provider.setCurrentIndex(i)
                break
        rt_form.addRow("Provider", self.provider)

        # API keys (one per provider, shown/hidden)
        self.gemini_api_key = QLineEdit(settings.get("api_key", ""))
        self.gemini_api_key.setEchoMode(QLineEdit.Password)
        self.gemini_api_key.setPlaceholderText("Enter your Google API key")
        self._gemini_key_label = QLabel("API Key")
        rt_form.addRow(self._gemini_key_label, self.gemini_api_key)

        self.openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("Enter your OpenAI API key")
        self._openai_key_label = QLabel("API Key")
        rt_form.addRow(self._openai_key_label, self.openai_api_key)

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
        rt_form.addRow(self._gemini_model_label, self.gemini_model)

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
        rt_form.addRow(self._openai_model_label, self.openai_model)

        # Voice (Gemini)
        self.gemini_voice = QComboBox()
        self.gemini_voice.addItems(GEMINI_VOICES)
        current_voice = settings.get("voice", "Aoede")
        vidx = self.gemini_voice.findText(current_voice)
        if vidx >= 0:
            self.gemini_voice.setCurrentIndex(vidx)
        self._gemini_voice_label = QLabel("Voice")
        rt_form.addRow(self._gemini_voice_label, self.gemini_voice)

        # Voice (OpenAI)
        self.openai_voice = QComboBox()
        self.openai_voice.addItems(OPENAI_VOICES)
        current_oai_voice = settings.get("openai_voice", "alloy")
        ovidx = self.openai_voice.findText(current_oai_voice)
        if ovidx >= 0:
            self.openai_voice.setCurrentIndex(ovidx)
        self._openai_voice_label = QLabel("Voice")
        rt_form.addRow(self._openai_voice_label, self.openai_voice)

        rt_layout.addLayout(rt_form)
        layout.addWidget(self._realtime_section)

        # ── Voice Channel (STT → LLM → TTS) section ──
        self._vc_section = QWidget()
        vc_layout = QVBoxLayout(self._vc_section)
        vc_layout.setContentsMargins(0, 0, 0, 0)
        vc_layout.setSpacing(10)

        vc_section_label = QLabel("Voice Channel")
        vc_section_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        vc_layout.addWidget(vc_section_label)

        vc_form = QFormLayout()
        vc_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        vc_form.setSpacing(10)
        vc_form.setLabelAlignment(Qt.AlignRight)

        # LLM Provider
        self.vc_provider = QComboBox()
        for label, _value in VC_LLM_PROVIDERS:
            self.vc_provider.addItem(label)
        current_vc_provider = settings.get("vc_llm_provider", "anthropic")
        for i, (_, val) in enumerate(VC_LLM_PROVIDERS):
            if val == current_vc_provider:
                self.vc_provider.setCurrentIndex(i)
                break
        vc_form.addRow("LLM Provider", self.vc_provider)

        # Anthropic API key
        self.anthropic_api_key = QLineEdit(settings.get("anthropic_api_key", ""))
        self.anthropic_api_key.setEchoMode(QLineEdit.Password)
        self.anthropic_api_key.setPlaceholderText("Enter your Anthropic API key")
        self._anthropic_key_label = QLabel("API Key")
        vc_form.addRow(self._anthropic_key_label, self.anthropic_api_key)

        # OpenAI key for VC (reuse field, shown when vc_provider=openai)
        self.vc_openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.vc_openai_api_key.setEchoMode(QLineEdit.Password)
        self.vc_openai_api_key.setPlaceholderText("Enter your OpenAI API key")
        self._vc_openai_key_label = QLabel("API Key")
        vc_form.addRow(self._vc_openai_key_label, self.vc_openai_api_key)

        # Gemini key for VC (reuse field, shown when vc_provider=gemini)
        self.vc_gemini_api_key = QLineEdit(settings.get("api_key", ""))
        self.vc_gemini_api_key.setEchoMode(QLineEdit.Password)
        self.vc_gemini_api_key.setPlaceholderText("Enter your Google API key")
        self._vc_gemini_key_label = QLabel("API Key")
        vc_form.addRow(self._vc_gemini_key_label, self.vc_gemini_api_key)

        # Model combos (one per provider, shown/hidden)
        self.vc_anthropic_model = QComboBox()
        self.vc_anthropic_model.setEditable(True)
        self.vc_anthropic_model.addItems(VC_ANTHROPIC_MODELS)
        cur = settings.get("vc_anthropic_model", VC_ANTHROPIC_MODELS[0])
        aidx = self.vc_anthropic_model.findText(cur)
        if aidx >= 0:
            self.vc_anthropic_model.setCurrentIndex(aidx)
        else:
            self.vc_anthropic_model.setCurrentText(cur)
        self._vc_anthropic_model_label = QLabel("Model")
        vc_form.addRow(self._vc_anthropic_model_label, self.vc_anthropic_model)

        self.vc_openai_model = QComboBox()
        self.vc_openai_model.setEditable(True)
        self.vc_openai_model.addItems(VC_OPENAI_MODELS)
        cur = settings.get("vc_openai_model", VC_OPENAI_MODELS[0])
        oidx2 = self.vc_openai_model.findText(cur)
        if oidx2 >= 0:
            self.vc_openai_model.setCurrentIndex(oidx2)
        else:
            self.vc_openai_model.setCurrentText(cur)
        self._vc_openai_model_label = QLabel("Model")
        vc_form.addRow(self._vc_openai_model_label, self.vc_openai_model)

        self.vc_gemini_model = QComboBox()
        self.vc_gemini_model.setEditable(True)
        self.vc_gemini_model.addItems(VC_GEMINI_MODELS)
        cur = settings.get("vc_gemini_model", VC_GEMINI_MODELS[0])
        gidx = self.vc_gemini_model.findText(cur)
        if gidx >= 0:
            self.vc_gemini_model.setCurrentIndex(gidx)
        else:
            self.vc_gemini_model.setCurrentText(cur)
        self._vc_gemini_model_label = QLabel("Model")
        vc_form.addRow(self._vc_gemini_model_label, self.vc_gemini_model)

        # Local (vLLM / Ollama) fields
        self.vc_local_base_url = QLineEdit(settings.get("vc_local_base_url", ""))
        self.vc_local_base_url.setPlaceholderText("http://localhost:11434/v1")
        self._vc_local_base_url_label = QLabel("Base URL")
        vc_form.addRow(self._vc_local_base_url_label, self.vc_local_base_url)

        self.vc_local_model = QLineEdit(settings.get("vc_local_model", ""))
        self.vc_local_model.setPlaceholderText("e.g. qwen2.5:7b")
        self._vc_local_model_label = QLabel("Model")
        vc_form.addRow(self._vc_local_model_label, self.vc_local_model)

        self.vc_local_api_key = QLineEdit(settings.get("vc_local_api_key", ""))
        self.vc_local_api_key.setEchoMode(QLineEdit.Password)
        self.vc_local_api_key.setPlaceholderText("Optional")
        self._vc_local_api_key_label = QLabel("API Key")
        vc_form.addRow(self._vc_local_api_key_label, self.vc_local_api_key)

        self.vc_local_tools = QCheckBox("Model supports tool use (function calling)")
        self.vc_local_tools.setChecked(bool(settings.get("vc_local_tools", True)))
        self._vc_local_tools_label = QLabel("")
        vc_form.addRow(self._vc_local_tools_label, self.vc_local_tools)

        # STT model combo
        self.vc_stt_model = QComboBox()
        self._vc_stt_no_models = QLabel("No STT models downloaded \u2014 go to AI Models tab.")
        self._vc_stt_no_models.setWordWrap(True)
        self._vc_stt_no_models.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        vc_form.addRow("STT Model", self.vc_stt_model)
        vc_form.addRow("", self._vc_stt_no_models)
        self._vc_saved_stt = settings.get("vc_stt_model", "")

        # VAD model combo
        self.vc_vad_model = QComboBox()
        self._vc_vad_no_models = QLabel("No VAD models downloaded \u2014 go to AI Models tab.")
        self._vc_vad_no_models.setWordWrap(True)
        self._vc_vad_no_models.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        vc_form.addRow("VAD Model", self.vc_vad_model)
        vc_form.addRow("", self._vc_vad_no_models)
        self._vc_saved_vad = settings.get("vc_vad_model", "")

        # Interruption toggle
        self.vc_interruption = QCheckBox("Allow barge-in (interrupt TTS by speaking)")
        self.vc_interruption.setChecked(bool(settings.get("vc_interruption", False)))
        vc_form.addRow("", self.vc_interruption)

        # TTS provider selector
        self.vc_tts_provider = QComboBox()
        for label, _value in VC_TTS_PROVIDERS:
            self.vc_tts_provider.addItem(label)
        current_tts_prov = settings.get("vc_tts_provider", "piper")
        for i, (_, val) in enumerate(VC_TTS_PROVIDERS):
            if val == current_tts_prov:
                self.vc_tts_provider.setCurrentIndex(i)
                break
        vc_form.addRow("TTS Provider", self.vc_tts_provider)

        # TTS model combo (Piper only)
        self.vc_tts_model = QComboBox()
        self._vc_tts_model_label = QLabel("TTS Model")
        self._vc_tts_no_models = QLabel("No TTS models downloaded \u2014 go to AI Models tab.")
        self._vc_tts_no_models.setWordWrap(True)
        self._vc_tts_no_models.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        vc_form.addRow(self._vc_tts_model_label, self.vc_tts_model)
        vc_form.addRow("", self._vc_tts_no_models)
        self._vc_saved_tts = settings.get("vc_tts_model", "")

        # Reference audio + text (voice clone providers only)
        self.vc_tts_ref_audio = QLineEdit(settings.get("vc_tts_ref_audio", ""))
        self.vc_tts_ref_audio.setPlaceholderText("Path to reference WAV (3-15s of speech)")
        self._vc_ref_audio_browse = QPushButton("Browse\u2026")
        self._vc_ref_audio_browse.setCursor(Qt.PointingHandCursor)
        self._vc_ref_audio_browse.setFixedHeight(28)
        self._vc_ref_audio_browse.clicked.connect(self._browse_ref_audio)
        ref_audio_row = QHBoxLayout()
        ref_audio_row.setSpacing(6)
        ref_audio_row.addWidget(self.vc_tts_ref_audio, 1)
        ref_audio_row.addWidget(self._vc_ref_audio_browse)
        self._vc_ref_audio_label = QLabel("Ref Audio")
        vc_form.addRow(self._vc_ref_audio_label, ref_audio_row)

        self.vc_tts_ref_text = QLineEdit(settings.get("vc_tts_ref_text", ""))
        self.vc_tts_ref_text.setPlaceholderText("Transcript of the reference audio")
        self._vc_ref_text_label = QLabel("Ref Text")
        vc_form.addRow(self._vc_ref_text_label, self.vc_tts_ref_text)

        vc_layout.addLayout(vc_form)
        layout.addWidget(self._vc_section)

        # ── System prompt (shared) ──
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

        # Wire signals
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        self.vc_provider.currentIndexChanged.connect(self._on_vc_provider_changed)
        self.vc_tts_provider.currentIndexChanged.connect(self._on_vc_tts_provider_changed)

        # Initial state
        self._on_mode_changed(self.mode_combo.currentIndex())
        self._on_provider_changed(self.provider.currentIndex())
        self._on_vc_provider_changed(self.vc_provider.currentIndex())
        self._on_vc_tts_provider_changed(self.vc_tts_provider.currentIndex())

    def _on_mode_changed(self, index: int) -> None:
        is_realtime = CONVERSATION_MODES[index][1] == "realtime"
        self._realtime_section.setVisible(is_realtime)
        self._vc_section.setVisible(not is_realtime)
        if not is_realtime:
            self.refresh_vc_model_combos()

    def _on_provider_changed(self, index: int) -> None:
        is_gemini = PROVIDERS[index][1] == "gemini"
        self._gemini_key_label.setVisible(is_gemini)
        self.gemini_api_key.setVisible(is_gemini)
        self._gemini_model_label.setVisible(is_gemini)
        self.gemini_model.setVisible(is_gemini)
        self._gemini_voice_label.setVisible(is_gemini)
        self.gemini_voice.setVisible(is_gemini)
        self._openai_key_label.setVisible(not is_gemini)
        self.openai_api_key.setVisible(not is_gemini)
        self._openai_model_label.setVisible(not is_gemini)
        self.openai_model.setVisible(not is_gemini)
        self._openai_voice_label.setVisible(not is_gemini)
        self.openai_voice.setVisible(not is_gemini)

    def _on_vc_provider_changed(self, index: int) -> None:
        prov = VC_LLM_PROVIDERS[index][1]
        self._anthropic_key_label.setVisible(prov == "anthropic")
        self.anthropic_api_key.setVisible(prov == "anthropic")
        self._vc_anthropic_model_label.setVisible(prov == "anthropic")
        self.vc_anthropic_model.setVisible(prov == "anthropic")
        self._vc_openai_key_label.setVisible(prov == "openai")
        self.vc_openai_api_key.setVisible(prov == "openai")
        self._vc_openai_model_label.setVisible(prov == "openai")
        self.vc_openai_model.setVisible(prov == "openai")
        self._vc_gemini_key_label.setVisible(prov == "gemini")
        self.vc_gemini_api_key.setVisible(prov == "gemini")
        self._vc_gemini_model_label.setVisible(prov == "gemini")
        self.vc_gemini_model.setVisible(prov == "gemini")
        self._vc_local_base_url_label.setVisible(prov == "local")
        self.vc_local_base_url.setVisible(prov == "local")
        self._vc_local_model_label.setVisible(prov == "local")
        self.vc_local_model.setVisible(prov == "local")
        self._vc_local_api_key_label.setVisible(prov == "local")
        self.vc_local_api_key.setVisible(prov == "local")
        self._vc_local_tools_label.setVisible(prov == "local")
        self.vc_local_tools.setVisible(prov == "local")

    def _on_vc_tts_provider_changed(self, index: int) -> None:
        prov = VC_TTS_PROVIDERS[index][1]
        is_piper = prov == "piper"
        # Piper-specific widgets
        self._vc_tts_model_label.setVisible(is_piper)
        self.vc_tts_model.setVisible(is_piper)
        self._vc_tts_no_models.setVisible(is_piper and self.vc_tts_model.count() == 0)
        # Voice clone reference fields
        self._vc_ref_audio_label.setVisible(not is_piper)
        self.vc_tts_ref_audio.setVisible(not is_piper)
        self._vc_ref_audio_browse.setVisible(not is_piper)
        self._vc_ref_text_label.setVisible(not is_piper)
        self.vc_tts_ref_text.setVisible(not is_piper)

    def _browse_ref_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference Audio", "", "WAV files (*.wav)"
        )
        if path:
            self.vc_tts_ref_audio.setText(path)

    def refresh_vc_model_combos(self) -> None:
        """Rebuild STT/TTS/VAD model combos with currently downloaded models."""
        from roomkit_ui.model_manager import (
            STT_MODELS,
            TTS_MODELS,
            VAD_MODELS,
            is_model_downloaded,
            is_tts_model_downloaded,
            is_vad_model_downloaded,
        )

        # STT
        self.vc_stt_model.blockSignals(True)
        self.vc_stt_model.clear()
        for m in STT_MODELS:
            if is_model_downloaded(m.id):
                self.vc_stt_model.addItem(f"{m.name} ({m.type})", m.id)
        target = self._vc_saved_stt or (
            self.vc_stt_model.itemData(0) if self.vc_stt_model.count() else ""
        )
        for i in range(self.vc_stt_model.count()):
            if self.vc_stt_model.itemData(i) == target:
                self.vc_stt_model.setCurrentIndex(i)
                break
        self.vc_stt_model.blockSignals(False)
        self._vc_stt_no_models.setVisible(self.vc_stt_model.count() == 0)

        # VAD
        self.vc_vad_model.blockSignals(True)
        self.vc_vad_model.clear()
        self.vc_vad_model.addItem("None (continuous mode)", "")
        for vm in VAD_MODELS:
            if is_vad_model_downloaded(vm.id):
                self.vc_vad_model.addItem(vm.name, vm.id)
        target = self._vc_saved_vad
        for i in range(self.vc_vad_model.count()):
            if self.vc_vad_model.itemData(i) == target:
                self.vc_vad_model.setCurrentIndex(i)
                break
        self.vc_vad_model.blockSignals(False)
        has_vad = self.vc_vad_model.count() > 1  # more than just "None"
        self._vc_vad_no_models.setVisible(not has_vad)

        # TTS
        self.vc_tts_model.blockSignals(True)
        self.vc_tts_model.clear()
        for tm in TTS_MODELS:
            if is_tts_model_downloaded(tm.id):
                self.vc_tts_model.addItem(tm.name, tm.id)
        target = self._vc_saved_tts or (
            self.vc_tts_model.itemData(0) if self.vc_tts_model.count() else ""
        )
        for i in range(self.vc_tts_model.count()):
            if self.vc_tts_model.itemData(i) == target:
                self.vc_tts_model.setCurrentIndex(i)
                break
        self.vc_tts_model.blockSignals(False)
        # Re-apply TTS provider visibility (controls model combo vs ref fields)
        self._on_vc_tts_provider_changed(self.vc_tts_provider.currentIndex())


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
        from roomkit_ui.model_manager import is_model_downloaded

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
        name_label.setStyleSheet("font-size: 13px; font-weight: 500; background: transparent;")
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
                f"font-size: 12px; color: {c['ACCENT_GREEN']}; background: transparent;"
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
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
        )

    def set_resolving(self) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.show()
        self.status_label.setText("Resolving…")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
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
            f"font-size: 12px; color: {self._c['ACCENT_RED']}; background: transparent;"
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

        from roomkit_ui.model_manager import STT_MODELS

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

        from roomkit_ui.model_manager import (
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
            id=GTCRN_MODEL_ID,
            name="GTCRN",
            type="denoiser",
            size=GTCRN_SIZE,
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

        # -- VAD Models section -------------------------------------------------
        vad_section = QLabel("Voice Activity Detection Models")
        vad_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(vad_section)

        vad_desc = QLabel(
            "Download a VAD model for Voice Channel mode. "
            "Required to detect speech segments for offline STT models."
        )
        vad_desc.setWordWrap(True)
        vad_desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(vad_desc)

        vad_frame = QWidget()
        vad_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        vad_frame_layout = QVBoxLayout(vad_frame)
        vad_frame_layout.setContentsMargins(4, 4, 4, 4)
        vad_frame_layout.setSpacing(0)

        from roomkit_ui.model_manager import VAD_MODELS, is_vad_model_downloaded

        self._vad_rows: list[_ModelRow] = []
        for vad_m in VAD_MODELS:
            row = _ModelRow(vad_m, c, show_radio=False)
            row._refresh_state(is_vad_model_downloaded(vad_m.id))
            row.action_btn.clicked.connect(
                lambda _checked=False, mid=vad_m.id: self._download_vad_model(mid)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, mid=vad_m.id: self._delete_vad_model(mid)
            )
            vad_frame_layout.addWidget(row)
            self._vad_rows.append(row)

        layout.addWidget(vad_frame)

        # -- TTS Models section -------------------------------------------------
        tts_section = QLabel("Text-to-Speech Models")
        tts_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(tts_section)

        tts_desc = QLabel(
            "Download local TTS models for Voice Channel mode. "
            "espeak-ng data is a shared dependency required by all Piper models."
        )
        tts_desc.setWordWrap(True)
        tts_desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(tts_desc)

        tts_frame = QWidget()
        tts_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        tts_frame_layout = QVBoxLayout(tts_frame)
        tts_frame_layout.setContentsMargins(4, 4, 4, 4)
        tts_frame_layout.setSpacing(0)

        # espeak-ng-data row (shared dependency)
        from roomkit_ui.model_manager import is_espeak_ng_downloaded

        @dataclass(frozen=True)
        class _EspeakInfo:
            id: str
            name: str
            type: str
            size: str

        espeak_info = _EspeakInfo(
            id="espeak-ng-data",
            name="espeak-ng data",
            type="shared",
            size="~1 MB",
        )
        self._espeak_row = _ModelRow(espeak_info, c, show_radio=False)
        self._espeak_row._refresh_state(is_espeak_ng_downloaded())
        self._espeak_row.action_btn.clicked.connect(self._download_espeak)
        self._espeak_row.delete_btn.clicked.connect(self._delete_espeak)
        tts_frame_layout.addWidget(self._espeak_row)

        # TTS model rows
        from roomkit_ui.model_manager import TTS_MODELS, is_tts_model_downloaded

        @dataclass(frozen=True)
        class _TTSInfo:
            id: str
            name: str
            type: str
            size: str

        self._tts_rows: list[_ModelRow] = []
        for tts_m in TTS_MODELS:
            info = _TTSInfo(id=tts_m.id, name=tts_m.name, type="tts", size=tts_m.size)
            row = _ModelRow(info, c, show_radio=False)
            row._refresh_state(is_tts_model_downloaded(tts_m.id))
            row.action_btn.clicked.connect(
                lambda _checked=False, mid=tts_m.id: self._download_tts_model(mid)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, mid=tts_m.id: self._delete_tts_model(mid)
            )
            tts_frame_layout.addWidget(row)
            self._tts_rows.append(row)

        layout.addWidget(tts_frame)
        layout.addStretch()

    def _find_row(self, model_id: str) -> _ModelRow | None:
        for row in self._model_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_model

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
        from roomkit_ui.model_manager import delete_model

        delete_model(model_id)
        row = self._find_row(model_id)
        if row is not None:
            row.set_not_downloaded()

    def _download_gtcrn(self) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_gtcrn

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
        from roomkit_ui.model_manager import delete_gtcrn

        delete_gtcrn()
        self._gtcrn_row.set_not_downloaded()

    # -- TTS model handlers --------------------------------------------------

    def _find_tts_row(self, model_id: str) -> _ModelRow | None:
        for row in self._tts_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_espeak(self) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_espeak_ng_data

        row = self._espeak_row
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_espeak_ng_data(_progress)
                row.set_downloaded()
            except Exception:
                logging.exception("espeak-ng-data download failed")
                row.set_error()

        loop.create_task(_run())

    def _delete_espeak(self) -> None:
        from roomkit_ui.model_manager import delete_espeak_ng_data

        delete_espeak_ng_data()
        self._espeak_row.set_not_downloaded()

    def _download_tts_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_tts_model

        row = self._find_tts_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_tts_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("TTS model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_tts_model(self, model_id: str) -> None:
        from roomkit_ui.model_manager import delete_tts_model

        delete_tts_model(model_id)
        row = self._find_tts_row(model_id)
        if row is not None:
            row.set_not_downloaded()

    # -- VAD model handlers --------------------------------------------------

    def _find_vad_row(self, model_id: str) -> _ModelRow | None:
        for row in self._vad_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_vad_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_vad_model

        row = self._find_vad_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_vad_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("VAD model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_vad_model(self, model_id: str) -> None:
        from roomkit_ui.model_manager import delete_vad_model

        delete_vad_model(model_id)
        row = self._find_vad_row(model_id)
        if row is not None:
            row.set_not_downloaded()


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
        from roomkit_ui.model_manager import STT_MODELS, is_model_downloaded

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
            "oauth_client_secret": "",
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

    _AI_TAB = 1
    _DICTATION_TAB = 2

    def _on_tab_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == self._AI_TAB:
            self._ai.refresh_vc_model_combos()
        elif index == self._DICTATION_TAB:
            self._dictation.refresh_model_combo()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save()
        super().closeEvent(event)

    def _save(self) -> None:
        from roomkit_ui.theme import get_stylesheet

        # Merge API keys: prefer non-empty from either location
        openai_key = (
            self._ai.openai_api_key.text().strip()
            or self._ai.vc_openai_api_key.text().strip()
            or self._dictation.openai_api_key.text().strip()
        )
        gemini_key = (
            self._ai.gemini_api_key.text().strip() or self._ai.vc_gemini_api_key.text().strip()
        )

        settings = {
            "theme": THEMES[self._general.theme_combo.currentIndex()][1],
            "provider": PROVIDERS[self._ai.provider.currentIndex()][1],
            "api_key": gemini_key,
            "openai_api_key": openai_key,
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
            "assistant_hotkey_enabled": self._general.assistant_hotkey_enabled.isChecked(),
            "assistant_hotkey": self._general.assistant_hotkey.value(),
            "stt_enabled": self._dictation.enabled.isChecked(),
            "stt_hotkey": self._dictation.hotkey.value(),
            "stt_provider": STT_PROVIDERS[self._dictation.stt_provider.currentIndex()][1],
            "stt_model": self._dictation.selected_model_id(),
            "stt_language": STT_LANGUAGES[self._dictation.language.currentIndex()][1],
            "stt_translate": self._dictation.translate.isChecked(),
            "mcp_servers": self._mcp.get_servers_json(),
            # Voice channel settings
            "conversation_mode": CONVERSATION_MODES[self._ai.mode_combo.currentIndex()][1],
            "vc_llm_provider": VC_LLM_PROVIDERS[self._ai.vc_provider.currentIndex()][1],
            "anthropic_api_key": self._ai.anthropic_api_key.text().strip(),
            "vc_anthropic_model": self._ai.vc_anthropic_model.currentText().strip(),
            "vc_openai_model": self._ai.vc_openai_model.currentText().strip(),
            "vc_gemini_model": self._ai.vc_gemini_model.currentText().strip(),
            "vc_stt_model": self._ai.vc_stt_model.currentData() or "",
            "vc_vad_model": self._ai.vc_vad_model.currentData() or "",
            "vc_interruption": self._ai.vc_interruption.isChecked(),
            "vc_tts_provider": VC_TTS_PROVIDERS[self._ai.vc_tts_provider.currentIndex()][1],
            "vc_tts_model": self._ai.vc_tts_model.currentData() or "",
            "vc_tts_ref_audio": self._ai.vc_tts_ref_audio.text().strip(),
            "vc_tts_ref_text": self._ai.vc_tts_ref_text.text().strip(),
            "vc_local_base_url": self._ai.vc_local_base_url.text().strip(),
            "vc_local_model": self._ai.vc_local_model.text().strip(),
            "vc_local_api_key": self._ai.vc_local_api_key.text().strip(),
            "vc_local_tools": self._ai.vc_local_tools.isChecked(),
        }
        save_settings(settings)

        # Apply the new theme stylesheet immediately
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(settings["theme"]))
