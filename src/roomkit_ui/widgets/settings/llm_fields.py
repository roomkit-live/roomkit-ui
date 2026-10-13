"""The rows that choose an LLM, the same in every place one is chosen.

Think · LLM (the conversation), the Agent tab's background tasks and the Text
chat tab each pick a provider, its model, its reasoning (Claude's thinking and
effort, Gemini's thinking level) and a local server's or a GGUF's own fields,
with one component, :class:`LLMFields`, so no place offers what another does
not. Each saves under its role's keys (``providers.LLM_ROLES``): Think · LLM's
``vc_*``, the tasks' ``vc_background_*``, typed messages' ``text_*``; a role
other than the conversation also offers Think · LLM's model, and an empty field
of its own takes Think · LLM's (``providers.llm_settings``), save its reasoning,
where empty means the model's default.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
    QWidget,
)

from roomkit_ui.features import AI_PROVIDER_FEATURES
from roomkit_ui.providers import LLM_PROVIDERS, LLM_ROLES
from roomkit_ui.widgets.settings.controls import SettingsForm
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.model_combos import (
    choice_combo,
    populate_editable_models,
    select_model,
)

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
    ``select_model``.  A dated snapshot and its dateless alias share a name;
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
    "Thinking and a higher effort make Claude slower to answer. With thinking off, "
    "the effort still sets how much it says and how readily it uses tools."
)
_GEMINI_REASONING_HINT = "A lower level makes Gemini answer sooner."

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


VC_ANTHROPIC_MODELS = _catalog_models(_ANTHROPIC_CATALOG) or [
    ("Claude Sonnet 5.5", "claude-sonnet-5-5")
]
VC_OPENAI_MODELS = _catalog_models(_OPENAI_CATALOG, refused_tags=_OPENAI_REFUSED_TAGS)
VC_GEMINI_MODELS = _catalog_models(_GEMINI_CATALOG)


# A cloud provider's model before the user picks one: its factory's default
# (Claude's is the catalog's first).
_DEFAULT_MODELS = {"openai": "gpt-4o", "gemini": "gemini-3.8-flash"}


def cloud_model_combo(provider: str, model_id: str) -> QComboBox:
    """Think · LLM's model dropdown for a cloud *provider*, on *model_id*:
    Claude's lineup from its catalog; OpenAI's and Gemini's editable, any id
    their API takes."""
    combo = QComboBox()
    if provider == "anthropic":
        for label, catalog_id in VC_ANTHROPIC_MODELS:
            combo.addItem(label, catalog_id)
        select_model(combo, model_id, _deprecated_label(_ANTHROPIC_CATALOG, model_id))
        return combo
    combo.setEditable(True)
    lineup = VC_OPENAI_MODELS if provider == "openai" else VC_GEMINI_MODELS
    populate_editable_models(combo, lineup, model_id or _DEFAULT_MODELS[provider])
    return combo


def cloud_model(combo: QComboBox) -> str:
    """The model id a ``cloud_model_combo`` is on."""
    if combo.isEditable():
        return combo.currentText().strip()
    return combo.currentData() or VC_ANTHROPIC_MODELS[0][1]


# What a local model's thinking switch does, by role and by provider.
CONVERSATION_THINKING_HINTS = {
    "local": (
        "Off, a reasoning model (Qwen3, DeepSeek-R1) answers at once instead of thinking "
        "for seconds before a word is spoken. A model that always reasons (Qwen3 "
        "Thinking-2507) then says its reasoning aloud: turn this on for it."
    ),
    "llamacpp": (
        "Off, a reasoning model (Qwen3, Qwen3.5) answers at once. On, it thinks before "
        "each reply, and seconds may pass before a word is spoken. Its thinking is never "
        "read aloud."
    ),
}

_DEFAULT_LOCAL_URL = "http://localhost:11434/v1"
_LOCAL_MODEL_EXAMPLE = "e.g. qwen2.5:7b"
_DEFAULT_CONTEXT = "8192"
_LLAMACPP_NOTE = (
    "Nothing to install: the first session downloads llama.cpp and the model "
    "(several GB), then the server stays up between sessions."
)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("settingsHint")
    return label


class LLMFields:
    """The rows of *role*'s LLM, added to a form by :meth:`add_rows`.

    *same_label* names a first choice that takes Think · LLM's model (a role
    other than the conversation). *thinking* is a local model's thinking until
    the user sets it, *thinking_hints* what it does (by provider: "local",
    "llamacpp"); *tool_use* offers a local server's tool-use switch.
    """

    def __init__(
        self,
        settings: dict,
        role: str,
        *,
        parent: QWidget,
        same_label: str | None = None,
        thinking: bool = False,
        thinking_hints: dict[str, str],
        tool_use: bool = True,
    ) -> None:
        self._settings = settings
        self._provider_key, self._prefix = LLM_ROLES[role]
        self._inherits = same_label is not None
        self._thinking = thinking
        self._thinking_hints = thinking_hints
        self._tool_use = tool_use
        self._parent = parent
        self.entries: list[tuple[str, str]] = [
            *([(same_label, "")] if same_label is not None else []),
            *LLM_PROVIDERS,
        ]
        self.provider = QComboBox()
        populate_provider_combo(self.provider, self.entries, AI_PROVIDER_FEATURES)
        values = [value for _label, value in self.entries]
        saved = settings.get(self._provider_key, "" if self._inherits else "anthropic")
        self.provider.setCurrentIndex(values.index(saved) if saved in values else 0)
        # provider → its widgets, and its field name → how to read it
        self._rows: dict[str, list[QWidget]] = {}
        self._readers: dict[str, dict[str, Callable[[], Any]]] = {}
        # field name ("anthropic_model", "llamacpp_thinking" …) → its input
        self.fields: dict[str, QWidget] = {}
        self.reasoning = QWidget()
        self._reasoning_note = _hint("")

    def _own(self, name: str, default: Any = "") -> Any:
        """The role's saved *name* field (``text_local_model``, ``vc_local_model`` …)."""
        return self._settings.get(self._prefix + name, default)

    def _think_llm(self, name: str, default: str = "") -> str:
        """Think · LLM's *name* field, which an empty one of the role's takes."""
        return str(self._settings.get("vc_" + name) or default)

    def _example(self, name: str, default: str, example: str) -> str:
        """A field's placeholder: Think · LLM's value it takes when left
        empty, for a role that takes it; else what it expects."""
        if self._inherits:
            return f"As in Think · LLM: {self._think_llm(name, default)}"
        return example

    def add_rows(self, form: QFormLayout, label: str) -> None:
        form.addRow(label, self.provider)
        form.addRow("", offer_install(self.provider, self.entries, AI_PROVIDER_FEATURES))
        for provider in ("anthropic", "openai", "gemini"):
            self._add_cloud(form, provider)
        self._add_reasoning(form)
        self._add_local(form)
        self._add_llamacpp(form)
        for field in (self.provider, *self.fields.values()):
            if isinstance(field, QComboBox | QLineEdit):
                field.setProperty("settingsFormField", True)
        self.provider.currentIndexChanged.connect(lambda _i: self.update_visibility())

    def _add_cloud(self, form: QFormLayout, provider: str) -> None:
        name = f"{provider}_model"
        model = self._own(name) or (self._think_llm(name) if self._inherits else "")
        combo = cloud_model_combo(provider, str(model))
        self.fields[name] = combo
        label = QLabel("Model")
        form.addRow(label, combo)
        self._rows[provider] = [label, combo]
        self._readers[provider] = {name: lambda: cloud_model(combo)}

    def _add_reasoning(self, form: QFormLayout) -> None:
        """Claude's thinking and effort, Gemini's thinking level: one block
        under the model, so search has one place to land. OpenAI has none:
        see ``engine_vc_helpers.reasoning_options``."""
        rows = SettingsForm(self.reasoning)
        thinking = choice_combo(CLAUDE_THINKING_OPTIONS, str(self._own("anthropic_thinking")))
        effort = choice_combo(CLAUDE_EFFORT_OPTIONS, str(self._own("anthropic_effort")))
        level = choice_combo(GEMINI_THINKING_OPTIONS, str(self._own("gemini_thinking")))
        thinking_label, effort_label = QLabel("Thinking"), QLabel("Effort")
        level_label = QLabel("Thinking level")
        rows.addRow(thinking_label, thinking)
        rows.addRow(effort_label, effort)
        rows.addRow(level_label, level)
        rows.addRow(self._reasoning_note)
        form.addRow(self.reasoning)
        self.fields.update(
            anthropic_thinking=thinking, anthropic_effort=effort, gemini_thinking=level
        )
        self._rows["anthropic"] += [thinking_label, thinking, effort_label, effort]
        self._rows["gemini"] += [level_label, level]
        self._readers["anthropic"].update(
            anthropic_thinking=lambda: thinking.currentData() or "",
            anthropic_effort=lambda: effort.currentData() or "",
        )
        self._readers["gemini"]["gemini_thinking"] = lambda: level.currentData() or ""
        anthropic = self.fields["anthropic_model"]
        gemini = self.fields["gemini_model"]
        assert isinstance(anthropic, QComboBox) and isinstance(gemini, QComboBox)
        anthropic.currentIndexChanged.connect(lambda _i: self._update_reasoning_note())
        gemini.currentTextChanged.connect(lambda _t: self._update_reasoning_note())

    def _update_reasoning_note(self) -> None:
        current = self.current()
        effort = self.fields["anthropic_effort"]
        if current == "anthropic":
            model = cloud_model(self.fields["anthropic_model"])  # type: ignore[arg-type]
            self._reasoning_note.setText(claude_reasoning_note(model))
            # Disabled, not reset: the pick returns with a model that takes it.
            takes_effort = "effort_refused" not in _catalog_tags(_ANTHROPIC_CATALOG, model)
            effort.setEnabled(takes_effort and self.provider.isEnabled())
        elif current == "gemini":
            model = cloud_model(self.fields["gemini_model"])  # type: ignore[arg-type]
            self._reasoning_note.setText(gemini_reasoning_note(model))

    def _add_local(self, form: QFormLayout) -> None:
        url = QLineEdit(str(self._own("local_base_url")))
        url.setPlaceholderText(
            self._example("local_base_url", _DEFAULT_LOCAL_URL, _DEFAULT_LOCAL_URL)
        )
        url_label = QLabel("Base URL")
        form.addRow(url_label, url)
        model = QLineEdit(str(self._own("local_model")))
        model.setPlaceholderText(
            self._example("local_model", _LOCAL_MODEL_EXAMPLE, _LOCAL_MODEL_EXAMPLE)
        )
        model_label = QLabel("Model")
        form.addRow(model_label, model)
        self.fields.update(local_base_url=url, local_model=model)
        rows: list[QWidget] = [url_label, url, model_label, model]
        readers: dict[str, Callable[[], Any]] = {
            "local_base_url": lambda: url.text().strip(),
            "local_model": lambda: model.text().strip(),
        }
        if self._tool_use:
            tools = QCheckBox("Model supports tool use (function calling)")
            tools.setChecked(bool(self._own("local_tools", True)))
            tools_label = QLabel("")
            form.addRow(tools_label, tools)
            self.fields["local_tools"] = tools
            rows += [tools_label, tools]
            readers["local_tools"] = tools.isChecked
        rows += self._add_thinking(form, "local", readers)
        self._rows["local"] = rows
        self._readers["local"] = readers

    def _add_llamacpp(self, form: QFormLayout) -> None:
        from roomkit_ui.providers.llamacpp import DEFAULT_MODEL

        gguf = QLineEdit(str(self._own("llamacpp_model")))
        think_llm = _short_model(self._think_llm("llamacpp_model", DEFAULT_MODEL))
        gguf.setPlaceholderText(
            f"As in Think · LLM: {think_llm}" if self._inherits else DEFAULT_MODEL
        )
        gguf.setToolTip("A Hugging Face GGUF as repo:quant, or the path of a local .gguf file.")
        browse = QPushButton("Browse…")
        browse.setCursor(Qt.PointingHandCursor)
        browse.setAutoDefault(False)
        browse.clicked.connect(lambda: self._browse_gguf(gguf))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(gguf, 1)
        row.addWidget(browse)
        gguf_label = QLabel("GGUF Model")
        form.addRow(gguf_label, row)
        context = QLineEdit(str(self._own("llamacpp_context") or ""))
        context.setPlaceholderText(
            self._example("llamacpp_context", _DEFAULT_CONTEXT, _DEFAULT_CONTEXT)
            + " (tokens; tools count against it)"
        )
        context_label = QLabel("Context")
        form.addRow(context_label, context)
        note = _hint(_LLAMACPP_NOTE)
        form.addRow("", note)
        readers: dict[str, Callable[[], Any]] = {
            "llamacpp_model": lambda: gguf.text().strip(),
            "llamacpp_context": lambda: context.text().strip(),
        }
        self.fields.update(llamacpp_model=gguf, llamacpp_context=context)
        thinking = self._add_thinking(form, "llamacpp", readers)
        self._rows["llamacpp"] = [
            gguf_label,
            gguf,
            browse,
            context_label,
            context,
            note,
            *thinking,
        ]
        self._readers["llamacpp"] = readers

    def _add_thinking(
        self, form: QFormLayout, provider: str, readers: dict[str, Callable[[], Any]]
    ) -> list[QWidget]:
        name = f"{provider}_thinking"
        box = QCheckBox("Model thinking (slower answers)")
        box.setChecked(bool(self._own(name, self._thinking)))
        label = QLabel("")
        form.addRow(label, box)
        hint = _hint(self._thinking_hints.get(provider, ""))
        form.addRow("", hint)
        readers[name] = box.isChecked
        self.fields[name] = box
        return [label, box, hint]

    def _browse_gguf(self, field: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._parent, "Select a GGUF Model", "", "GGUF models (*.gguf)"
        )
        if path:
            field.setText(path)

    def current(self) -> str:
        """The provider chosen; empty for Think · LLM's model."""
        return self.entries[self.provider.currentIndex()][1]

    def update_visibility(self, enabled: bool | None = None) -> None:
        """Show the chosen provider's fields; *enabled* greys them all."""
        if enabled is not None:
            self.provider.setEnabled(enabled)
        on = self.provider.isEnabled()
        current = self.current()
        for provider, widgets in self._rows.items():
            for widget in widgets:
                widget.setVisible(provider == current)
                widget.setEnabled(on)
        self.reasoning.setVisible(current in ("anthropic", "gemini"))
        self._update_reasoning_note()

    def get_settings(self) -> dict:
        """The provider, the chosen provider's fields; the others' as saved."""
        current = self.current()
        out: dict[str, Any] = {self._provider_key: current}
        for provider, readers in self._readers.items():
            for name, read in readers.items():
                key = self._prefix + name
                if provider == current:
                    out[key] = read()
                elif key in self._settings:
                    out[key] = self._settings[key]
        return out


def _short_model(model: str) -> str:
    """A GGUF path by its file name; a repo:quant as it is."""
    return Path(model).name if model.endswith(".gguf") else model
