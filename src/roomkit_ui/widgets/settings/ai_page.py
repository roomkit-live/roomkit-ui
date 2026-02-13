"""AI settings: conversation mode, provider, API key, model, voice, prompt."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

GEMINI_LANGUAGES = [
    ("Auto-detect", ""),
    ("English (US)", "en-US"),
    ("English (UK)", "en-GB"),
    ("French", "fr-FR"),
    ("Spanish", "es-ES"),
    ("German", "de-DE"),
    ("Italian", "it-IT"),
    ("Portuguese (BR)", "pt-BR"),
    ("Dutch", "nl-NL"),
    ("Japanese", "ja-JP"),
    ("Chinese", "zh-CN"),
    ("Korean", "ko-KR"),
    ("Russian", "ru-RU"),
    ("Arabic", "ar-XA"),
    ("Hindi", "hi-IN"),
]

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

        # ── Gemini Advanced (collapsible) ──
        self._gemini_adv_toggle = QPushButton("\u25b8 Advanced")
        self._gemini_adv_toggle.setFlat(True)
        self._gemini_adv_toggle.setCursor(Qt.PointingHandCursor)
        self._gemini_adv_toggle.setStyleSheet(
            "text-align: left; font-size: 12px; font-weight: 600;"
            f" color: {c['TEXT_SECONDARY']}; background: transparent; border: none;"
            " padding: 2px 0;"
        )
        self._gemini_adv_toggle.clicked.connect(self._toggle_gemini_advanced)
        rt_layout.addWidget(self._gemini_adv_toggle)

        self._gemini_adv_container = QWidget()
        adv_form = QFormLayout(self._gemini_adv_container)
        adv_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        adv_form.setSpacing(10)
        adv_form.setLabelAlignment(Qt.AlignRight)

        self.gemini_language = QComboBox()
        for label, _val in GEMINI_LANGUAGES:
            self.gemini_language.addItem(label, _val)
        saved_lang = settings.get("gemini_language", "")
        for i, (_, val) in enumerate(GEMINI_LANGUAGES):
            if val == saved_lang:
                self.gemini_language.setCurrentIndex(i)
                break
        adv_form.addRow("Language", self.gemini_language)

        self.gemini_no_interruption = QCheckBox("Disable barge-in")
        self.gemini_no_interruption.setChecked(bool(settings.get("gemini_no_interruption", False)))
        adv_form.addRow("", self.gemini_no_interruption)

        self.gemini_affective_dialog = QCheckBox("Emotional responses")
        self.gemini_affective_dialog.setChecked(
            bool(settings.get("gemini_affective_dialog", False))
        )
        adv_form.addRow("", self.gemini_affective_dialog)

        self.gemini_proactive_audio = QCheckBox("AI can speak unprompted")
        self.gemini_proactive_audio.setChecked(bool(settings.get("gemini_proactive_audio", False)))
        adv_form.addRow("", self.gemini_proactive_audio)

        start_sens_options = [
            ("Auto", ""),
            ("High", "START_SENSITIVITY_HIGH"),
            ("Low", "START_SENSITIVITY_LOW"),
        ]
        self.gemini_start_sensitivity = QComboBox()
        for label, _val in start_sens_options:
            self.gemini_start_sensitivity.addItem(label, _val)
        saved_start = settings.get("gemini_start_sensitivity", "")
        for i, (_, val) in enumerate(start_sens_options):
            if val == saved_start:
                self.gemini_start_sensitivity.setCurrentIndex(i)
                break
        adv_form.addRow("Start Speech", self.gemini_start_sensitivity)

        end_sens_options = [
            ("Auto", ""),
            ("High", "END_SENSITIVITY_HIGH"),
            ("Low", "END_SENSITIVITY_LOW"),
        ]
        self.gemini_end_sensitivity = QComboBox()
        for label, _val in end_sens_options:
            self.gemini_end_sensitivity.addItem(label, _val)
        saved_end = settings.get("gemini_end_sensitivity", "")
        for i, (_, val) in enumerate(end_sens_options):
            if val == saved_end:
                self.gemini_end_sensitivity.setCurrentIndex(i)
                break
        adv_form.addRow("End Speech", self.gemini_end_sensitivity)

        self.gemini_silence_duration = QLineEdit(
            str(settings.get("gemini_silence_duration_ms", "") or "")
        )
        self.gemini_silence_duration.setPlaceholderText("e.g. 1000")
        adv_form.addRow("Silence (ms)", self.gemini_silence_duration)

        self._gemini_adv_container.hide()
        rt_layout.addWidget(self._gemini_adv_container)

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

        # ── Default Attitude (shared) ──
        attitude_label = QLabel("Default Attitude")
        attitude_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(attitude_label)

        self.attitude_combo = QComboBox()
        layout.addWidget(self.attitude_combo)

        attitude_hint = QLabel(
            "Select the assistant's default personality. Manage attitudes in the Attitudes tab."
        )
        attitude_hint.setWordWrap(True)
        attitude_hint.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(attitude_hint)

        self._saved_selected_attitude = settings.get("selected_attitude", "")

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
        self._gemini_adv_toggle.setVisible(is_gemini)
        if not is_gemini:
            self._gemini_adv_container.hide()

    def _toggle_gemini_advanced(self) -> None:
        visible = not self._gemini_adv_container.isVisible()
        self._gemini_adv_container.setVisible(visible)
        self._gemini_adv_toggle.setText("\u25be Advanced" if visible else "\u25b8 Advanced")

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

    def populate_attitude_combo(self, all_names: list[str]) -> None:
        """Rebuild the attitude combo from the given list of names."""
        self.attitude_combo.blockSignals(True)
        self.attitude_combo.clear()
        self.attitude_combo.addItem("None")
        for name in all_names:
            self.attitude_combo.addItem(name)
        # Restore saved selection
        saved = self._saved_selected_attitude
        if saved:
            idx = self.attitude_combo.findText(saved)
            if idx >= 0:
                self.attitude_combo.setCurrentIndex(idx)
        self.attitude_combo.blockSignals(False)

    def selected_attitude_name(self) -> str:
        text = str(self.attitude_combo.currentText())
        return "" if text == "None" else text

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

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "provider": PROVIDERS[self.provider.currentIndex()][1],
            "_rt_gemini_key": self.gemini_api_key.text().strip(),
            "_rt_openai_key": self.openai_api_key.text().strip(),
            "model": self.gemini_model.currentText().strip(),
            "openai_model": self.openai_model.currentText().strip(),
            "voice": self.gemini_voice.currentText(),
            "openai_voice": self.openai_voice.currentText(),
            "gemini_language": self.gemini_language.currentData() or "",
            "gemini_no_interruption": self.gemini_no_interruption.isChecked(),
            "gemini_affective_dialog": self.gemini_affective_dialog.isChecked(),
            "gemini_proactive_audio": self.gemini_proactive_audio.isChecked(),
            "gemini_start_sensitivity": self.gemini_start_sensitivity.currentData() or "",
            "gemini_end_sensitivity": self.gemini_end_sensitivity.currentData() or "",
            "gemini_silence_duration_ms": self.gemini_silence_duration.text().strip(),
            "system_prompt": self.prompt.toPlainText().strip(),
            "selected_attitude": self.selected_attitude_name(),
            "conversation_mode": CONVERSATION_MODES[self.mode_combo.currentIndex()][1],
            "vc_llm_provider": VC_LLM_PROVIDERS[self.vc_provider.currentIndex()][1],
            "anthropic_api_key": self.anthropic_api_key.text().strip(),
            "_vc_openai_key": self.vc_openai_api_key.text().strip(),
            "_vc_gemini_key": self.vc_gemini_api_key.text().strip(),
            "vc_anthropic_model": self.vc_anthropic_model.currentText().strip(),
            "vc_openai_model": self.vc_openai_model.currentText().strip(),
            "vc_gemini_model": self.vc_gemini_model.currentText().strip(),
            "vc_stt_model": self.vc_stt_model.currentData() or "",
            "vc_vad_model": self.vc_vad_model.currentData() or "",
            "vc_interruption": self.vc_interruption.isChecked(),
            "vc_tts_provider": VC_TTS_PROVIDERS[self.vc_tts_provider.currentIndex()][1],
            "vc_tts_model": self.vc_tts_model.currentData() or "",
            "vc_tts_ref_audio": self.vc_tts_ref_audio.text().strip(),
            "vc_tts_ref_text": self.vc_tts_ref_text.text().strip(),
            "vc_local_base_url": self.vc_local_base_url.text().strip(),
            "vc_local_model": self.vc_local_model.text().strip(),
            "vc_local_api_key": self.vc_local_api_key.text().strip(),
            "vc_local_tools": self.vc_local_tools.isChecked(),
        }
