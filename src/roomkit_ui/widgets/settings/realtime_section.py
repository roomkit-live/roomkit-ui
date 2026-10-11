"""Realtime (speech-to-speech) provider settings.

Six providers: Gemini Live, OpenAI Realtime, Deepgram Voice Agent,
ElevenLabs Conversational AI, xAI Grok and OpenAI GPT-Live.  Each provider's widgets are
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
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.features import REALTIME_PROVIDER_FEATURES
from roomkit_ui.widgets.settings.controls import AdvancedSection, SettingsSection
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.realtime_catalogs import (
    DEEPGRAM_LANGUAGES,
    DEEPGRAM_LISTEN_MODELS,
    DEEPGRAM_THINK_CATALOGS,
    DEEPGRAM_THINK_PROVIDERS,
    DEEPGRAM_VOICES,
    GEMINI_LANGUAGES,
    GEMINI_MODELS,
    GEMINI_VOICES,
    OPENAI_MODELS,
    OPENAI_VOICES,
    PROVIDERS,
    XAI_MODELS,
    XAI_VOICES,
    chat_model_options,
    populate_model_combo,
    populate_voice_combo,
    sts_model_options,
    voice_options,
)
from roomkit_ui.widgets.settings.realtime_gemini_live import GeminiGenerationFields
from roomkit_ui.widgets.settings.realtime_gpt_live import GPTLiveFields


class RealtimeSection(QWidget):
    """Realtime speech-to-speech provider settings."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        rt_layout = QVBoxLayout(self)
        rt_layout.setContentsMargins(0, 0, 0, 0)
        rt_layout.setSpacing(10)

        section = SettingsSection("Your voice assistant")
        section.content.setContentsMargins(20, 20, 20, 20)
        rt_layout.addWidget(section)
        rt_layout.setSpacing(20)

        rt_form = QFormLayout()
        rt_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        rt_form.setSpacing(10)
        rt_form.setLabelAlignment(Qt.AlignLeft)
        rt_form.setRowWrapPolicy(QFormLayout.WrapAllRows)

        self._add_provider_selector(settings, rt_form)
        self._add_models_and_voices(settings, rt_form)
        self._add_deepgram_fields(settings, rt_form)
        self._add_elevenlabs_fields(settings, rt_form)
        self._add_xai_fields(settings, rt_form)
        self._add_openai_live_fields(settings, rt_form)
        section.content.addLayout(rt_form)
        self._add_gemini_advanced(settings, rt_layout)
        self._add_openai_advanced(settings, rt_layout)
        self._add_deepgram_advanced(settings, rt_layout)
        self._add_xai_advanced(settings, rt_layout)
        self._map_provider_widgets()

        # Wire signals
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        self.openai_turn_detection.currentIndexChanged.connect(
            self._on_openai_turn_detection_changed
        )
        self.deepgram_think_provider.currentIndexChanged.connect(self._on_think_provider_changed)
        self.gemini_model.currentTextChanged.connect(self._gemini_generation.update_for_model)

        # Initial state
        self._on_provider_changed(self.provider.currentIndex())
        self._gemini_generation.update_for_model(self.gemini_model.currentText())

    def _add_provider_selector(self, settings: dict, rt_form: QFormLayout) -> None:
        """The provider combo, set to the saved provider."""
        self.provider = QComboBox()
        populate_provider_combo(self.provider, PROVIDERS, REALTIME_PROVIDER_FEATURES)
        current_provider = settings.get("provider", "gemini")
        for i, (_, val) in enumerate(PROVIDERS):
            if val == current_provider:
                self.provider.setCurrentIndex(i)
                break
        rt_form.addRow("Provider", self.provider)
        rt_form.addRow("", offer_install(self.provider, PROVIDERS, REALTIME_PROVIDER_FEATURES))

    def _add_models_and_voices(self, settings: dict, rt_form: QFormLayout) -> None:
        """Gemini and OpenAI model and voice combos, fed by roomkit's catalogs."""
        # Model (Gemini)
        self.gemini_model = QComboBox()
        populate_model_combo(
            self.gemini_model,
            sts_model_options("roomkit.providers.gemini.realtime_models", GEMINI_MODELS),
            settings.get("model", GEMINI_MODELS[0]),
        )
        self._gemini_model_label = QLabel("Model")
        rt_form.addRow(self._gemini_model_label, self.gemini_model)

        # Model (OpenAI)
        self.openai_model = QComboBox()
        populate_model_combo(
            self.openai_model,
            sts_model_options("roomkit.providers.openai.realtime_models", OPENAI_MODELS),
            settings.get("openai_model", OPENAI_MODELS[0]),
        )
        self._openai_model_label = QLabel("Model")
        rt_form.addRow(self._openai_model_label, self.openai_model)

        # Voice (Gemini)
        self.gemini_voice = QComboBox()
        populate_voice_combo(
            self.gemini_voice,
            voice_options("roomkit.providers.gemini.voices", GEMINI_VOICES),
            settings.get("voice", "Aoede"),
        )
        self._gemini_voice_label = QLabel("Voice")
        rt_form.addRow(self._gemini_voice_label, self.gemini_voice)

        # Voice (OpenAI)
        self.openai_voice = QComboBox()
        populate_voice_combo(
            self.openai_voice,
            voice_options("roomkit.providers.openai.voices", OPENAI_VOICES),
            settings.get("openai_voice", "alloy"),
        )
        self._openai_voice_label = QLabel("Voice")
        rt_form.addRow(self._openai_voice_label, self.openai_voice)

    def _add_deepgram_fields(self, settings: dict, rt_form: QFormLayout) -> None:
        """Deepgram Voice Agent: think/speak/listen stages and the half-duplex escape hatch."""

        self.deepgram_voice = QComboBox()
        self.deepgram_voice.setEditable(True)
        populate_voice_combo(
            self.deepgram_voice,
            voice_options("roomkit.providers.deepgram.voices", DEEPGRAM_VOICES),
            settings.get("deepgram_agent_voice", DEEPGRAM_VOICES[0]),
        )
        self._deepgram_voice_label = QLabel("Voice")
        rt_form.addRow(self._deepgram_voice_label, self.deepgram_voice)

        self.deepgram_language = QComboBox()
        for label, val in DEEPGRAM_LANGUAGES:
            self.deepgram_language.addItem(label, val)
        saved_dg_lang = settings.get("deepgram_agent_listen_language", "")
        for i, (_, val) in enumerate(DEEPGRAM_LANGUAGES):
            if val == saved_dg_lang:
                self.deepgram_language.setCurrentIndex(i)
                break
        self._deepgram_language_label = QLabel("Language")
        rt_form.addRow(self._deepgram_language_label, self.deepgram_language)

        # Deepgram owns turn detection with no sensitivity knob.  The
        # default wiring (transport AEC + NS, per roomkit's example) keeps
        # the mic open; this is the escape hatch when echo still trips it.
        self.deepgram_half_duplex = QCheckBox("Prevent barge-in (mute mic while agent speaks)")
        self.deepgram_half_duplex.setChecked(
            bool(settings.get("deepgram_agent_half_duplex", False))
        )
        rt_form.addRow("", self.deepgram_half_duplex)

    def _add_elevenlabs_fields(self, settings: dict, rt_form: QFormLayout) -> None:
        """ElevenLabs Conversational AI: the agent defines model and voice."""

        self.elevenlabs_agent_id = QLineEdit(settings.get("elevenlabs_agent_id", ""))
        self.elevenlabs_agent_id.setPlaceholderText("agent_… (ElevenLabs dashboard → Agents)")
        self._elevenlabs_agent_label = QLabel("Agent ID")
        rt_form.addRow(self._elevenlabs_agent_label, self.elevenlabs_agent_id)

        self._elevenlabs_note = QLabel(
            "Model, voice and turn detection are configured on the agent itself "
            "(ElevenLabs dashboard). Tools must be declared there as client tools."
        )
        self._elevenlabs_note.setWordWrap(True)
        self._elevenlabs_note.setObjectName("settingsHint")
        rt_form.addRow("", self._elevenlabs_note)

    def _add_xai_fields(self, settings: dict, rt_form: QFormLayout) -> None:
        """xAI Grok model and voice."""

        self.xai_model = QComboBox()
        populate_model_combo(
            self.xai_model,
            sts_model_options("roomkit.providers.xai.realtime_models", XAI_MODELS),
            settings.get("xai_model", XAI_MODELS[0]),
        )
        self._xai_model_label = QLabel("Model")
        rt_form.addRow(self._xai_model_label, self.xai_model)

        self.xai_voice = QComboBox()
        populate_voice_combo(
            self.xai_voice,
            voice_options("roomkit.providers.xai.voices", XAI_VOICES),
            settings.get("xai_voice", "eve"),
        )
        self._xai_voice_label = QLabel("Voice")
        rt_form.addRow(self._xai_voice_label, self.xai_voice)

    def _add_openai_live_fields(self, settings: dict, rt_form: QFormLayout) -> None:
        """OpenAI GPT-Live model and voice controls."""
        self._gpt_live = GPTLiveFields(settings, rt_form)

    def _add_gemini_advanced(self, settings: dict, rt_layout: QVBoxLayout) -> None:
        """Gemini Advanced (collapsible)."""
        self._gemini_adv_container = QWidget()
        adv_form = QFormLayout(self._gemini_adv_container)
        adv_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        adv_form.setSpacing(10)
        adv_form.setLabelAlignment(Qt.AlignLeft)
        adv_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        adv_form.setContentsMargins(20, 16, 20, 16)

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

        self._gemini_generation = GeminiGenerationFields(
            settings,
            adv_form,
            proactive=self.gemini_proactive_audio,
            affective=self.gemini_affective_dialog,
        )

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

        self._gemini_advanced = AdvancedSection(
            "Advanced realtime settings", self._gemini_adv_container
        )
        rt_layout.addWidget(self._gemini_advanced)

    def _add_openai_advanced(self, settings: dict, rt_layout: QVBoxLayout) -> None:
        """OpenAI Advanced (collapsible)."""
        self._openai_adv_container = QWidget()
        oai_form = QFormLayout(self._openai_adv_container)
        oai_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        oai_form.setSpacing(10)
        oai_form.setLabelAlignment(Qt.AlignLeft)
        oai_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        oai_form.setContentsMargins(20, 16, 20, 16)

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

        reasoning_options = [
            ("Default (model decides)", ""),
            ("Minimal (fastest)", "minimal"),
            ("Low", "low"),
            ("Medium", "medium"),
            ("High", "high"),
            ("Extra high", "xhigh"),
        ]
        self.openai_reasoning = QComboBox()
        for label, val in reasoning_options:
            self.openai_reasoning.addItem(label, val)
        saved_effort = settings.get("openai_reasoning_effort", "")
        for i, (_, val) in enumerate(reasoning_options):
            if val == saved_effort:
                self.openai_reasoning.setCurrentIndex(i)
                break
        oai_form.addRow("Reasoning Effort", self.openai_reasoning)

        self.openai_voice_speed = QLineEdit(str(settings.get("openai_voice_speed", "") or ""))
        self.openai_voice_speed.setPlaceholderText("1.0 (0.25 slow – 1.5 fast)")
        oai_form.addRow("Voice Speed", self.openai_voice_speed)

        self.openai_interrupt_response = QCheckBox("Allow interrupting AI response")
        self.openai_interrupt_response.setChecked(
            bool(settings.get("openai_interrupt_response", True))
        )
        oai_form.addRow("", self.openai_interrupt_response)

        self.openai_create_response = QCheckBox("Auto-respond on turn end")
        self.openai_create_response.setChecked(bool(settings.get("openai_create_response", True)))
        oai_form.addRow("", self.openai_create_response)

        self._openai_advanced = AdvancedSection(
            "Advanced realtime settings", self._openai_adv_container
        )
        rt_layout.addWidget(self._openai_advanced)

    def _add_deepgram_advanced(self, settings: dict, rt_layout: QVBoxLayout) -> None:
        """Deepgram Advanced (collapsible)."""
        self._deepgram_adv_container = QWidget()
        dg_form = QFormLayout(self._deepgram_adv_container)
        dg_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        dg_form.setSpacing(10)
        dg_form.setLabelAlignment(Qt.AlignLeft)
        dg_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        dg_form.setContentsMargins(20, 16, 20, 16)

        self.deepgram_think_provider = QComboBox()
        for label, val in DEEPGRAM_THINK_PROVIDERS:
            self.deepgram_think_provider.addItem(label, val)
        saved_think = settings.get("deepgram_agent_think_provider", "open_ai")
        for i, (_, val) in enumerate(DEEPGRAM_THINK_PROVIDERS):
            if val == saved_think:
                self.deepgram_think_provider.setCurrentIndex(i)
                break
        dg_form.addRow("LLM Provider", self.deepgram_think_provider)

        self.deepgram_think_model = QComboBox()
        self.deepgram_think_model.setEditable(True)
        self._populate_think_models(
            saved_think, settings.get("deepgram_agent_think_model", "") or ""
        )
        dg_form.addRow("LLM Model", self.deepgram_think_model)

        self.deepgram_listen_model = QComboBox()
        self.deepgram_listen_model.setEditable(True)
        self.deepgram_listen_model.addItems(DEEPGRAM_LISTEN_MODELS)
        self.deepgram_listen_model.setCurrentText(
            settings.get("deepgram_agent_listen_model", "") or ""
        )
        listen_edit = self.deepgram_listen_model.lineEdit()
        if listen_edit is not None:
            listen_edit.setPlaceholderText("auto — nova-3, or nova-2 for a specific language")
        dg_form.addRow("STT Model", self.deepgram_listen_model)

        self.deepgram_speak_provider = QComboBox()
        for label, val in [
            ("Deepgram Aura", ""),
            ("ElevenLabs", "eleven_labs"),
            ("OpenAI", "open_ai"),
        ]:
            self.deepgram_speak_provider.addItem(label, val)
        saved_speak = settings.get("deepgram_agent_speak_provider", "")
        for i in range(self.deepgram_speak_provider.count()):
            if self.deepgram_speak_provider.itemData(i) == saved_speak:
                self.deepgram_speak_provider.setCurrentIndex(i)
                break
        self.deepgram_speak_provider.setToolTip(
            "TTS vendor Deepgram hosts for the speak stage. ElevenLabs and OpenAI "
            "use the API keys in Providers & keys."
        )
        dg_form.addRow("TTS Provider", self.deepgram_speak_provider)

        self.deepgram_speak_model = QLineEdit(settings.get("deepgram_agent_speak_model", "") or "")
        self.deepgram_speak_model.setPlaceholderText("vendor default — eleven_turbo_v2_5 / tts-1")
        dg_form.addRow("TTS Model", self.deepgram_speak_model)

        self.deepgram_speak_voice = QLineEdit(settings.get("deepgram_agent_speak_voice", "") or "")
        self.deepgram_speak_voice.setPlaceholderText("ElevenLabs voice ID · OpenAI voice (alloy)")
        dg_form.addRow("TTS Voice", self.deepgram_speak_voice)

        self.deepgram_speak_speed = QLineEdit(settings.get("deepgram_agent_speak_speed", "") or "")
        self.deepgram_speak_speed.setPlaceholderText("1.0 (0.7 slow – 1.5 fast, Aura voices)")
        dg_form.addRow("Voice Speed", self.deepgram_speak_speed)

        self.deepgram_greeting = QLineEdit(settings.get("deepgram_agent_greeting", "") or "")
        self.deepgram_greeting.setPlaceholderText("Optional line spoken when the session opens")
        dg_form.addRow("Greeting", self.deepgram_greeting)

        self._deepgram_advanced = AdvancedSection(
            "Advanced realtime settings", self._deepgram_adv_container
        )
        rt_layout.addWidget(self._deepgram_advanced)

    def _add_xai_advanced(self, settings: dict, rt_layout: QVBoxLayout) -> None:
        """xAI Advanced (collapsible)."""
        self._xai_adv_container = QWidget()
        xai_form = QFormLayout(self._xai_adv_container)
        xai_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        xai_form.setSpacing(10)
        xai_form.setLabelAlignment(Qt.AlignLeft)
        xai_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        xai_form.setContentsMargins(20, 16, 20, 16)

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

        self._xai_advanced = AdvancedSection("Advanced realtime settings", self._xai_adv_container)
        rt_layout.addWidget(self._xai_advanced)

    def _map_provider_widgets(self) -> None:
        """Which widgets show for which provider.

        Advanced containers are handled separately: they stay collapsed on a
        provider switch.
        """
        self._provider_widgets: dict[str, list[QWidget]] = {
            "gemini": [
                self._gemini_model_label,
                self.gemini_model,
                self._gemini_voice_label,
                self.gemini_voice,
                self._gemini_advanced,
            ],
            "openai": [
                self._openai_model_label,
                self.openai_model,
                self._openai_voice_label,
                self.openai_voice,
                self._openai_advanced,
            ],
            "deepgram": [
                self._deepgram_voice_label,
                self.deepgram_voice,
                self._deepgram_language_label,
                self.deepgram_language,
                self.deepgram_half_duplex,
                self._deepgram_advanced,
            ],
            "elevenlabs": [
                self._elevenlabs_agent_label,
                self.elevenlabs_agent_id,
                self._elevenlabs_note,
            ],
            "xai": [
                self._xai_model_label,
                self.xai_model,
                self._xai_voice_label,
                self.xai_voice,
                self._xai_advanced,
            ],
            "openai_live": [
                *self._gpt_live.widgets,
            ],
        }
        self._advanced = {
            "gemini": self._gemini_advanced,
            "openai": self._openai_advanced,
            "deepgram": self._deepgram_advanced,
            "xai": self._xai_advanced,
        }

    # -- Visibility handlers --

    def _on_provider_changed(self, index: int) -> None:
        current = PROVIDERS[index][1]
        for widgets in self._provider_widgets.values():
            for w in widgets:
                w.setVisible(False)
        for w in self._provider_widgets.get(current, []):
            w.setVisible(True)
        for name, section in self._advanced.items():
            if name != current:
                section.set_expanded(False)
        self._on_openai_turn_detection_changed(self.openai_turn_detection.currentIndex())

    def _on_think_provider_changed(self, _index: int) -> None:
        # The old model id belongs to the previous vendor \u2014 start clean.
        self._populate_think_models(self.deepgram_think_provider.currentData() or "open_ai", "")

    def _populate_think_models(self, think_provider: str, current: str) -> None:
        """Reload the think-model suggestions for *think_provider*."""
        combo = self.deepgram_think_model
        combo.clear()
        combo.addItems(chat_model_options(DEEPGRAM_THINK_CATALOGS.get(think_provider, "")))
        combo.setCurrentText(current)
        if think_provider == "open_ai":
            placeholder = "gpt-4o-mini (default)"
        else:
            placeholder = "required \u2014 pick or type a model"
        line_edit = combo.lineEdit()
        if line_edit is not None:  # None only for non-editable combos
            line_edit.setPlaceholderText(placeholder)

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
            "deepgram_agent_voice": self.deepgram_voice.currentText().strip(),
            "deepgram_agent_think_provider": (
                self.deepgram_think_provider.currentData() or "open_ai"
            ),
            "deepgram_agent_think_model": self.deepgram_think_model.currentText().strip(),
            "deepgram_agent_listen_model": self.deepgram_listen_model.currentText().strip(),
            "deepgram_agent_listen_language": self.deepgram_language.currentData() or "",
            "deepgram_agent_half_duplex": self.deepgram_half_duplex.isChecked(),
            "deepgram_agent_speak_provider": self.deepgram_speak_provider.currentData() or "",
            "deepgram_agent_speak_model": self.deepgram_speak_model.text().strip(),
            "deepgram_agent_speak_voice": self.deepgram_speak_voice.text().strip(),
            "deepgram_agent_speak_speed": self.deepgram_speak_speed.text().strip(),
            "deepgram_agent_greeting": self.deepgram_greeting.text().strip(),
            "elevenlabs_agent_id": self.elevenlabs_agent_id.text().strip(),
            "xai_model": self.xai_model.currentText().strip(),
            "xai_voice": self.xai_voice.currentData() or "",
            "xai_vad_threshold": self.xai_vad_threshold.text().strip(),
            "xai_silence_duration_ms": self.xai_silence_duration.text().strip(),
            "xai_prefix_padding_ms": self.xai_prefix_padding.text().strip(),
            "model": self.gemini_model.currentText().strip(),
            "openai_model": self.openai_model.currentText().strip(),
            "voice": self.gemini_voice.currentData() or "",
            "openai_voice": self.openai_voice.currentData() or "",
            "gemini_language": self.gemini_language.currentData() or "",
            "gemini_no_interruption": self.gemini_no_interruption.isChecked(),
            "gemini_affective_dialog": self.gemini_affective_dialog.isChecked(),
            "gemini_proactive_audio": self.gemini_proactive_audio.isChecked(),
            "gemini_start_sensitivity": self.gemini_start_sensitivity.currentData() or "",
            "gemini_end_sensitivity": self.gemini_end_sensitivity.currentData() or "",
            "gemini_silence_duration_ms": self.gemini_silence_duration.text().strip(),
            **self._gemini_generation.get_settings(),
            **self._gpt_live.get_settings(),
            "openai_turn_detection": (self.openai_turn_detection.currentData() or "server_vad"),
            "openai_eagerness": self.openai_eagerness.text().strip(),
            "openai_vad_threshold": self.openai_vad_threshold.text().strip(),
            "openai_silence_duration_ms": self.openai_silence_duration.text().strip(),
            "openai_prefix_padding_ms": self.openai_prefix_padding.text().strip(),
            "openai_interrupt_response": self.openai_interrupt_response.isChecked(),
            "openai_create_response": self.openai_create_response.isChecked(),
            "openai_reasoning_effort": self.openai_reasoning.currentData() or "",
            "openai_voice_speed": self.openai_voice_speed.text().strip(),
        }
