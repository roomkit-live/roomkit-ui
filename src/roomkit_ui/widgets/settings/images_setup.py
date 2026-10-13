"""Images tab: the provider and model the assistant draws with."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QFrame, QLabel, QWidget

from roomkit_ui.features import IMAGE_PROVIDER_FEATURES
from roomkit_ui.image_generation import IMAGE_PROVIDERS, default_image_model, image_models
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.model_combos import select_model

_IMAGES_HINT = (
    "Asked for a picture, the assistant draws it and shows it in the chat, by voice "
    "or in writing; it can also change the last image of the conversation, one you "
    "shared or one it drew. It uses this provider's key from Providers & keys. Each "
    "image is billed by the provider, and one that fails is never drawn again on its "
    "own. The session's cost counts it when roomkit knows the model's price."
)


class ImagesSetup(QFrame):
    """The Images tab of the Conversation page."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self._settings = settings
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
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
            label = QLabel("Model")
            form.addRow(label, combo)
            self.models[provider] = (label, combo)

        hint = QLabel(_IMAGES_HINT)
        hint.setWordWrap(True)
        hint.setObjectName("settingsHint")
        form.addRow("", hint)
        self.provider.currentIndexChanged.connect(lambda _i: self._update_visibility())
        self._update_visibility()

    def current(self) -> str:
        """The provider chosen, empty when the assistant does not draw."""
        return IMAGE_PROVIDERS[self.provider.currentIndex()][1]

    def _update_visibility(self) -> None:
        current = self.current()
        for provider, (label, combo) in self.models.items():
            label.setVisible(provider == current)
            combo.setVisible(provider == current)

    def get_settings(self) -> dict:
        current = self.current()
        out: dict = {"image_provider": current}
        for provider, (_label, combo) in self.models.items():
            key = f"image_{provider}_model"
            if provider == current:
                out[key] = combo.currentData() or ""
            elif key in self._settings:
                out[key] = self._settings[key]
        return out
