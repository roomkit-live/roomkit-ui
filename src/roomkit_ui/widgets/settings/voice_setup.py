"""Conversation voice setup: mode, providers, models and speaking behavior."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.features import (
    AI_PROVIDER_FEATURES,
    STT_PROVIDER_FEATURES,
    TTS_PROVIDER_FEATURES,
)
from roomkit_ui.widgets.settings.choice_cards import ChoiceCards
from roomkit_ui.widgets.settings.controls import SettingsTabs, label
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.pipeline_summary import PipelineSummary
from roomkit_ui.widgets.settings.realtime_section import RealtimeSection
from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage
from roomkit_ui.widgets.settings.vc_cloud_fields import VCCloudFields
from roomkit_ui.widgets.settings.vc_local_fields import VCLocalFields

VC_LLM_PROVIDERS = [
    ("Anthropic", "anthropic"),
    ("OpenAI", "openai"),
    ("Google Gemini", "gemini"),
    ("Local (vLLM / Ollama)", "local"),
    ("llama.cpp (local GGUF)", "llamacpp"),
]

VC_STT_PROVIDERS: list[tuple[str, str]] = [
    ("Local (sherpa-onnx)", "local"),
    ("Gradium", "gradium"),
    ("Deepgram", "deepgram"),
    ("Azure MAI-Transcribe", "azure_mai"),
    ("Meta Muse Voice Transcribe", "meta"),
    ("Google Gemini", "gemini"),
]

VC_TTS_PROVIDERS: list[tuple[str, str]] = [
    ("Piper (sherpa-onnx)", "piper"),
    ("Qwen3-TTS (voice clone)", "qwen3"),
    ("NeuTTS (voice clone)", "neutts"),
    ("Gradium", "gradium"),
    ("ElevenLabs", "elevenlabs"),
    ("Pocket TTS (local, voice clone)", "pocket"),
    ("Azure MAI-Voice", "azure"),
    ("Google Gemini", "gemini"),
]

# Barge-in: how the user's speech may cut the assistant off (build_interruption).
VC_INTERRUPTION_MODES: list[tuple[str, str]] = [
    ("Off — the assistant finishes speaking", "off"),
    ("Any speech interrupts", "immediate"),
    ("Words only — ignores “ok”, “mm” and noise", "semantic"),
]

_INTERRUPTION_HINT = (
    "Words only lets acknowledgements (“ok”, “mm-hmm”, "
    "“d’accord”, “merci”) through and stops for anything else. "
    "It needs an STT that hears words while you speak (Deepgram, Gradium, Meta Muse, "
    "Gemini, a streaming local model): a Whisper-type local model only gives them once you "
    "stop, so with one any speech that lasts stops the assistant."
)


class VoiceSetup(QWidget):
    """Conversation voice setup: mode, providers, models and speaking behavior."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(28)

        mode_heading = QVBoxLayout()
        mode_heading.setSpacing(6)
        mode_heading.addWidget(label("Conversation mode", "settingsSectionTitle"))
        mode_heading.addWidget(
            label("Choose the experience. Fine-tune the details below.", "settingsHint")
        )
        mode_heading.addSpacing(10)
        self.mode_picker = ChoiceCards(
            [
                (
                    "realtime",
                    "Realtime",
                    "A single provider handles a fluid, live voice conversation.",
                    "waveform",
                ),
                (
                    "voice_channel",
                    "Voice Channel",
                    "Choose separate models for transcription, reasoning, and speech.",
                    "layers",
                ),
            ],
            settings.get("conversation_mode", "realtime"),
        )
        mode_heading.addWidget(self.mode_picker)
        layout.addLayout(mode_heading)

        # ── Realtime section (self-contained widget) ──
        self._realtime = RealtimeSection(settings)
        layout.addWidget(self._realtime)

        # ── Voice Channel section ──
        self._vc_section = QWidget()
        vc_layout = QVBoxLayout(self._vc_section)
        vc_layout.setContentsMargins(0, 0, 0, 0)
        vc_layout.setSpacing(20)
        vc_layout.addWidget(label("Build your voice pipeline", "settingsSectionTitle"))
        self.pipeline = PipelineSummary()
        vc_layout.addWidget(self.pipeline)

        # Sub-module instances
        self._local = VCLocalFields(self, settings)
        self._cloud = VCCloudFields(settings)

        # -- Page 0: STT --
        stt_page = QFrame()
        stt_page.setObjectName("settingsCard")
        stt_form = QFormLayout(stt_page)
        stt_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        stt_form.setSpacing(10)
        stt_form.setLabelAlignment(Qt.AlignLeft)
        stt_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        stt_form.setContentsMargins(20, 20, 20, 20)

        self.vc_stt_provider = QComboBox()
        populate_provider_combo(self.vc_stt_provider, VC_STT_PROVIDERS, STT_PROVIDER_FEATURES)
        current_stt_prov = settings.get("vc_stt_provider", "local")
        for i, (_, val) in enumerate(VC_STT_PROVIDERS):
            if val == current_stt_prov:
                self.vc_stt_provider.setCurrentIndex(i)
                break
        stt_form.addRow("Provider", self.vc_stt_provider)
        stt_form.addRow(
            "", offer_install(self.vc_stt_provider, VC_STT_PROVIDERS, STT_PROVIDER_FEATURES)
        )
        self._local.add_stt_fields(stt_form)
        self._cloud.add_stt_fields(stt_form)

        # Barge-in is decided on the microphone side, and what it can do
        # depends on the STT (Words only needs one that hears words live).
        self._add_interruption_fields(stt_form, settings)

        # -- Page 1: LLM --
        llm_page = QFrame()
        llm_page.setObjectName("settingsCard")
        llm_form = QFormLayout(llm_page)
        llm_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        llm_form.setSpacing(10)
        llm_form.setLabelAlignment(Qt.AlignLeft)
        llm_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        llm_form.setContentsMargins(20, 20, 20, 20)

        self.vc_provider = QComboBox()
        populate_provider_combo(self.vc_provider, VC_LLM_PROVIDERS, AI_PROVIDER_FEATURES)
        current_vc_provider = settings.get("vc_llm_provider", "anthropic")
        for i, (_, val) in enumerate(VC_LLM_PROVIDERS):
            if val == current_vc_provider:
                self.vc_provider.setCurrentIndex(i)
                break
        llm_form.addRow("Provider", self.vc_provider)
        llm_form.addRow(
            "", offer_install(self.vc_provider, VC_LLM_PROVIDERS, AI_PROVIDER_FEATURES)
        )
        self._cloud.add_llm_fields(llm_form)
        self._local.add_llm_fields(llm_form)

        # -- Page 2: TTS --
        tts_page = QFrame()
        tts_page.setObjectName("settingsCard")
        tts_form = QFormLayout(tts_page)
        tts_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        tts_form.setSpacing(10)
        tts_form.setLabelAlignment(Qt.AlignLeft)
        tts_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        tts_form.setContentsMargins(20, 20, 20, 20)

        self.vc_tts_provider = QComboBox()
        populate_provider_combo(self.vc_tts_provider, VC_TTS_PROVIDERS, TTS_PROVIDER_FEATURES)
        current_tts_prov = settings.get("vc_tts_provider", "piper")
        for i, (_, val) in enumerate(VC_TTS_PROVIDERS):
            if val == current_tts_prov:
                self.vc_tts_provider.setCurrentIndex(i)
                break
        tts_form.addRow("Provider", self.vc_tts_provider)
        tts_form.addRow(
            "", offer_install(self.vc_tts_provider, VC_TTS_PROVIDERS, TTS_PROVIDER_FEATURES)
        )
        self._local.add_tts_fields(tts_form)
        self._cloud.add_tts_fields(tts_form)

        # -- Page 3: Agent (turn-taking) --
        self._agent = VCAgentPage(settings)

        self.pipeline_tabs = SettingsTabs(
            [
                ("Listen · STT", stt_page),
                ("Think · LLM", llm_page),
                ("Speak · TTS", tts_page),
                ("Agent", self._agent),
            ]
        )
        vc_layout.addWidget(self.pipeline_tabs)

        # Gradium Advanced collapsible (below tabs, visible when Gradium selected)
        self._cloud.add_gradium_advanced(vc_layout)

        layout.addWidget(self._vc_section)

        # Wire signals
        self.mode_picker.value_changed.connect(self._on_mode_changed)
        self.vc_provider.currentIndexChanged.connect(self._on_vc_provider_changed)
        self.vc_stt_provider.currentIndexChanged.connect(self._on_vc_stt_provider_changed)
        self.vc_tts_provider.currentIndexChanged.connect(self._on_vc_tts_provider_changed)

        self._local.vc_stt_model.currentIndexChanged.connect(
            lambda: self._local.update_stt_visibility(self._current_stt_provider())
        )
        self._local.vc_tts_model.currentIndexChanged.connect(
            lambda: self._local.update_tts_visibility(self._current_tts_provider())
        )

        # Initial state
        self._on_mode_changed(self.mode_picker.value())
        self._on_vc_provider_changed(self.vc_provider.currentIndex())
        self._on_vc_stt_provider_changed(self.vc_stt_provider.currentIndex())
        self._on_vc_tts_provider_changed(self.vc_tts_provider.currentIndex())

        for field in [*self.findChildren(QComboBox), *self.findChildren(QLineEdit)]:
            field.setProperty("settingsFormField", True)

    def _add_interruption_fields(self, form: QFormLayout, settings: dict) -> None:
        self.vc_interruption_mode = QComboBox()
        for title, value in VC_INTERRUPTION_MODES:
            self.vc_interruption_mode.addItem(title, value)
        idx = self.vc_interruption_mode.findData(settings.get("vc_interruption_mode", "off"))
        self.vc_interruption_mode.setCurrentIndex(max(idx, 0))
        form.addRow("Barge-in", self.vc_interruption_mode)

        hint = QLabel(_INTERRUPTION_HINT)
        hint.setWordWrap(True)
        hint.setObjectName("settingsHint")
        form.addRow("", hint)

    # -- Mode / provider change handlers --

    def _on_mode_changed(self, mode: str) -> None:
        is_realtime = mode == "realtime"
        self._realtime.setVisible(is_realtime)
        self._vc_section.setVisible(not is_realtime)
        # Realtime mode too: get_settings() reads these combos, and left
        # empty they saved the voice-channel model choice as "".
        self.refresh_vc_model_combos()

    def _on_vc_provider_changed(self, index: int) -> None:
        prov = VC_LLM_PROVIDERS[index][1]
        self._local.update_llm_visibility(prov)
        self._cloud.update_llm_visibility(prov)
        self._update_pipeline_summary()

    def _on_vc_stt_provider_changed(self, index: int) -> None:
        prov = VC_STT_PROVIDERS[index][1]
        self._local.update_stt_visibility(prov)
        self._cloud.update_stt_visibility(prov)
        self._cloud.update_gradium_visibility(prov, self._current_tts_provider())
        self._update_pipeline_summary()

    def _on_vc_tts_provider_changed(self, index: int) -> None:
        prov = VC_TTS_PROVIDERS[index][1]
        self._local.update_tts_visibility(prov)
        self._cloud.update_tts_visibility(prov)
        self._cloud.update_gradium_visibility(self._current_stt_provider(), prov)
        self._update_pipeline_summary()

    def _update_pipeline_summary(self) -> None:
        stt = {"local": "Local", "azure_mai": "Azure MAI", "meta": "Meta Muse", "gemini": "Gemini"}
        llm = {"local": "Local", "llamacpp": "llama.cpp", "gemini": "Gemini"}
        tts = {
            "piper": "Piper",
            "qwen3": "Qwen3-TTS",
            "neutts": "NeuTTS",
            "pocket": "Pocket TTS",
            "azure": "Azure MAI",
            "gemini": "Gemini",
        }
        providers = (
            (self.vc_stt_provider, VC_STT_PROVIDERS, stt),
            (self.vc_provider, VC_LLM_PROVIDERS, llm),
            (self.vc_tts_provider, VC_TTS_PROVIDERS, tts),
        )
        names = []
        for combo, entries, short_names in providers:
            title, value = entries[combo.currentIndex()]
            names.append(short_names.get(value, title))
        self.pipeline.set_providers(*names)

    def _current_stt_provider(self) -> str:
        idx: int = self.vc_stt_provider.currentIndex()
        return VC_STT_PROVIDERS[idx][1]

    def _current_tts_provider(self) -> str:
        idx: int = self.vc_tts_provider.currentIndex()
        return VC_TTS_PROVIDERS[idx][1]

    # -- Models and settings --

    def refresh_vc_model_combos(self) -> None:
        # The saved models seed the first fill only.  Refills (to list models
        # downloaded meanwhile) keep the user's current pick.
        local = self._local
        local.refresh_model_combos(
            local.vc_stt_model.currentData() or local._vc_saved_stt,
            local.vc_tts_model.currentData() or local._vc_saved_tts,
        )
        # Re-apply provider visibility (controls model combo vs no-models label)
        self._on_vc_stt_provider_changed(self.vc_stt_provider.currentIndex())
        self._on_vc_tts_provider_changed(self.vc_tts_provider.currentIndex())

    def get_settings(self) -> dict:
        return {
            "conversation_mode": self.mode_picker.value(),
            **self._realtime.get_settings(),
            "vc_llm_provider": VC_LLM_PROVIDERS[self.vc_provider.currentIndex()][1],
            "vc_stt_provider": VC_STT_PROVIDERS[self.vc_stt_provider.currentIndex()][1],
            "vc_interruption_mode": self.vc_interruption_mode.currentData() or "off",
            "vc_tts_provider": VC_TTS_PROVIDERS[self.vc_tts_provider.currentIndex()][1],
            **self._local.get_settings(),
            **self._cloud.get_settings(),
            **self._agent.get_settings(),
        }
