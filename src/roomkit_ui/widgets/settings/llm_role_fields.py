"""A role's LLM in a settings form: Think · LLM's, or a model of its own.

The Agent tab sets the background tasks' (``vc_background_*``), the Text chat
tab typed messages' (``text_*``); ``providers.llm_settings`` reads them.
Each provider shows the fields Think · LLM does: a cloud model starts on
Think · LLM's, a local field left empty takes Think · LLM's value.  Only the
chosen provider's fields are saved; the others keep what they held.
"""

from __future__ import annotations

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
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.vc_cloud_fields import cloud_model, cloud_model_combo

_DEFAULT_LOCAL_URL = "http://localhost:11434/v1"


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("settingsHint")
    return label


class RoleLLMFields:
    """The rows of *role*'s LLM, added to a form by ``add_rows``.

    *same_label* names the first choice, Think · LLM's model.  *thinking*
    is a local model's thinking until the user sets it, with its hint;
    *tool_use* offers a local model's tool-use switch.
    """

    def __init__(
        self,
        settings: dict,
        role: str,
        *,
        same_label: str,
        thinking: bool,
        thinking_hint: str,
        tool_use: bool,
        parent: QWidget,
    ) -> None:
        self._settings = settings
        self._provider_key, self._prefix = LLM_ROLES[role]
        self._thinking = thinking
        self._thinking_hint = thinking_hint
        self._tool_use = tool_use
        self._parent = parent
        self.entries: list[tuple[str, str]] = [(same_label, ""), *LLM_PROVIDERS]
        self.provider = QComboBox()
        populate_provider_combo(self.provider, self.entries, AI_PROVIDER_FEATURES)
        saved = settings.get(self._provider_key, "")
        values = [value for _label, value in self.entries]
        self.provider.setCurrentIndex(values.index(saved) if saved in values else 0)
        # provider → its widgets, and its field name → how to read it
        self._rows: dict[str, list[QWidget]] = {}
        self._readers: dict[str, dict[str, Callable[[], Any]]] = {}
        # field name ("anthropic_model", "llamacpp_thinking" …) → its input
        self.fields: dict[str, QWidget] = {}

    def _own(self, name: str, default: Any = "") -> Any:
        """The role's saved *name* field (``text_local_model`` …)."""
        return self._settings.get(self._prefix + name, default)

    def _think_llm(self, name: str, default: str = "") -> str:
        """Think · LLM's *name* field, which an empty one of the role's takes."""
        return str(self._settings.get("vc_" + name) or default)

    def add_rows(self, form: QFormLayout, label: str) -> None:
        form.addRow(label, self.provider)
        form.addRow("", offer_install(self.provider, self.entries, AI_PROVIDER_FEATURES))
        for provider in ("anthropic", "openai", "gemini"):
            self._add_cloud(form, provider)
        self._add_local(form)
        self._add_llamacpp(form)
        for field in (self.provider, *self.fields.values()):
            if isinstance(field, QComboBox | QLineEdit):
                field.setProperty("settingsFormField", True)
        self.provider.currentIndexChanged.connect(lambda _i: self.update_visibility())

    def _add_cloud(self, form: QFormLayout, provider: str) -> None:
        name = f"{provider}_model"
        combo = cloud_model_combo(provider, self._own(name) or self._think_llm(name))
        self.fields[name] = combo
        label = QLabel("Model")
        form.addRow(label, combo)
        self._rows[provider] = [label, combo]
        self._readers[provider] = {name: lambda: cloud_model(combo)}

    def _add_local(self, form: QFormLayout) -> None:
        url = QLineEdit(self._own("local_base_url"))
        url.setPlaceholderText(
            f"As in Think · LLM: {self._think_llm('local_base_url', _DEFAULT_LOCAL_URL)}"
        )
        url_label = QLabel("Base URL")
        form.addRow(url_label, url)
        model = QLineEdit(self._own("local_model"))
        think_llm_model = self._think_llm("local_model")
        model.setPlaceholderText(
            f"As in Think · LLM: {think_llm_model}" if think_llm_model else "e.g. qwen2.5:7b"
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
        rows += self._add_thinking(form, "local_thinking", readers)
        self._rows["local"] = rows
        self._readers["local"] = readers

    def _add_llamacpp(self, form: QFormLayout) -> None:
        from roomkit_ui.providers.llamacpp import DEFAULT_MODEL

        gguf = QLineEdit(self._own("llamacpp_model"))
        gguf.setPlaceholderText(
            f"As in Think · LLM: {_short_model(self._think_llm('llamacpp_model', DEFAULT_MODEL))}"
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
            f"As in Think · LLM: {self._think_llm('llamacpp_context', '8192')} "
            "(tokens; tools count against it)"
        )
        context_label = QLabel("Context")
        form.addRow(context_label, context)
        readers: dict[str, Callable[[], Any]] = {
            "llamacpp_model": lambda: gguf.text().strip(),
            "llamacpp_context": lambda: context.text().strip(),
        }
        self.fields.update(llamacpp_model=gguf, llamacpp_context=context)
        thinking = self._add_thinking(form, "llamacpp_thinking", readers)
        self._rows["llamacpp"] = [gguf_label, gguf, browse, context_label, context, *thinking]
        self._readers["llamacpp"] = readers

    def _add_thinking(
        self, form: QFormLayout, name: str, readers: dict[str, Callable[[], Any]]
    ) -> list[QWidget]:
        box = QCheckBox("Model thinking")
        box.setChecked(bool(self._own(name, self._thinking)))
        label = QLabel("")
        form.addRow(label, box)
        hint = _hint(self._thinking_hint)
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
        """The provider chosen, empty for Think · LLM's model."""
        return self.entries[self.provider.currentIndex()][1]

    def widgets(self, provider: str) -> list[QWidget]:
        return self._rows.get(provider, [])

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

    def get_settings(self) -> dict:
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
