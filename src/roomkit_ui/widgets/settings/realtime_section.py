"""Realtime (speech-to-speech) provider settings.

Five providers: Gemini Live, OpenAI Realtime, Deepgram Voice Agent,
ElevenLabs Conversational AI and xAI Grok.  Each provider's widgets are
registered in ``self._provider_widgets`` so switching the provider combo
shows exactly one group.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

PROVIDERS = [
    ("Google Gemini", "gemini"),
    ("OpenAI", "openai"),
    ("Deepgram Voice Agent", "deepgram"),
    ("ElevenLabs (Conversational AI)", "elevenlabs"),
    ("xAI Grok", "xai"),
]

GEMINI_MODELS = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.0-flash-live-001",
]
GEMINI_VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Puck"]

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

OPENAI_MODELS = [
    "gpt-realtime-2.1",
    "gpt-realtime-2.1-mini",
    "gpt-4o-realtime-preview",
]
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

# Curated Aura-2 speak models (roomkit's full offline catalog has 100+;
# the combo stays editable so any "aura-2-{name}-{lang}" id can be typed).
DEEPGRAM_VOICES = [
    "aura-2-thalia-en",
    "aura-2-andromeda-en",
    "aura-2-apollo-en",
    "aura-2-asteria-en",
    "aura-2-athena-en",
    "aura-2-atlas-en",
    "aura-2-helena-en",
    "aura-2-hermes-en",
    "aura-2-orion-en",
    "aura-2-agathe-fr",
    "aura-2-hector-fr",
]
DEEPGRAM_THINK_PROVIDERS = [
    ("OpenAI", "open_ai"),
    ("Anthropic", "anthropic"),
    ("Google", "google"),
]

XAI_MODELS = ["grok-2-audio"]
XAI_VOICES = ["eve", "ara", "rex", "sal", "leo"]


class RealtimeSection(QWidget):
    """Realtime speech-to-speech provider settings."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = colors()

        rt_layout = QVBoxLayout(self)
        rt_layout.setContentsMargins(0, 0, 0, 0)
        rt_layout.setSpacing(10)

        section_label = QLabel("Realtime Provider")
        section_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        rt_layout.addWidget(section_label)

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

        # ── Deepgram Voice Agent ──
        self.deepgram_api_key = QLineEdit(settings.get("deepgram_api_key", ""))
        self.deepgram_api_key.setEchoMode(QLineEdit.Password)
        self.deepgram_api_key.setPlaceholderText("Enter your Deepgram API key")
        self._deepgram_key_label = QLabel("API Key")
        rt_form.addRow(self._deepgram_key_label, self.deepgram_api_key)

        self.deepgram_voice = QComboBox()
        self.deepgram_voice.setEditable(True)
        self.deepgram_voice.addItems(DEEPGRAM_VOICES)
        current_dg_voice = settings.get("deepgram_agent_voice", DEEPGRAM_VOICES[0])
        dgidx = self.deepgram_voice.findText(current_dg_voice)
        if dgidx >= 0:
            self.deepgram_voice.setCurrentIndex(dgidx)
        else:
            self.deepgram_voice.setCurrentText(current_dg_voice)
        self._deepgram_voice_label = QLabel("Voice")
        rt_form.addRow(self._deepgram_voice_label, self.deepgram_voice)

        # ── ElevenLabs Conversational AI ──
        self.elevenlabs_api_key = QLineEdit(settings.get("elevenlabs_api_key", ""))
        self.elevenlabs_api_key.setEchoMode(QLineEdit.Password)
        self.elevenlabs_api_key.setPlaceholderText("Enter your ElevenLabs API key")
        self._elevenlabs_key_label = QLabel("API Key")
        rt_form.addRow(self._elevenlabs_key_label, self.elevenlabs_api_key)

        self.elevenlabs_agent_id = QLineEdit(settings.get("elevenlabs_agent_id", ""))
        self.elevenlabs_agent_id.setPlaceholderText("agent_… (ElevenLabs dashboard → Agents)")
        self._elevenlabs_agent_label = QLabel("Agent ID")
        rt_form.addRow(self._elevenlabs_agent_label, self.elevenlabs_agent_id)

        self._elevenlabs_note = QLabel(
            "Model, voice and turn detection are configured on the agent itself "
            "(ElevenLabs dashboard). Tools must be declared there as client tools."
        )
        self._elevenlabs_note.setWordWrap(True)
        self._elevenlabs_note.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        rt_form.addRow("", self._elevenlabs_note)

        # ── xAI Grok ──
        self.xai_api_key = QLineEdit(settings.get("xai_api_key", ""))
        self.xai_api_key.setEchoMode(QLineEdit.Password)
        self.xai_api_key.setPlaceholderText("Enter your xAI API key")
        self._xai_key_label = QLabel("API Key")
        rt_form.addRow(self._xai_key_label, self.xai_api_key)

        self.xai_model = QComboBox()
        self.xai_model.setEditable(True)
        self.xai_model.addItems(XAI_MODELS)
        current_xai_model = settings.get("xai_model", XAI_MODELS[0])
        xmidx = self.xai_model.findText(current_xai_model)
        if xmidx >= 0:
            self.xai_model.setCurrentIndex(xmidx)
        else:
            self.xai_model.setCurrentText(current_xai_model)
        self._xai_model_label = QLabel("Model")
        rt_form.addRow(self._xai_model_label, self.xai_model)

        self.xai_voice = QComboBox()
        self.xai_voice.addItems(XAI_VOICES)
        current_xai_voice = settings.get("xai_voice", "eve")
        xvidx = self.xai_voice.findText(current_xai_voice)
        if xvidx >= 0:
            self.xai_voice.setCurrentIndex(xvidx)
        self._xai_voice_label = QLabel("Voice")
        rt_form.addRow(self._xai_voice_label, self.xai_voice)

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

        # ── OpenAI Advanced (collapsible) ──
        self._openai_adv_toggle = QPushButton("\u25b8 Advanced")
        self._openai_adv_toggle.setFlat(True)
        self._openai_adv_toggle.setCursor(Qt.PointingHandCursor)
        self._openai_adv_toggle.setStyleSheet(
            "text-align: left; font-size: 12px; font-weight: 600;"
            f" color: {c['TEXT_SECONDARY']}; background: transparent; border: none;"
            " padding: 2px 0;"
        )
        self._openai_adv_toggle.clicked.connect(self._toggle_openai_advanced)
        rt_layout.addWidget(self._openai_adv_toggle)

        self._openai_adv_container = QWidget()
        oai_form = QFormLayout(self._openai_adv_container)
        oai_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        oai_form.setSpacing(10)
        oai_form.setLabelAlignment(Qt.AlignRight)

        turn_detection_options = [
            ("Server VAD (energy-based)", "server_vad"),
            ("Semantic VAD (turn-aware)", "semantic_vad"),
            ("Disabled (manual)", "none"),
        ]
        self.openai_turn_detection = QComboBox()
        for label, val in turn_detection_options:
            self.openai_turn_detection.addItem(label, val)
        saved_td = settings.get("openai_turn_detection", "server_vad")
        for i, (_, val) in enumerate(turn_detection_options):
            if val == saved_td:
                self.openai_turn_detection.setCurrentIndex(i)
                break
        oai_form.addRow("Turn Detection", self.openai_turn_detection)

        self.openai_eagerness = QLineEdit(str(settings.get("openai_eagerness", "") or ""))
        self.openai_eagerness.setPlaceholderText("0.8 (0 = patient \u2026 1 = eager)")
        self._openai_eagerness_label = QLabel("Eagerness")
        oai_form.addRow(self._openai_eagerness_label, self.openai_eagerness)

        self.openai_vad_threshold = QLineEdit(str(settings.get("openai_vad_threshold", "") or ""))
        self.openai_vad_threshold.setPlaceholderText("0.5 (0 \u2013 1)")
        self._openai_vad_threshold_label = QLabel("VAD Threshold")
        oai_form.addRow(self._openai_vad_threshold_label, self.openai_vad_threshold)

        self.openai_silence_duration = QLineEdit(
            str(settings.get("openai_silence_duration_ms", "") or "")
        )
        self.openai_silence_duration.setPlaceholderText("200 (ms)")
        self._openai_silence_label = QLabel("Silence (ms)")
        oai_form.addRow(self._openai_silence_label, self.openai_silence_duration)

        self.openai_prefix_padding = QLineEdit(
            str(settings.get("openai_prefix_padding_ms", "") or "")
        )
        self.openai_prefix_padding.setPlaceholderText("300 (ms)")
        self._openai_prefix_label = QLabel("Prefix Padding (ms)")
        oai_form.addRow(self._openai_prefix_label, self.openai_prefix_padding)

        self.openai_interrupt_response = QCheckBox("Allow interrupting AI response")
        self.openai_interrupt_response.setChecked(
            bool(settings.get("openai_interrupt_response", True))
        )
        oai_form.addRow("", self.openai_interrupt_response)

        self.openai_create_response = QCheckBox("Auto-respond on turn end")
        self.openai_create_response.setChecked(bool(settings.get("openai_create_response", True)))
        oai_form.addRow("", self.openai_create_response)

        self._openai_adv_container.hide()
        rt_layout.addWidget(self._openai_adv_container)

        # ── Deepgram Advanced (collapsible) ──
        self._deepgram_adv_toggle = QPushButton("▸ Advanced")
        self._deepgram_adv_toggle.setFlat(True)
        self._deepgram_adv_toggle.setCursor(Qt.PointingHandCursor)
        self._deepgram_adv_toggle.setStyleSheet(
            "text-align: left; font-size: 12px; font-weight: 600;"
            f" color: {c['TEXT_SECONDARY']}; background: transparent; border: none;"
            " padding: 2px 0;"
        )
        self._deepgram_adv_toggle.clicked.connect(self._toggle_deepgram_advanced)
        rt_layout.addWidget(self._deepgram_adv_toggle)

        self._deepgram_adv_container = QWidget()
        dg_form = QFormLayout(self._deepgram_adv_container)
        dg_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        dg_form.setSpacing(10)
        dg_form.setLabelAlignment(Qt.AlignRight)

        self.deepgram_think_provider = QComboBox()
        for label, val in DEEPGRAM_THINK_PROVIDERS:
            self.deepgram_think_provider.addItem(label, val)
        saved_think = settings.get("deepgram_agent_think_provider", "open_ai")
        for i, (_, val) in enumerate(DEEPGRAM_THINK_PROVIDERS):
            if val == saved_think:
                self.deepgram_think_provider.setCurrentIndex(i)
                break
        dg_form.addRow("LLM Provider", self.deepgram_think_provider)

        self.deepgram_think_model = QLineEdit(settings.get("deepgram_agent_think_model", "") or "")
        self.deepgram_think_model.setPlaceholderText("gpt-4o-mini (default)")
        dg_form.addRow("LLM Model", self.deepgram_think_model)

        self.deepgram_listen_language = QLineEdit(
            settings.get("deepgram_agent_listen_language", "") or ""
        )
        self.deepgram_listen_language.setPlaceholderText("e.g. fr, en, multi (empty = default)")
        dg_form.addRow("Language", self.deepgram_listen_language)

        self.deepgram_greeting = QLineEdit(settings.get("deepgram_agent_greeting", "") or "")
        self.deepgram_greeting.setPlaceholderText("Optional line spoken when the session opens")
        dg_form.addRow("Greeting", self.deepgram_greeting)

        self._deepgram_adv_container.hide()
        rt_layout.addWidget(self._deepgram_adv_container)

        # ── xAI Advanced (collapsible) ──
        self._xai_adv_toggle = QPushButton("▸ Advanced")
        self._xai_adv_toggle.setFlat(True)
        self._xai_adv_toggle.setCursor(Qt.PointingHandCursor)
        self._xai_adv_toggle.setStyleSheet(
            "text-align: left; font-size: 12px; font-weight: 600;"
            f" color: {c['TEXT_SECONDARY']}; background: transparent; border: none;"
            " padding: 2px 0;"
        )
        self._xai_adv_toggle.clicked.connect(self._toggle_xai_advanced)
        rt_layout.addWidget(self._xai_adv_toggle)

        self._xai_adv_container = QWidget()
        xai_form = QFormLayout(self._xai_adv_container)
        xai_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        xai_form.setSpacing(10)
        xai_form.setLabelAlignment(Qt.AlignRight)

        self.xai_vad_threshold = QLineEdit(str(settings.get("xai_vad_threshold", "") or ""))
        self.xai_vad_threshold.setPlaceholderText("0.5 (0 – 1)")
        xai_form.addRow("VAD Threshold", self.xai_vad_threshold)

        self.xai_silence_duration = QLineEdit(
            str(settings.get("xai_silence_duration_ms", "") or "")
        )
        self.xai_silence_duration.setPlaceholderText("200 (ms)")
        xai_form.addRow("Silence (ms)", self.xai_silence_duration)

        self.xai_prefix_padding = QLineEdit(str(settings.get("xai_prefix_padding_ms", "") or ""))
        self.xai_prefix_padding.setPlaceholderText("300 (ms)")
        xai_form.addRow("Prefix Padding (ms)", self.xai_prefix_padding)

        self._xai_adv_container.hide()
        rt_layout.addWidget(self._xai_adv_container)

        # Provider → widgets that must be visible only for it.  Advanced
        # containers are handled separately (they stay collapsed on switch).
        self._provider_widgets: dict[str, list[QWidget]] = {
            "gemini": [
                self._gemini_key_label,
                self.gemini_api_key,
                self._gemini_model_label,
                self.gemini_model,
                self._gemini_voice_label,
                self.gemini_voice,
                self._gemini_adv_toggle,
            ],
            "openai": [
                self._openai_key_label,
                self.openai_api_key,
                self._openai_model_label,
                self.openai_model,
                self._openai_voice_label,
                self.openai_voice,
                self._openai_adv_toggle,
            ],
            "deepgram": [
                self._deepgram_key_label,
                self.deepgram_api_key,
                self._deepgram_voice_label,
                self.deepgram_voice,
                self._deepgram_adv_toggle,
            ],
            "elevenlabs": [
                self._elevenlabs_key_label,
                self.elevenlabs_api_key,
                self._elevenlabs_agent_label,
                self.elevenlabs_agent_id,
                self._elevenlabs_note,
            ],
            "xai": [
                self._xai_key_label,
                self.xai_api_key,
                self._xai_model_label,
                self.xai_model,
                self._xai_voice_label,
                self.xai_voice,
                self._xai_adv_toggle,
            ],
        }
        self._adv_containers = {
            "gemini": (self._gemini_adv_container, self._gemini_adv_toggle),
            "openai": (self._openai_adv_container, self._openai_adv_toggle),
            "deepgram": (self._deepgram_adv_container, self._deepgram_adv_toggle),
            "xai": (self._xai_adv_container, self._xai_adv_toggle),
        }

        # Wire signals
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        self.openai_turn_detection.currentIndexChanged.connect(
            self._on_openai_turn_detection_changed
        )

        # Initial state
        self._on_provider_changed(self.provider.currentIndex())

    # -- Visibility handlers --

    def _on_provider_changed(self, index: int) -> None:
        current = PROVIDERS[index][1]
        for name, widgets in self._provider_widgets.items():
            visible = name == current
            for w in widgets:
                w.setVisible(visible)
        # Collapse the advanced blocks of every other provider.
        for name, (container, toggle) in self._adv_containers.items():
            if name != current:
                container.hide()
                toggle.setText("\u25b8 Advanced")

    def _toggle_gemini_advanced(self) -> None:
        visible = not self._gemini_adv_container.isVisible()
        self._gemini_adv_container.setVisible(visible)
        self._gemini_adv_toggle.setText("\u25be Advanced" if visible else "\u25b8 Advanced")

    def _toggle_openai_advanced(self) -> None:
        visible = not self._openai_adv_container.isVisible()
        self._openai_adv_container.setVisible(visible)
        self._openai_adv_toggle.setText("\u25be Advanced" if visible else "\u25b8 Advanced")
        if visible:
            self._on_openai_turn_detection_changed(self.openai_turn_detection.currentIndex())

    def _toggle_deepgram_advanced(self) -> None:
        visible = not self._deepgram_adv_container.isVisible()
        self._deepgram_adv_container.setVisible(visible)
        self._deepgram_adv_toggle.setText("\u25be Advanced" if visible else "\u25b8 Advanced")

    def _toggle_xai_advanced(self) -> None:
        visible = not self._xai_adv_container.isVisible()
        self._xai_adv_container.setVisible(visible)
        self._xai_adv_toggle.setText("\u25be Advanced" if visible else "\u25b8 Advanced")

    def _on_openai_turn_detection_changed(self, _index: int) -> None:
        td = self.openai_turn_detection.currentData()
        is_semantic = td == "semantic_vad"
        is_server = td == "server_vad"
        is_any = is_semantic or is_server
        self._openai_eagerness_label.setVisible(is_semantic)
        self.openai_eagerness.setVisible(is_semantic)
        self._openai_vad_threshold_label.setVisible(is_server)
        self.openai_vad_threshold.setVisible(is_server)
        self._openai_silence_label.setVisible(is_server)
        self.openai_silence_duration.setVisible(is_server)
        self._openai_prefix_label.setVisible(is_server)
        self.openai_prefix_padding.setVisible(is_server)
        self.openai_interrupt_response.setVisible(is_any)
        self.openai_create_response.setVisible(is_any)

    # -- Settings --

    def get_settings(self) -> dict:
        return {
            "provider": PROVIDERS[self.provider.currentIndex()][1],
            "_rt_gemini_key": self.gemini_api_key.text().strip(),
            "_rt_openai_key": self.openai_api_key.text().strip(),
            "_rt_deepgram_key": self.deepgram_api_key.text().strip(),
            "_rt_elevenlabs_key": self.elevenlabs_api_key.text().strip(),
            "deepgram_agent_voice": self.deepgram_voice.currentText().strip(),
            "deepgram_agent_think_provider": (
                self.deepgram_think_provider.currentData() or "open_ai"
            ),
            "deepgram_agent_think_model": self.deepgram_think_model.text().strip(),
            "deepgram_agent_listen_language": self.deepgram_listen_language.text().strip(),
            "deepgram_agent_greeting": self.deepgram_greeting.text().strip(),
            "elevenlabs_agent_id": self.elevenlabs_agent_id.text().strip(),
            "xai_api_key": self.xai_api_key.text().strip(),
            "xai_model": self.xai_model.currentText().strip(),
            "xai_voice": self.xai_voice.currentText(),
            "xai_vad_threshold": self.xai_vad_threshold.text().strip(),
            "xai_silence_duration_ms": self.xai_silence_duration.text().strip(),
            "xai_prefix_padding_ms": self.xai_prefix_padding.text().strip(),
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
            "openai_turn_detection": (self.openai_turn_detection.currentData() or "server_vad"),
            "openai_eagerness": self.openai_eagerness.text().strip(),
            "openai_vad_threshold": self.openai_vad_threshold.text().strip(),
            "openai_silence_duration_ms": self.openai_silence_duration.text().strip(),
            "openai_prefix_padding_ms": self.openai_prefix_padding.text().strip(),
            "openai_interrupt_response": self.openai_interrupt_response.isChecked(),
            "openai_create_response": self.openai_create_response.isChecked(),
        }
