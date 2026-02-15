"""Realtime (speech-to-speech) provider settings: Gemini and OpenAI."""

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
    "gpt-4o-realtime-preview",
]
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class RealtimeSection(QWidget):
    """Realtime speech-to-speech provider settings (Gemini / OpenAI)."""

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

        # Wire signals
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        self.openai_turn_detection.currentIndexChanged.connect(
            self._on_openai_turn_detection_changed
        )

        # Initial state
        self._on_provider_changed(self.provider.currentIndex())

    # -- Visibility handlers --

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
        self._openai_adv_toggle.setVisible(not is_gemini)
        if not is_gemini:
            self._gemini_adv_container.hide()
        else:
            self._openai_adv_container.hide()

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
