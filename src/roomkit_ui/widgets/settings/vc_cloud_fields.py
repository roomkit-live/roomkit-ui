"""Voice Channel cloud provider fields: cloud LLM, cloud STT, cloud TTS, Gradium Advanced."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

VC_ANTHROPIC_MODELS = [
    ("Opus 4.6", "claude-opus-4-6"),
    ("Sonnet 4.5", "claude-sonnet-4-5-20250929"),
    ("Sonnet 4", "claude-sonnet-4-20250514"),
    ("Haiku 4.5", "claude-haiku-4-5-20251001"),
]
VC_OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini"]
VC_GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash"]

DEEPGRAM_MODELS = [
    ("Nova-3", "nova-3"),
    ("Nova-2", "nova-2"),
    ("Nova", "nova"),
    ("Enhanced", "enhanced"),
    ("Base", "base"),
]

GRADIUM_REGIONS = [
    ("US", "us"),
    ("EU", "eu"),
]

ELEVENLABS_MODELS = [
    ("v3 (expressive, 70+ langs)", "eleven_v3"),
    ("Multilingual v2 (lifelike)", "eleven_multilingual_v2"),
    ("Flash v2.5 (~75ms, multilingual)", "eleven_flash_v2_5"),
    ("Flash v2 (~75ms, EN only)", "eleven_flash_v2"),
    ("Turbo v2.5 (~250ms, multilingual)", "eleven_turbo_v2_5"),
    ("Turbo v2 (~250ms, EN only)", "eleven_turbo_v2"),
]


class VCCloudFields:
    """Cloud provider fields added to a parent QFormLayout in phases.

    Call ``add_llm_fields``, ``add_stt_fields``, ``add_tts_fields`` at the
    correct insertion points in the form.  ``add_gradium_advanced`` goes on
    the VC section's QVBoxLayout (outside the form grid).
    """

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    # ── LLM ──

    def add_llm_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Anthropic
        self.anthropic_api_key = QLineEdit(s.get("anthropic_api_key", ""))
        self.anthropic_api_key.setEchoMode(QLineEdit.Password)
        self.anthropic_api_key.setPlaceholderText("Enter your Anthropic API key")
        self._anthropic_key_label = QLabel("API Key")
        form.addRow(self._anthropic_key_label, self.anthropic_api_key)

        self.vc_anthropic_model = QComboBox()
        for label, model_id in VC_ANTHROPIC_MODELS:
            self.vc_anthropic_model.addItem(label, model_id)
        cur = s.get("vc_anthropic_model", VC_ANTHROPIC_MODELS[0][1])
        for i, (_, mid) in enumerate(VC_ANTHROPIC_MODELS):
            if mid == cur:
                self.vc_anthropic_model.setCurrentIndex(i)
                break
        self._vc_anthropic_model_label = QLabel("Model")
        form.addRow(self._vc_anthropic_model_label, self.vc_anthropic_model)

        # OpenAI
        self.vc_openai_api_key = QLineEdit(s.get("openai_api_key", ""))
        self.vc_openai_api_key.setEchoMode(QLineEdit.Password)
        self.vc_openai_api_key.setPlaceholderText("Enter your OpenAI API key")
        self._vc_openai_key_label = QLabel("API Key")
        form.addRow(self._vc_openai_key_label, self.vc_openai_api_key)

        self.vc_openai_model = QComboBox()
        self.vc_openai_model.setEditable(True)
        self.vc_openai_model.addItems(VC_OPENAI_MODELS)
        cur = s.get("vc_openai_model", VC_OPENAI_MODELS[0])
        oidx = self.vc_openai_model.findText(cur)
        if oidx >= 0:
            self.vc_openai_model.setCurrentIndex(oidx)
        else:
            self.vc_openai_model.setCurrentText(cur)
        self._vc_openai_model_label = QLabel("Model")
        form.addRow(self._vc_openai_model_label, self.vc_openai_model)

        # Gemini
        self.vc_gemini_api_key = QLineEdit(s.get("api_key", ""))
        self.vc_gemini_api_key.setEchoMode(QLineEdit.Password)
        self.vc_gemini_api_key.setPlaceholderText("Enter your Google API key")
        self._vc_gemini_key_label = QLabel("API Key")
        form.addRow(self._vc_gemini_key_label, self.vc_gemini_api_key)

        self.vc_gemini_model = QComboBox()
        self.vc_gemini_model.setEditable(True)
        self.vc_gemini_model.addItems(VC_GEMINI_MODELS)
        cur = s.get("vc_gemini_model", VC_GEMINI_MODELS[0])
        gidx = self.vc_gemini_model.findText(cur)
        if gidx >= 0:
            self.vc_gemini_model.setCurrentIndex(gidx)
        else:
            self.vc_gemini_model.setCurrentText(cur)
        self._vc_gemini_model_label = QLabel("Model")
        form.addRow(self._vc_gemini_model_label, self.vc_gemini_model)

    # ── STT ──

    def add_stt_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Gradium shared key + region
        self.gradium_api_key = QLineEdit(s.get("gradium_api_key", ""))
        self.gradium_api_key.setEchoMode(QLineEdit.Password)
        self.gradium_api_key.setPlaceholderText("Enter your Gradium API key")
        self._gradium_key_label = QLabel("Gradium Key")
        form.addRow(self._gradium_key_label, self.gradium_api_key)

        self.gradium_region = QComboBox()
        for label, _val in GRADIUM_REGIONS:
            self.gradium_region.addItem(label, _val)
        saved_region = s.get("gradium_region", "us")
        for i, (_, val) in enumerate(GRADIUM_REGIONS):
            if val == saved_region:
                self.gradium_region.setCurrentIndex(i)
                break
        self._gradium_region_label = QLabel("Gradium Region")
        form.addRow(self._gradium_region_label, self.gradium_region)

        # Deepgram
        self.deepgram_api_key = QLineEdit(s.get("deepgram_api_key", ""))
        self.deepgram_api_key.setEchoMode(QLineEdit.Password)
        self.deepgram_api_key.setPlaceholderText("Enter your Deepgram API key")
        self._deepgram_key_label = QLabel("Deepgram Key")
        form.addRow(self._deepgram_key_label, self.deepgram_api_key)

        self.deepgram_model = QComboBox()
        for label, val in DEEPGRAM_MODELS:
            self.deepgram_model.addItem(label, val)
        saved_dg_model = s.get("deepgram_model", "nova-3")
        for i, (_, val) in enumerate(DEEPGRAM_MODELS):
            if val == saved_dg_model:
                self.deepgram_model.setCurrentIndex(i)
                break
        self._deepgram_model_label = QLabel("Deepgram Model")
        form.addRow(self._deepgram_model_label, self.deepgram_model)

    # ── TTS ──

    def add_tts_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Gradium voice
        self.vc_gradium_voice = QLineEdit(s.get("vc_gradium_voice", ""))
        self.vc_gradium_voice.setPlaceholderText("Voice ID (leave empty for default)")
        self._vc_gradium_voice_label = QLabel("Gradium Voice")
        form.addRow(self._vc_gradium_voice_label, self.vc_gradium_voice)

        # ElevenLabs
        self.elevenlabs_api_key = QLineEdit(s.get("elevenlabs_api_key", ""))
        self.elevenlabs_api_key.setEchoMode(QLineEdit.Password)
        self.elevenlabs_api_key.setPlaceholderText("Enter your ElevenLabs API key")
        self._elevenlabs_key_label = QLabel("ElevenLabs Key")
        form.addRow(self._elevenlabs_key_label, self.elevenlabs_api_key)

        self.elevenlabs_voice_id = QLineEdit(s.get("elevenlabs_voice_id", ""))
        self.elevenlabs_voice_id.setPlaceholderText("Rachel (default)")
        self._elevenlabs_voice_label = QLabel("Voice ID")
        form.addRow(self._elevenlabs_voice_label, self.elevenlabs_voice_id)

        self.elevenlabs_model = QComboBox()
        for label, val in ELEVENLABS_MODELS:
            self.elevenlabs_model.addItem(label, val)
        saved_el_model = s.get("elevenlabs_model", "")
        for i, (_, val) in enumerate(ELEVENLABS_MODELS):
            if val == saved_el_model:
                self.elevenlabs_model.setCurrentIndex(i)
                break
        self._elevenlabs_model_label = QLabel("Model")
        form.addRow(self._elevenlabs_model_label, self.elevenlabs_model)

    # ── Gradium Advanced (collapsible) ──

    def add_gradium_advanced(self, vc_layout: QVBoxLayout) -> None:
        s = self._settings
        c = colors()

        self._gradium_adv_toggle = QPushButton("\u25b8 Gradium Advanced")
        self._gradium_adv_toggle.setFlat(True)
        self._gradium_adv_toggle.setCursor(Qt.PointingHandCursor)
        self._gradium_adv_toggle.setStyleSheet(
            "text-align: left; font-size: 12px; font-weight: 600;"
            f" color: {c['TEXT_SECONDARY']}; background: transparent; border: none;"
            " padding: 2px 0;"
        )
        self._gradium_adv_toggle.clicked.connect(self._toggle_gradium_advanced)
        vc_layout.addWidget(self._gradium_adv_toggle)

        self._gradium_adv_container = QWidget()
        gadv_form = QFormLayout(self._gradium_adv_container)
        gadv_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        gadv_form.setSpacing(10)
        gadv_form.setLabelAlignment(Qt.AlignRight)

        # STT sub-section
        stt_label = QLabel("STT")
        stt_label.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            " background: transparent;"
        )
        gadv_form.addRow("", stt_label)

        self.gradium_stt_model = QLineEdit(s.get("gradium_stt_model", ""))
        self.gradium_stt_model.setPlaceholderText("default")
        gadv_form.addRow("Model", self.gradium_stt_model)

        gradium_lang_options = [
            ("Auto", ""),
            ("English", "en"),
            ("French", "fr"),
            ("German", "de"),
            ("Spanish", "es"),
            ("Portuguese", "pt"),
        ]
        self.gradium_language = QComboBox()
        for label, val in gradium_lang_options:
            self.gradium_language.addItem(label, val)
        saved_glang = s.get("gradium_language", "")
        for i, (_, val) in enumerate(gradium_lang_options):
            if val == saved_glang:
                self.gradium_language.setCurrentIndex(i)
                break
        gadv_form.addRow("Language", self.gradium_language)

        self.gradium_stt_delay = QComboBox()
        delay_options = [
            ("Auto (7)", ""),
            ("8", "8"),
            ("10", "10"),
            ("12", "12"),
            ("14", "14"),
            ("16", "16"),
            ("20", "20"),
            ("24", "24"),
            ("36", "36"),
            ("48", "48"),
        ]
        for label, val in delay_options:
            self.gradium_stt_delay.addItem(label, val)
        saved_delay = str(s.get("gradium_stt_delay", "") or "")
        for i, (_, val) in enumerate(delay_options):
            if val == saved_delay:
                self.gradium_stt_delay.setCurrentIndex(i)
                break
        gadv_form.addRow("Delay (frames)", self.gradium_stt_delay)

        self.gradium_stt_temperature = QLineEdit(str(s.get("gradium_stt_temperature", "") or ""))
        self.gradium_stt_temperature.setPlaceholderText("0 (0 = greedy \u2026 1 = diverse)")
        gadv_form.addRow("Temperature", self.gradium_stt_temperature)

        self.gradium_vad_threshold = QLineEdit(str(s.get("gradium_vad_threshold", "") or ""))
        self.gradium_vad_threshold.setPlaceholderText("0.9 (0 \u2013 1)")
        gadv_form.addRow("VAD Threshold", self.gradium_vad_threshold)

        self.gradium_vad_steps = QLineEdit(str(s.get("gradium_vad_steps", "") or ""))
        self.gradium_vad_steps.setPlaceholderText("10 (steps \u00d7 80ms = 800ms)")
        gadv_form.addRow("VAD Steps", self.gradium_vad_steps)

        # TTS sub-section
        tts_label = QLabel("TTS")
        tts_label.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            " background: transparent;"
        )
        gadv_form.addRow("", tts_label)

        self.gradium_tts_model = QLineEdit(s.get("gradium_tts_model", ""))
        self.gradium_tts_model.setPlaceholderText("default")
        gadv_form.addRow("Model", self.gradium_tts_model)

        self.gradium_speed = QLineEdit(str(s.get("gradium_speed", "") or ""))
        self.gradium_speed.setPlaceholderText("0 (\u22124 faster \u2026 +4 slower)")
        gadv_form.addRow("Speed", self.gradium_speed)

        self.gradium_temperature = QLineEdit(str(s.get("gradium_temperature", "") or ""))
        self.gradium_temperature.setPlaceholderText("0.7 (0 \u2013 1.4)")
        gadv_form.addRow("Temperature", self.gradium_temperature)

        self.gradium_cfg_coef = QLineEdit(str(s.get("gradium_cfg_coef", "") or ""))
        self.gradium_cfg_coef.setPlaceholderText("2.0 (1 \u2013 4)")
        gadv_form.addRow("Voice Similarity", self.gradium_cfg_coef)

        self.gradium_rewrite_rules = QLineEdit(s.get("gradium_rewrite_rules", ""))
        self.gradium_rewrite_rules.setPlaceholderText("en, fr, de, es, pt or custom rules")
        gadv_form.addRow("Rewrite Rules", self.gradium_rewrite_rules)

        self._gradium_adv_container.hide()
        vc_layout.addWidget(self._gradium_adv_container)

    # -- Visibility --

    def update_llm_visibility(self, provider: str) -> None:
        self._anthropic_key_label.setVisible(provider == "anthropic")
        self.anthropic_api_key.setVisible(provider == "anthropic")
        self._vc_anthropic_model_label.setVisible(provider == "anthropic")
        self.vc_anthropic_model.setVisible(provider == "anthropic")
        self._vc_openai_key_label.setVisible(provider == "openai")
        self.vc_openai_api_key.setVisible(provider == "openai")
        self._vc_openai_model_label.setVisible(provider == "openai")
        self.vc_openai_model.setVisible(provider == "openai")
        self._vc_gemini_key_label.setVisible(provider == "gemini")
        self.vc_gemini_api_key.setVisible(provider == "gemini")
        self._vc_gemini_model_label.setVisible(provider == "gemini")
        self.vc_gemini_model.setVisible(provider == "gemini")

    def update_stt_visibility(self, provider: str) -> None:
        is_deepgram = provider == "deepgram"
        self._deepgram_key_label.setVisible(is_deepgram)
        self.deepgram_api_key.setVisible(is_deepgram)
        self._deepgram_model_label.setVisible(is_deepgram)
        self.deepgram_model.setVisible(is_deepgram)

    def update_tts_visibility(self, provider: str) -> None:
        is_gradium = provider == "gradium"
        is_elevenlabs = provider == "elevenlabs"
        self._vc_gradium_voice_label.setVisible(is_gradium)
        self.vc_gradium_voice.setVisible(is_gradium)
        self._elevenlabs_key_label.setVisible(is_elevenlabs)
        self.elevenlabs_api_key.setVisible(is_elevenlabs)
        self._elevenlabs_voice_label.setVisible(is_elevenlabs)
        self.elevenlabs_voice_id.setVisible(is_elevenlabs)
        self._elevenlabs_model_label.setVisible(is_elevenlabs)
        self.elevenlabs_model.setVisible(is_elevenlabs)

    def update_gradium_visibility(self, stt_provider: str, tts_provider: str) -> None:
        needs_gradium = stt_provider == "gradium" or tts_provider == "gradium"
        self._gradium_key_label.setVisible(needs_gradium)
        self.gradium_api_key.setVisible(needs_gradium)
        self._gradium_region_label.setVisible(needs_gradium)
        self.gradium_region.setVisible(needs_gradium)
        self._gradium_adv_toggle.setVisible(needs_gradium)
        if not needs_gradium:
            self._gradium_adv_container.hide()

    def _toggle_gradium_advanced(self) -> None:
        visible = not self._gradium_adv_container.isVisible()
        self._gradium_adv_container.setVisible(visible)
        arrow = "\u25be" if visible else "\u25b8"
        self._gradium_adv_toggle.setText(f"{arrow} Gradium Advanced")

    # -- Settings --

    def get_settings(self) -> dict:
        return {
            "anthropic_api_key": self.anthropic_api_key.text().strip(),
            "_vc_openai_key": self.vc_openai_api_key.text().strip(),
            "_vc_gemini_key": self.vc_gemini_api_key.text().strip(),
            "vc_anthropic_model": (
                self.vc_anthropic_model.currentData() or VC_ANTHROPIC_MODELS[0][1]
            ),
            "vc_openai_model": self.vc_openai_model.currentText().strip(),
            "vc_gemini_model": self.vc_gemini_model.currentText().strip(),
            "gradium_api_key": self.gradium_api_key.text().strip(),
            "gradium_region": self.gradium_region.currentData() or "us",
            "_vc_deepgram_key": self.deepgram_api_key.text().strip(),
            "deepgram_model": self.deepgram_model.currentData() or "nova-3",
            "vc_gradium_voice": self.vc_gradium_voice.text().strip(),
            "elevenlabs_api_key": self.elevenlabs_api_key.text().strip(),
            "elevenlabs_voice_id": self.elevenlabs_voice_id.text().strip(),
            "elevenlabs_model": self.elevenlabs_model.currentData() or "",
            "gradium_language": self.gradium_language.currentData() or "",
            "gradium_stt_model": self.gradium_stt_model.text().strip(),
            "gradium_stt_delay": self.gradium_stt_delay.currentData() or "",
            "gradium_stt_temperature": self.gradium_stt_temperature.text().strip(),
            "gradium_vad_threshold": self.gradium_vad_threshold.text().strip(),
            "gradium_vad_steps": self.gradium_vad_steps.text().strip(),
            "gradium_tts_model": self.gradium_tts_model.text().strip(),
            "gradium_speed": self.gradium_speed.text().strip(),
            "gradium_temperature": self.gradium_temperature.text().strip(),
            "gradium_cfg_coef": self.gradium_cfg_coef.text().strip(),
            "gradium_rewrite_rules": self.gradium_rewrite_rules.text().strip(),
        }
