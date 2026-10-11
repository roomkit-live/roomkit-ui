"""Voice Channel cloud provider fields: cloud LLM, cloud STT, cloud TTS, Gradium Advanced."""

from __future__ import annotations

import importlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.widgets.settings.controls import AdvancedSection, SettingsForm
from roomkit_ui.widgets.settings.vc_azure_fields import AzureSpeechFields
from roomkit_ui.widgets.settings.vc_meta_fields import MetaSTTFields

_ANTHROPIC_CATALOG = "roomkit.providers.anthropic.models"
_OPENAI_CATALOG = "roomkit.providers.openai.models"
_GEMINI_CATALOG = "roomkit.providers.gemini.models"

# A voice-channel turn always declares tools (the built-ins at least) and
# roomkit's OpenAI provider speaks Chat Completions: it refuses every turn on
# a model its catalog tags Responses-only, and every turn with tools on one
# tagged chat_tools_refused.  Listing them would offer a model that never
# answers.
_OPENAI_REFUSED_TAGS = frozenset({"responses_only", "chat_tools_refused"})


def _catalog_models(
    module_name: str, *, refused_tags: frozenset[str] = frozenset()
) -> list[tuple[str, str]]:
    """``(display name, model id)`` for the current models of a roomkit chat catalog.

    The catalogs are pure data (``MODELS: list[ModelInfo]``), no vendor SDK.
    Deprecated models are left out — a saved one is still kept, see
    ``_select_model``.  A dated snapshot and its dateless alias share a name;
    the first listed stands for both.  Empty if the catalog cannot be read.
    """
    try:
        models = importlib.import_module(module_name).MODELS
    except Exception:
        return []
    seen: set[str] = set()
    options: list[tuple[str, str]] = []
    for model in models:
        if model.deprecated or refused_tags & set(model.capabilities):
            continue
        label = model.display_name or model.id
        if label not in seen:
            seen.add(label)
            options.append((label, model.id))
    return options


def _deprecated_label(module_name: str, model_id: str) -> str | None:
    """``"<name> (deprecated)"`` when the catalog flags *model_id*, else None."""
    try:
        models = importlib.import_module(module_name).MODELS
    except Exception:
        return None
    for model in models:
        if model.id == model_id and model.deprecated:
            return f"{model.display_name or model.id} (deprecated)"
    return None


def _catalog_tags(module_name: str, model_id: str) -> set[str]:
    """The capability tags a roomkit catalog gives *model_id*; empty if unknown."""
    try:
        models = importlib.import_module(module_name).MODELS
    except Exception:
        return set()
    for model in models:
        if model.id == model_id:
            return set(model.capabilities)
    return set()


# Values: engine_vc_helpers.CLAUDE_THINKING / CLAUDE_EFFORTS / GEMINI_THINKING_LEVELS.
CLAUDE_THINKING_OPTIONS = [("Model default", ""), ("On", "on"), ("Off (answers sooner)", "off")]
CLAUDE_EFFORT_OPTIONS = [
    ("Model default", ""),
    ("Low (fastest)", "low"),
    ("Medium", "medium"),
    ("High", "high"),
    ("Extra high", "xhigh"),
    ("Max (slowest)", "max"),
]
GEMINI_THINKING_OPTIONS = [
    ("Model default", ""),
    ("Off (fastest)", "none"),
    ("Minimal", "minimal"),
    ("Low", "low"),
    ("Medium", "medium"),
    ("High", "high"),
]

_CLAUDE_REASONING_HINT = (
    "Thinking and a higher effort make Claude slower to start speaking. With thinking "
    "off, the effort still sets how much it says and how readily it uses tools."
)
_GEMINI_REASONING_HINT = "A lower level makes Gemini start speaking sooner."

# What roomkit sends a Claude its catalog tags so (RFC §6.7, roomkit 0.98).
_CLAUDE_CAVEATS = (
    ("effort_refused", "This model takes no effort setting."),
    ("reasoning_floor_low", "This model always thinks: Off runs it at low effort."),
    ("thinking_off_between_tools", "Off still lets it think between tool calls."),
    ("thinking_off_effort_high", "With thinking off, Extra high and Max run as High."),
)


def claude_reasoning_note(model_id: str) -> str:
    """The Claude hint, with what this model does differently (roomkit's catalog)."""
    tags = _catalog_tags(_ANTHROPIC_CATALOG, model_id)
    caveats = [caveat for tag, caveat in _CLAUDE_CAVEATS if tag in tags]
    return " ".join([_CLAUDE_REASONING_HINT, *caveats])


def gemini_reasoning_note(model_id: str) -> str:
    """The Gemini hint, with what this model does differently (roomkit's catalog)."""
    tags = _catalog_tags(_GEMINI_CATALOG, model_id)
    if not tags:
        return _GEMINI_REASONING_HINT
    if "thinking_level" not in tags:
        caveat = "This model takes no level: only Off changes how it thinks."
    elif "thinking_required" in tags:
        caveat = "This model always thinks: Off runs it at its lowest level."
    elif "thinking_level_minimal" not in tags:
        caveat = "Minimal runs as Low on this model."
    else:
        return _GEMINI_REASONING_HINT
    return f"{_GEMINI_REASONING_HINT} {caveat}"


def _choice_combo(options: list[tuple[str, str]], saved: str) -> QComboBox:
    combo = QComboBox()
    for label, value in options:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(combo.findData(saved), 0))
    return combo


VC_ANTHROPIC_MODELS = _catalog_models(_ANTHROPIC_CATALOG) or [
    ("Claude Sonnet 5.5", "claude-sonnet-5-5")
]
VC_OPENAI_MODELS = _catalog_models(_OPENAI_CATALOG, refused_tags=_OPENAI_REFUSED_TAGS)
VC_GEMINI_MODELS = _catalog_models(_GEMINI_CATALOG)

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


def _select_model(combo: QComboBox, model_id: str, label: str | None = None) -> None:
    """Select *model_id* in a fixed model dropdown.

    A saved id the lineup does not carry (a retired model, a hand-pinned
    one) is inserted at the top, shown as *label* when given, and stays
    selected — falling back to the first item would silently change what
    the next session runs.
    """
    if not model_id:
        return
    idx = combo.findData(model_id)
    if idx < 0:
        combo.insertItem(0, label or model_id, model_id)
        idx = 0
    combo.setCurrentIndex(idx)


def _populate_editable_models(
    combo: QComboBox, options: list[tuple[str, str]], current: str
) -> None:
    """Fill an editable model combo: ids as text, the catalog name as tooltip.

    The text doubles as free input (any id the API takes), so it must be the
    id itself; a saved id the lineup lacks is shown as it was saved.
    """
    for label, model_id in options:
        combo.addItem(model_id, model_id)
        combo.setItemData(combo.count() - 1, label, Qt.ToolTipRole)
    idx = combo.findText(current)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    else:
        combo.setCurrentText(current)


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

    # ── LLM ──

    def add_llm_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Anthropic
        self.vc_anthropic_model = QComboBox()
        for label, model_id in VC_ANTHROPIC_MODELS:
            self.vc_anthropic_model.addItem(label, model_id)
        saved_anthropic = s.get("vc_anthropic_model", "")
        _select_model(
            self.vc_anthropic_model,
            saved_anthropic,
            _deprecated_label(_ANTHROPIC_CATALOG, saved_anthropic),
        )
        self._vc_anthropic_model_label = QLabel("Model")
        form.addRow(self._vc_anthropic_model_label, self.vc_anthropic_model)

        # OpenAI
        self.vc_openai_model = QComboBox()
        self.vc_openai_model.setEditable(True)
        _populate_editable_models(
            self.vc_openai_model, VC_OPENAI_MODELS, s.get("vc_openai_model", "gpt-4o")
        )
        self._vc_openai_model_label = QLabel("Model")
        form.addRow(self._vc_openai_model_label, self.vc_openai_model)

        # Gemini
        self.vc_gemini_model = QComboBox()
        self.vc_gemini_model.setEditable(True)
        _populate_editable_models(
            self.vc_gemini_model, VC_GEMINI_MODELS, s.get("vc_gemini_model", "gemini-3.8-flash")
        )
        self._vc_gemini_model_label = QLabel("Model")
        form.addRow(self._vc_gemini_model_label, self.vc_gemini_model)

        self._add_reasoning_fields(form)

    def _add_reasoning_fields(self, form: QFormLayout) -> None:
        """Thinking and effort for Claude, the thinking level for Gemini.

        One block under the model, so search has one place to land.  OpenAI
        has none: see ``engine_vc_helpers.reasoning_options``.
        """
        s = self._settings
        self.vc_reasoning = QWidget()
        rows = SettingsForm(self.vc_reasoning)

        self.vc_anthropic_thinking = _choice_combo(
            CLAUDE_THINKING_OPTIONS, s.get("vc_anthropic_thinking", "")
        )
        self._vc_anthropic_thinking_label = QLabel("Thinking")
        rows.addRow(self._vc_anthropic_thinking_label, self.vc_anthropic_thinking)
        self.vc_anthropic_effort = _choice_combo(
            CLAUDE_EFFORT_OPTIONS, s.get("vc_anthropic_effort", "")
        )
        self._vc_anthropic_effort_label = QLabel("Effort")
        rows.addRow(self._vc_anthropic_effort_label, self.vc_anthropic_effort)

        self.vc_gemini_thinking = _choice_combo(
            GEMINI_THINKING_OPTIONS, s.get("vc_gemini_thinking", "")
        )
        self._vc_gemini_thinking_label = QLabel("Thinking level")
        rows.addRow(self._vc_gemini_thinking_label, self.vc_gemini_thinking)

        self._vc_reasoning_note = QLabel()
        self._vc_reasoning_note.setWordWrap(True)
        self._vc_reasoning_note.setObjectName("settingsHint")
        rows.addRow(self._vc_reasoning_note)
        form.addRow(self.vc_reasoning)

        self._llm_provider = ""
        self.vc_anthropic_model.currentIndexChanged.connect(self._update_reasoning_note)
        self.vc_gemini_model.currentTextChanged.connect(self._update_reasoning_note)

    def _update_reasoning_note(self) -> None:
        if self._llm_provider == "anthropic":
            model = self.vc_anthropic_model.currentData() or ""
            self._vc_reasoning_note.setText(claude_reasoning_note(model))
            # Disabled, not reset: the pick returns with a model that takes it.
            takes_effort = "effort_refused" not in _catalog_tags(_ANTHROPIC_CATALOG, model)
            self.vc_anthropic_effort.setEnabled(takes_effort)
        elif self._llm_provider == "gemini":
            model = self.vc_gemini_model.currentText().strip()
            self._vc_reasoning_note.setText(gemini_reasoning_note(model))

    # ── STT ──

    def add_stt_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Deepgram
        self.deepgram_model = QComboBox()
        for label, val in DEEPGRAM_MODELS:
            self.deepgram_model.addItem(label, val)
        _select_model(self.deepgram_model, s.get("deepgram_model", "nova-3"))
        self._deepgram_model_label = QLabel("Deepgram Model")
        form.addRow(self._deepgram_model_label, self.deepgram_model)

        self.azure.add_stt_rows(form)
        self.meta.add_stt_rows(form)

    # ── TTS ──

    def add_tts_fields(self, form: QFormLayout) -> None:
        s = self._settings
        self.azure.add_tts_rows(form)

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
        _select_model(self.elevenlabs_model, s.get("elevenlabs_model", ""))
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

    def update_llm_visibility(self, provider: str) -> None:
        self._vc_anthropic_model_label.setVisible(provider == "anthropic")
        self.vc_anthropic_model.setVisible(provider == "anthropic")
        self._vc_openai_model_label.setVisible(provider == "openai")
        self.vc_openai_model.setVisible(provider == "openai")
        self._vc_gemini_model_label.setVisible(provider == "gemini")
        self.vc_gemini_model.setVisible(provider == "gemini")
        self._llm_provider = provider
        self.vc_reasoning.setVisible(provider in ("anthropic", "gemini"))
        for widget in (
            self._vc_anthropic_thinking_label,
            self.vc_anthropic_thinking,
            self._vc_anthropic_effort_label,
            self.vc_anthropic_effort,
        ):
            widget.setVisible(provider == "anthropic")
        self._vc_gemini_thinking_label.setVisible(provider == "gemini")
        self.vc_gemini_thinking.setVisible(provider == "gemini")
        self._update_reasoning_note()

    def update_stt_visibility(self, provider: str) -> None:
        self.azure.update_stt_visibility(provider)
        self.meta.update_stt_visibility(provider)
        is_deepgram = provider == "deepgram"
        self._deepgram_model_label.setVisible(is_deepgram)
        self.deepgram_model.setVisible(is_deepgram)

    def update_tts_visibility(self, provider: str) -> None:
        self.azure.update_tts_visibility(provider)
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

    def update_gradium_visibility(self, stt_provider: str, tts_provider: str) -> None:
        needs_gradium = stt_provider == "gradium" or tts_provider == "gradium"
        self.gradium_advanced.setVisible(needs_gradium)
        if not needs_gradium:
            self.gradium_advanced.set_expanded(False)

    # -- Settings --

    def get_settings(self) -> dict:
        return {
            "vc_anthropic_model": (
                self.vc_anthropic_model.currentData() or VC_ANTHROPIC_MODELS[0][1]
            ),
            "vc_openai_model": self.vc_openai_model.currentText().strip(),
            "vc_gemini_model": self.vc_gemini_model.currentText().strip(),
            "vc_anthropic_thinking": self.vc_anthropic_thinking.currentData() or "",
            "vc_anthropic_effort": self.vc_anthropic_effort.currentData() or "",
            "vc_gemini_thinking": self.vc_gemini_thinking.currentData() or "",
            "gradium_region": self.gradium_region.currentData() or "us",
            "deepgram_model": self.deepgram_model.currentData() or "nova-3",
            "vc_gradium_voice": self.vc_gradium_voice.text().strip(),
            "elevenlabs_voice_id": self.elevenlabs_voice_id.text().strip(),
            "elevenlabs_model": self.elevenlabs_model.currentData() or "",
            "elevenlabs_stream_input": self.elevenlabs_stream_input.isChecked(),
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
        }
