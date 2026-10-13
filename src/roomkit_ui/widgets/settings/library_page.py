"""One destination for local model files and the components that use them."""

from PySide6.QtWidgets import QWidget

from roomkit_ui.widgets.settings.components_page import _ComponentsPage
from roomkit_ui.widgets.settings.controls import SettingsTabs, page_layout
from roomkit_ui.widgets.settings.llm_library_page import LLMLibrary
from roomkit_ui.widgets.settings.models_page import _ModelsPage


class LibraryPage(QWidget):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "Models & components", "Everything you need to run your chosen features."
        )
        self.models = _ModelsPage(settings)
        self.llms = LLMLibrary(settings)
        self.components = _ComponentsPage(settings)
        self.tabs = SettingsTabs(
            [("Local models", self.models), ("LLMs", self.llms), ("Components", self.components)]
        )
        self.tabs.current_changed.connect(self._tab_changed)
        self.models.components_requested.connect(lambda: self.tabs.bar.setCurrentIndex(2))
        layout.addWidget(self.tabs)
        layout.addStretch()

    def _tab_changed(self, _index: int) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.models.refresh()
        self.llms.refresh()
        self.components.refresh()

    def reveal_search_target(self) -> None:
        self.models.clear_filters()
        self.components.clear_filters()
