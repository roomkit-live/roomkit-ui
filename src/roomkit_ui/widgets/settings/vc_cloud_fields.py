"""Voice Channel cloud provider fields: cloud STT, cloud TTS, audio tags, Gradium
Advanced.

A cloud LLM's fields are ``llm_fields.LLMFields``, as in every place a model is
chosen."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from roomkit_ui.audio_tags import performed_tags
from roomkit_ui.widgets.settings.controls import AdvancedSection, SettingsForm
from roomkit_ui.widgets.settings.model_combos import select_model
from roomkit_ui.widgets.settings.vc_azure_fields import AzureSpeechFields
from roomkit_ui.widgets.settings.vc_google_fields import GeminiSpeechFields
from roomkit_ui.widgets.settings.vc_meta_fields import MetaSTTFields

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
    ("v4 (expressive, streams)", "eleven_v4"),
    ("v4 Turbo (expressive, conversational latency)", "eleven_v4_turbo"),
    ("v3 (expressive, 70+ langs, no streaming)", "eleven_v3"),
    ("Multilingual v2 (lifelike)", "eleven_multilingual_v2"),
    ("Flash v2.5 (~75ms, multilingual)", "eleven_flash_v2_5"),
    ("Flash v2 (~75ms, EN only)", "eleven_flash_v2"),
    ("Turbo v2.5 (~250ms, multilingual)", "eleven_turbo_v2_5"),
    ("Turbo v2 (~250ms, EN only)", "eleven_turbo_v2"),
]


def audio_tags_hint(tags: tuple[str, ...]) -> str:
    """What the audio-tag option does with this voice, or why it cannot."""
    if not tags:
        return (
            "Google Gemini voices and ElevenLabs v3 or v4 perform audio tags. "
            "This voice would read them aloud."
        )
    return (
        f"The assistant varies its delivery with {', '.join(tags)} where they fit. "
        "The voice performs them and the chat shows them."
    )


class VCCloudFields:
    """Cloud provider fields added to a parent QFormLayout in phases.

    Call ``add_llm_fields``, ``add_stt_fields``, ``add_tts_fields`` at the
    correct insertion points in the form.  ``add_gradium_advanced`` goes on
    the VC section's QVBoxLayout (outside the form grid).
    """

    def __init__(self, settings: dict) -> None:
        self._settings = settings
        self.azure = AzureSpeechFields(settings)
        self.meta = MetaSTTFields(settings)
        self.google = GeminiSpeechFields(settings)
        self._tts_provider = ""

    # ── STT ──

    def add_stt_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Deepgram
        self.deepgram_model = QComboBox()
        for label, val in DEEPGRAM_MODELS:
            self.deepgram_model.addItem(label, val)
        select_model(self.deepgram_model, s.get("deepgram_model", "nova-3"))
        self._deepgram_model_label = QLabel("Deepgram Model")
        form.addRow(self._deepgram_model_label, self.deepgram_model)

        self.azure.add_stt_rows(form)
        self.meta.add_stt_rows(form)
        self.google.add_stt_rows(form)

    # ── TTS ──

    def add_tts_fields(self, form: QFormLayout) -> None:
        s = self._settings
        self.azure.add_tts_rows(form)
        self.google.add_tts_rows(form)

        # Gradium voice
        self.vc_gradium_voice = QLineEdit(s.get("vc_gradium_voice", ""))
        self.vc_gradium_voice.setPlaceholderText("Voice ID (leave empty for default)")
        self._vc_gradium_voice_label = QLabel("Gradium Voice")
        form.addRow(self._vc_gradium_voice_label, self.vc_gradium_voice)

        # ElevenLabs
        self.elevenlabs_voice_id = QLineEdit(s.get("elevenlabs_voice_id", ""))
        self.elevenlabs_voice_id.setPlaceholderText("Rachel (default)")
        self._elevenlabs_voice_label = QLabel("Voice ID")
        form.addRow(self._elevenlabs_voice_label, self.elevenlabs_voice_id)

        self.elevenlabs_model = QComboBox()
        for label, val in ELEVENLABS_MODELS:
            self.elevenlabs_model.addItem(label, val)
        # Empty means eleven_v4, the first item.
        select_model(self.elevenlabs_model, s.get("elevenlabs_model", ""))
        self._elevenlabs_model_label = QLabel("Model")
        form.addRow(self._elevenlabs_model_label, self.elevenlabs_model)

        self.elevenlabs_stream_input = QCheckBox("Stream text to ElevenLabs (lower latency)")
        self.elevenlabs_stream_input.setChecked(bool(s.get("elevenlabs_stream_input", True)))
        self.elevenlabs_stream_input.setToolTip(
            "Each sentence is spoken as soon as the model writes it, instead of once the "
            "whole reply is written. v3 has no streaming: it always waits for the reply."
        )
        self._elevenlabs_stream_label = QLabel("")
        form.addRow(self._elevenlabs_stream_label, self.elevenlabs_stream_input)

        self._add_audio_tag_fields(form)

    def _add_audio_tag_fields(self, form: QFormLayout) -> None:
        """Hand the model the audio tags the voice performs (audio_tags.py).

        Shown for every voice, so it can be found; enabled where the voice
        performs tags.  Disabled, it keeps its value for when one does.
        """
        self.vc_tts_audio_tags = QCheckBox("Let the assistant direct its voice")
        self.vc_tts_audio_tags.setChecked(bool(self._settings.get("vc_tts_audio_tags", False)))
        self.vc_tts_audio_tags.setToolTip(
            "The model writes tags such as [whispers] or [laughs] into its replies, "
            "and the voice acts them out: more varied delivery."
        )
        form.addRow("Audio tags", self.vc_tts_audio_tags)
        self._audio_tags_note = QLabel()
        self._audio_tags_note.setWordWrap(True)
        self._audio_tags_note.setObjectName("settingsHint")
        form.addRow("", self._audio_tags_note)
        self.elevenlabs_model.currentIndexChanged.connect(self._update_audio_tags)

    def _update_audio_tags(self) -> None:
        tags = performed_tags(
            {
                "vc_tts_provider": self._tts_provider,
                "elevenlabs_model": self.elevenlabs_model.currentData() or "",
            }
        )
        self.vc_tts_audio_tags.setEnabled(bool(tags))
        self._audio_tags_note.setText(audio_tags_hint(tags))

    # ── Gradium Advanced (collapsible) ──

    def add_gradium_advanced(self, vc_layout: QVBoxLayout) -> None:
        s = self._settings

        content = QFrame()
        content.setObjectName("settingsCard")
        gadv_form = SettingsForm(content)
        gadv_form.setContentsMargins(20, 16, 20, 16)
        self.gradium_advanced = AdvancedSection("Gradium advanced settings", content)
        vc_layout.addWidget(self.gradium_advanced)

        # Region shared by Gradium STT and TTS

        self.gradium_region = QComboBox()
        for label, _val in GRADIUM_REGIONS:
            self.gradium_region.addItem(label, _val)
        saved_region = s.get("gradium_region", "us")
        for i, (_, val) in enumerate(GRADIUM_REGIONS):
            if val == saved_region:
                self.gradium_region.setCurrentIndex(i)
                break
        self._gradium_region_label = QLabel("Gradium Region")
        gadv_form.addRow(self._gradium_region_label, self.gradium_region)

        # STT sub-section
        stt_label = QLabel("Transcription")
        stt_label.setObjectName("settingsSectionTitle")
        gadv_form.addRow(stt_label)

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
        tts_label = QLabel("Speech")
        tts_label.setObjectName("settingsSectionTitle")
        gadv_form.addRow(tts_label)

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

    # -- Visibility --

    def update_stt_visibility(self, provider: str) -> None:
        self.azure.update_stt_visibility(provider)
        self.meta.update_stt_visibility(provider)
        self.google.update_stt_visibility(provider)
        is_deepgram = provider == "deepgram"
        self._deepgram_model_label.setVisible(is_deepgram)
        self.deepgram_model.setVisible(is_deepgram)

    def update_tts_visibility(self, provider: str) -> None:
        self.azure.update_tts_visibility(provider)
        self.google.update_tts_visibility(provider)
        is_gradium = provider == "gradium"
        is_elevenlabs = provider == "elevenlabs"
        self._vc_gradium_voice_label.setVisible(is_gradium)
        self.vc_gradium_voice.setVisible(is_gradium)
        self._elevenlabs_voice_label.setVisible(is_elevenlabs)
        self.elevenlabs_voice_id.setVisible(is_elevenlabs)
        self._elevenlabs_model_label.setVisible(is_elevenlabs)
        self.elevenlabs_model.setVisible(is_elevenlabs)
        self._elevenlabs_stream_label.setVisible(is_elevenlabs)
        self.elevenlabs_stream_input.setVisible(is_elevenlabs)
        self._tts_provider = provider
        self._update_audio_tags()

    def update_gradium_visibility(self, stt_provider: str, tts_provider: str) -> None:
        needs_gradium = stt_provider == "gradium" or tts_provider == "gradium"
        self.gradium_advanced.setVisible(needs_gradium)
        if not needs_gradium:
            self.gradium_advanced.set_expanded(False)

    # -- Settings --

    def get_settings(self) -> dict:
        return {
            "gradium_region": self.gradium_region.currentData() or "us",
            "deepgram_model": self.deepgram_model.currentData() or "nova-3",
            "vc_gradium_voice": self.vc_gradium_voice.text().strip(),
            "elevenlabs_voice_id": self.elevenlabs_voice_id.text().strip(),
            "elevenlabs_model": self.elevenlabs_model.currentData() or "",
            "elevenlabs_stream_input": self.elevenlabs_stream_input.isChecked(),
            "vc_tts_audio_tags": self.vc_tts_audio_tags.isChecked(),
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
            **self.azure.get_settings(),
            **self.meta.get_settings(),
            **self.google.get_settings(),
        }
