"""Images tab: the provider and model the assistant draws with, and the
settings that model takes (size, shape, resolution, quality, thinking)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QFrame, QLabel, QWidget

from roomkit_ui.features import IMAGE_PROVIDER_FEATURES
from roomkit_ui.image_generation import (
    IMAGE_CONTROL_FIELDS,
    IMAGE_PROVIDERS,
    default_image_model,
    image_controls,
    image_models,
)
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.model_combos import choice_combo, select_model

_IMAGES_HINT = (
    "Asked for a picture, the assistant draws it and shows it in the chat, by voice "
    "or in writing; it can also change the last image of the conversation, one you "
    "shared or one it drew. It uses this provider's key from Providers & keys. Each "
    "image is billed by the provider, and one that fails is never drawn again on its "
    "own. The session's cost counts it when roomkit knows the model's price."
)

_SETTINGS_HINT = (
    "What this model takes, from roomkit's catalog, as defaults: a size the assistant "
    "asks for wins over the size, shape and resolution. A higher quality or resolution "
    "costs more and takes longer."
)


def _form(widget: QWidget) -> QFormLayout:
    form = QFormLayout(widget)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setSpacing(10)
    form.setLabelAlignment(Qt.AlignLeft)
    form.setRowWrapPolicy(QFormLayout.WrapAllRows)
    return form


class ImagesSetup(QFrame):
    """The Images tab of the Conversation page."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self._settings = settings
        form = _form(self)
        form.setContentsMargins(20, 20, 20, 20)

        self.provider = QComboBox()
        populate_provider_combo(self.provider, IMAGE_PROVIDERS, IMAGE_PROVIDER_FEATURES)
        values = [value for _label, value in IMAGE_PROVIDERS]
        saved = settings.get("image_provider", "")
        self.provider.setCurrentIndex(values.index(saved) if saved in values else 0)
        self.provider.setProperty("settingsFormField", True)
        form.addRow("The assistant draws with", self.provider)
        form.addRow("", offer_install(self.provider, IMAGE_PROVIDERS, IMAGE_PROVIDER_FEATURES))

        # provider → (its label, its model dropdown)
        self.models: dict[str, tuple[QLabel, QComboBox]] = {}
        for _label, provider in IMAGE_PROVIDERS[1:]:
            combo = QComboBox()
            for name, model_id in image_models(provider):
                combo.addItem(name, model_id)
            combo.setCurrentIndex(max(combo.findData(default_image_model(provider)), 0))
            select_model(combo, str(settings.get(f"image_{provider}_model") or ""))
            combo.setProperty("settingsFormField", True)
            combo.currentIndexChanged.connect(lambda _i: self._show_model_settings())
            label = QLabel("Model")
            form.addRow(label, combo)
            self.models[provider] = (label, combo)

        # The chosen model's settings, rebuilt when the model changes; what
        # was picked is kept by (provider, field) while the tab is open.
        self._values: dict[tuple[str, str], str] = {
            (provider, field): str(settings.get(f"image_{provider}_{field}") or "")
            for _label, provider in IMAGE_PROVIDERS[1:]
            for field in IMAGE_CONTROL_FIELDS
        }
        # field → its dropdown, for the model shown
        self.controls: dict[str, QComboBox] = {}
        self.model_settings = QWidget()
        self._model_rows = _form(self.model_settings)
        self._model_rows.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.model_settings)
        self._settings_hint = QLabel(_SETTINGS_HINT)
        self._settings_hint.setWordWrap(True)
        self._settings_hint.setObjectName("settingsHint")
        form.addRow("", self._settings_hint)

        hint = QLabel(_IMAGES_HINT)
        hint.setWordWrap(True)
        hint.setObjectName("settingsHint")
        form.addRow("", hint)
        self.provider.currentIndexChanged.connect(lambda _i: self._update_visibility())
        self._update_visibility()

    def current(self) -> str:
        """The provider chosen, empty when the assistant does not draw."""
        return IMAGE_PROVIDERS[self.provider.currentIndex()][1]

    def _model(self, provider: str) -> str:
        return str(self.models[provider][1].currentData() or "")

    def _update_visibility(self) -> None:
        current = self.current()
        for provider, (label, combo) in self.models.items():
            label.setVisible(provider == current)
            combo.setVisible(provider == current)
        self._show_model_settings()

    def _show_model_settings(self) -> None:
        """The rows of the chosen model's settings, its default first in each."""
        while self._model_rows.rowCount():
            self._model_rows.removeRow(0)
        self.controls = {}
        current = self.current()
        controls = image_controls(current, self._model(current)) if current else []
        for control in controls:
            key = (current, control.field)
            combo = choice_combo(list(control.choices), self._values.get(key, ""))
            combo.setProperty("settingsFormField", True)
            combo.currentIndexChanged.connect(
                lambda _i, key=key, combo=combo: self._remember(key, combo)
            )
            self._model_rows.addRow(control.label, combo)
            self.controls[control.field] = combo
        self.model_settings.setVisible(bool(controls))
        self._settings_hint.setVisible(bool(controls))

    def _remember(self, key: tuple[str, str], combo: QComboBox) -> None:
        self._values[key] = str(combo.currentData() or "")

    def get_settings(self) -> dict:
        current = self.current()
        out: dict = {"image_provider": current}
        for provider, (_label, combo) in self.models.items():
            key = f"image_{provider}_model"
            if provider == current:
                out[key] = combo.currentData() or ""
            elif key in self._settings:
                out[key] = self._settings[key]
        if current:
            # A setting the model does not take is cleared, not left to apply
            # to a model that would refuse it.
            for field in IMAGE_CONTROL_FIELDS:
                setting = self.controls.get(field)
                out[f"image_{current}_{field}"] = (setting.currentData() or "") if setting else ""
        return out
