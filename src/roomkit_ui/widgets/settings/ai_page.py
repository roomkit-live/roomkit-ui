"""AI settings: conversation mode, provider, API key, model, voice, prompt."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QStackedWidget,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.realtime_section import RealtimeSection
from roomkit_ui.widgets.settings.vc_cloud_fields import VCCloudFields
from roomkit_ui.widgets.settings.vc_local_fields import VCLocalFields

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

VC_STT_PROVIDERS = [
    ("Local (sherpa-onnx)", "local"),
    ("Gradium", "gradium"),
    ("Deepgram", "deepgram"),
]

VC_TTS_PROVIDERS = [
    ("Piper (sherpa-onnx)", "piper"),
    ("Qwen3-TTS (voice clone)", "qwen3"),
    ("NeuTTS (voice clone)", "neutts"),
    ("Gradium", "gradium"),
    ("ElevenLabs", "elevenlabs"),
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

        # ── Realtime section (self-contained widget) ──
        self._realtime = RealtimeSection(settings)
        layout.addWidget(self._realtime)

        # ── Voice Channel section ──
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

        # Sub-module instances
        self._local = VCLocalFields(self, settings)
        self._cloud = VCCloudFields(settings)

        # -- Horizontal tab bar --
        self._vc_tab_bar = QTabBar()
        self._vc_tab_bar.addTab("STT")
        self._vc_tab_bar.addTab("LLM")
        self._vc_tab_bar.addTab("TTS")
        self._vc_tab_bar.setExpanding(False)
        self._vc_tab_bar.setDocumentMode(True)
        self._vc_tab_bar.setStyleSheet(f"""
            QTabBar::tab {{
                padding: 5px 16px;
                margin-right: 4px;
                border-radius: 6px;
                color: {c["TEXT_SECONDARY"]};
                background: transparent;
            }}
            QTabBar::tab:selected {{
                background: {c["BG_TERTIARY"]};
                color: {c["TEXT_PRIMARY"]};
            }}
        """)
        vc_layout.addWidget(self._vc_tab_bar)

        self._vc_stack = QStackedWidget()

        # -- Page 0: STT --
        stt_page = QWidget()
        stt_form = QFormLayout(stt_page)
        stt_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        stt_form.setSpacing(10)
        stt_form.setLabelAlignment(Qt.AlignRight)

        self.vc_stt_provider = QComboBox()
        for label, _value in VC_STT_PROVIDERS:
            self.vc_stt_provider.addItem(label)
        current_stt_prov = settings.get("vc_stt_provider", "local")
        for i, (_, val) in enumerate(VC_STT_PROVIDERS):
            if val == current_stt_prov:
                self.vc_stt_provider.setCurrentIndex(i)
                break
        stt_form.addRow("Provider", self.vc_stt_provider)
        self._local.add_stt_fields(stt_form)
        self._cloud.add_stt_fields(stt_form)

        self._vc_stack.addWidget(stt_page)

        # -- Page 1: LLM --
        llm_page = QWidget()
        llm_form = QFormLayout(llm_page)
        llm_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        llm_form.setSpacing(10)
        llm_form.setLabelAlignment(Qt.AlignRight)

        self.vc_provider = QComboBox()
        for label, _value in VC_LLM_PROVIDERS:
            self.vc_provider.addItem(label)
        current_vc_provider = settings.get("vc_llm_provider", "anthropic")
        for i, (_, val) in enumerate(VC_LLM_PROVIDERS):
            if val == current_vc_provider:
                self.vc_provider.setCurrentIndex(i)
                break
        llm_form.addRow("Provider", self.vc_provider)
        self._cloud.add_llm_fields(llm_form)
        self._local.add_llm_fields(llm_form)

        self._vc_stack.addWidget(llm_page)

        # -- Page 2: TTS --
        tts_page = QWidget()
        tts_form = QFormLayout(tts_page)
        tts_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        tts_form.setSpacing(10)
        tts_form.setLabelAlignment(Qt.AlignRight)

        self.vc_tts_provider = QComboBox()
        for label, _value in VC_TTS_PROVIDERS:
            self.vc_tts_provider.addItem(label)
        current_tts_prov = settings.get("vc_tts_provider", "piper")
        for i, (_, val) in enumerate(VC_TTS_PROVIDERS):
            if val == current_tts_prov:
                self.vc_tts_provider.setCurrentIndex(i)
                break
        tts_form.addRow("Provider", self.vc_tts_provider)
        self._local.add_tts_fields(tts_form)
        self._cloud.add_tts_fields(tts_form)

        self.vc_interruption = QCheckBox("Allow barge-in (interrupt TTS by speaking)")
        self.vc_interruption.setChecked(bool(settings.get("vc_interruption", False)))
        tts_form.addRow("", self.vc_interruption)

        self._vc_stack.addWidget(tts_page)

        self._vc_tab_bar.currentChanged.connect(self._vc_stack.setCurrentIndex)
        vc_layout.addWidget(self._vc_stack)

        # Gradium Advanced collapsible (below tabs, visible when Gradium selected)
        self._cloud.add_gradium_advanced(vc_layout)

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
        self.vc_provider.currentIndexChanged.connect(self._on_vc_provider_changed)
        self.vc_stt_provider.currentIndexChanged.connect(self._on_vc_stt_provider_changed)
        self.vc_tts_provider.currentIndexChanged.connect(self._on_vc_tts_provider_changed)

        # Initial state
        self._on_mode_changed(self.mode_combo.currentIndex())
        self._on_vc_provider_changed(self.vc_provider.currentIndex())
        self._on_vc_stt_provider_changed(self.vc_stt_provider.currentIndex())
        self._on_vc_tts_provider_changed(self.vc_tts_provider.currentIndex())

    # -- Mode / provider change handlers --

    def _on_mode_changed(self, index: int) -> None:
        is_realtime = CONVERSATION_MODES[index][1] == "realtime"
        self._realtime.setVisible(is_realtime)
        self._vc_section.setVisible(not is_realtime)
        if not is_realtime:
            self.refresh_vc_model_combos()

    def _on_vc_provider_changed(self, index: int) -> None:
        prov = VC_LLM_PROVIDERS[index][1]
        self._local.update_llm_visibility(prov)
        self._cloud.update_llm_visibility(prov)

    def _on_vc_stt_provider_changed(self, index: int) -> None:
        prov = VC_STT_PROVIDERS[index][1]
        self._local.update_stt_visibility(prov)
        self._cloud.update_stt_visibility(prov)
        self._cloud.update_gradium_visibility(prov, self._current_tts_provider())

    def _on_vc_tts_provider_changed(self, index: int) -> None:
        prov = VC_TTS_PROVIDERS[index][1]
        self._local.update_tts_visibility(prov)
        self._cloud.update_tts_visibility(prov)
        self._cloud.update_gradium_visibility(self._current_stt_provider(), prov)

    def _current_stt_provider(self) -> str:
        return VC_STT_PROVIDERS[self.vc_stt_provider.currentIndex()][1]

    def _current_tts_provider(self) -> str:
        return VC_TTS_PROVIDERS[self.vc_tts_provider.currentIndex()][1]

    # -- Public API (panel.py compatibility) --

    def populate_attitude_combo(self, all_names: list[str]) -> None:
        self.attitude_combo.blockSignals(True)
        self.attitude_combo.clear()
        self.attitude_combo.addItem("None")
        for name in all_names:
            self.attitude_combo.addItem(name)
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
        self._local.refresh_model_combos(self._local._vc_saved_stt, self._local._vc_saved_tts)
        # Re-apply provider visibility (controls model combo vs no-models label)
        self._on_vc_stt_provider_changed(self.vc_stt_provider.currentIndex())
        self._on_vc_tts_provider_changed(self.vc_tts_provider.currentIndex())

    def get_settings(self) -> dict:
        return {
            "conversation_mode": CONVERSATION_MODES[self.mode_combo.currentIndex()][1],
            **self._realtime.get_settings(),
            "vc_llm_provider": VC_LLM_PROVIDERS[self.vc_provider.currentIndex()][1],
            "vc_stt_provider": VC_STT_PROVIDERS[self.vc_stt_provider.currentIndex()][1],
            "vc_interruption": self.vc_interruption.isChecked(),
            "vc_tts_provider": VC_TTS_PROVIDERS[self.vc_tts_provider.currentIndex()][1],
            **self._local.get_settings(),
            **self._cloud.get_settings(),
            "system_prompt": self.prompt.toPlainText().strip(),
            "selected_attitude": self.selected_attitude_name(),
        }
