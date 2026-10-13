"""Resizable Settings workspace with grouped navigation and save-on-close."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.theme_live import apply_theme, bind_theme
from roomkit_ui.widgets.navigation_brand import NavigationBrand
from roomkit_ui.widgets.settings.controls import label
from roomkit_ui.widgets.settings.navigation import SettingsNavigation
from roomkit_ui.widgets.settings.page_registry import PAGE_SPECS
from roomkit_ui.widgets.settings.search import SearchResult, SearchResults, find_settings
from roomkit_ui.widgets.settings.style import settings_colors, settings_stylesheet


class SettingsPanel(QDialog):
    """Each page has a stable identity, independent of sidebar group headings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.setWindowTitle("Settings — RoomKit")
        self.setModal(True)
        self._restore_size()
        settings = load_settings()
        bind_theme(self, self._apply_style)
        self._specs = {spec.key: spec for spec in PAGE_SPECS}
        self._current_page_key = "general"
        self._stack = QStackedWidget()
        self._page_widgets: dict[str, QWidget] = {}
        self._scrolls: dict[str, QScrollArea] = {}
        self._build_pages(settings)
        self._general.theme_picker.theme_changed.connect(apply_theme)
        self._sidebar = SettingsNavigation(PAGE_SPECS)
        self._breadcrumb = label("", "settingsBreadcrumb", wrap=False)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search settings…")
        self._search.setAccessibleName("Search settings")
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip("Find a setting by name or keyword. Ctrl/Cmd+K or Ctrl/Cmd+F.")
        search_action = self._search.addAction(QIcon(), QLineEdit.LeadingPosition)
        search_action.setText("Search settings")
        search_action.triggered.connect(self._focus_search)
        bind_theme(
            self._search,
            lambda: search_action.setIcon(
                svg_icon("magnifying-glass", settings_colors()["muted"], 18)
            ),
        )
        self._search_results = SearchResults()
        self._search_notice = label("", "settingsSearchNotice")
        self._search_notice.hide()
        self._highlighted: QWidget | None = None
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_highlight)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.timeout.connect(self._focus_search_target)
        self._pending_target: QWidget | None = None
        self._save_hint = label(
            "Theme changes apply immediately. Other changes are saved on close.",
            "settingsSaveHint",
        )
        content = QHBoxLayout(self)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_sidebar())
        content.addWidget(self._build_workspace(), 1)
        self._sidebar.page_selected.connect(self._on_page_changed)
        self._sidebar.itemClicked.connect(lambda _: self._search.clear())
        self._search.textChanged.connect(self._search_changed)
        self._search_results.activated.connect(self._open_search_result)
        self._search.installEventFilter(self)
        self._search_results.list.installEventFilter(self)
        for sequence in (QKeySequence(QKeySequence.Find), QKeySequence("Ctrl+K")):
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._focus_search)
        for page in self._pages:
            if hasattr(page, "navigate_requested"):
                page.navigate_requested.connect(self._navigate)
        self._sidebar.select_page("general")

    def _apply_style(self) -> None:
        self.setStyleSheet(settings_stylesheet(str(QSettings().value("room/theme", "dark"))))

    def _navigate(self, key: str) -> None:
        key, _, section = key.partition(":")
        self._sidebar.select_page(key)
        if key == "conversation" and section == "personality":
            self._conversation.tabs.bar.setCurrentIndex(3)
        if key == "diagnostics":
            self._diagnostics.tabs.bar.setCurrentIndex(2 if section == "telemetry" else 0)
            self._diagnostics.reveal_search_target()
        if key == "models":
            self._models.tabs.bar.setCurrentIndex(1 if section == "components" else 0)
            self._models.models.clear_filters()

    def _restore_size(self) -> None:
        screen = self.screen()
        available = screen.availableGeometry().size() if screen else QSize(1280, 900)
        minimum = QSize(820, 620).boundedTo(available)
        self.setMinimumSize(minimum)
        saved = QSettings().value("ui/settings_size")
        size = saved if isinstance(saved, QSize) and saved.isValid() else QSize(1060, 820)
        self.resize(size.expandedTo(minimum).boundedTo(available))

    def _build_pages(self, settings: dict) -> None:
        for spec in PAGE_SPECS:
            page = spec.create(settings)
            setattr(self, f"_{spec.key}", page)
            self._page_widgets[spec.key] = page
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            # Keep long legacy provider forms scrollable while the pages migrate.
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(32, 28, 32, 28)
            layout.addWidget(page)
            scroll.setWidget(container)
            self._scrolls[spec.key] = scroll
            self._stack.addWidget(scroll)
        self._pages = tuple(self._page_widgets.values())
        self._privacy.recording_directory_changed.connect(
            self._diagnostics.set_recording_directory
        )

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(22, 25, 22, 21)
        brand.addWidget(NavigationBrand())
        layout.addLayout(brand)
        title = label("Settings", "settingsNavTitle", wrap=False)
        title.setContentsMargins(22, 0, 22, 6)
        layout.addWidget(title)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(12, 4, 12, 8)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)
        layout.addWidget(self._sidebar, 1)
        layout.addWidget(label("Your desktop voice assistant", "settingsVersion"))
        return sidebar

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("settingsToolbar")
        top = QHBoxLayout(toolbar)
        top.setContentsMargins(32, 18, 32, 18)
        top.addWidget(self._breadcrumb)
        top.addStretch()
        layout.addWidget(toolbar)
        self._search_notice.setContentsMargins(32, 10, 32, 10)
        layout.addWidget(self._search_notice)
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self._stack)
        self._content_stack.addWidget(self._search_results)
        layout.addWidget(self._content_stack, 1)
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(32, 12, 24, 12)
        bottom.setSpacing(16)
        bottom.addWidget(self._save_hint, 1)
        self._done_button = QPushButton("Done")
        self._done_button.setAutoDefault(False)
        self._done_button.setCursor(Qt.PointingHandCursor)
        self._done_button.clicked.connect(self.accept)
        bottom.addWidget(self._done_button)
        layout.addWidget(footer)
        return workspace

    def _on_page_changed(self, key: str) -> None:
        self._current_page_key = key
        self._search.clear()
        self._search_notice.hide()
        self._clear_highlight()
        spec = self._specs[key]
        self._stack.setCurrentWidget(self._scrolls[key])
        self._breadcrumb.setText(f"Settings  /  {spec.group}  /  {spec.title}")
        if key == "wakeword":
            self._wakeword.set_capture_settings(
                {**self._audio.get_settings(), **self._conversation.get_settings()}
            )
        if spec.refresh:
            getattr(self._page_widgets[key], spec.refresh)()

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.ShortcutFocusReason)
        self._search.selectAll()

    def _search_changed(self, text: str) -> None:
        self._search_notice.hide()
        self._clear_highlight()
        searching = bool(text.strip())
        self._content_stack.setCurrentIndex(1 if searching else 0)
        if searching:
            self._breadcrumb.setText("Settings  /  Search")
            self._search_results.show_results(find_settings(PAGE_SPECS, text))
        else:
            spec = self._specs[self._current_page_key]
            self._breadcrumb.setText(f"Settings  /  {spec.group}  /  {spec.title}")
            self._search_results.show_results([])

    @staticmethod
    def _resolve(page: QWidget, path: str):
        value = page
        for part in path.split("."):
            value = value[part] if isinstance(value, dict) else getattr(value, part)
        return value

    def _open_search_result(self, result: SearchResult) -> None:
        self._search.clear()
        self._sidebar.select_page(result.page)
        page = self._page_widgets[result.page]
        target = result.target
        for path, index in target.tabs:
            self._resolve(page, path).bar.setCurrentIndex(index)
        if result.page in {"providers", "integrations"}:
            page.reveal_search_target(target.control)
        elif hasattr(page, "reveal_search_target"):
            page.reveal_search_target()
        if target.disclosure:
            self._resolve(page, target.disclosure).set_expanded(True)
        widget = self._resolve(page, target.control) if target.control else page
        if (not widget.isVisibleTo(page) or not widget.isEnabled()) and target.fallback:
            widget = self._resolve(page, target.fallback)
            self._search_notice.setText(target.unavailable)
        else:
            self._search_notice.setText(f"Found: {target.title}")
        self._search_notice.show()
        self._pending_target = widget
        # Wait for tab/disclosure layout before scrolling and placing keyboard focus.
        self._focus_timer.start(0)

    def _focus_search_target(self) -> None:
        widget = self._pending_target
        if widget is None:
            return
        self._pending_target = None
        for scroll in self._scrolls.values():
            if scroll.isAncestorOf(widget):
                scroll.ensureWidgetVisible(widget, 16, 32)
                break
        focus = widget
        if focus.focusPolicy() == Qt.NoFocus:
            focus = next(
                (
                    child
                    for child in widget.findChildren(QWidget)
                    if child.focusPolicy() != Qt.NoFocus
                    and child.isVisibleTo(widget)
                    and child.isEnabled()
                ),
                widget,
            )
        focus.setFocus(Qt.ShortcutFocusReason)
        self._highlighted = widget
        widget.setProperty("settingsSearchHit", True)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
        self._highlight_timer.start(2200)

    def _clear_highlight(self) -> None:
        self._focus_timer.stop()
        self._pending_target = None
        if self._highlighted is not None:
            widget = self._highlighted
            widget.setProperty("settingsSearchHit", False)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
            self._highlighted = None
        self._highlight_timer.stop()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._search_results.activate_current()
                return True
            if event.key() == Qt.Key_Escape and self._search.text():
                self._search.clear()
                self._focus_search()
                return True
            if (
                watched is self._search
                and event.key() == Qt.Key_Down
                and self._search_results.list.count()
                and self._content_stack.currentIndex() == 1
            ):
                self._search_results.list.setFocus(Qt.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self._search.text():
            self._search.clear()
            self._focus_search()
            event.accept()
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # Esc, Done, and the title-bar close all save exactly once.
        self._save()
        QSettings().setValue("ui/settings_size", self.size())
        super().done(result)

    def _save(self) -> None:
        # Collect settings from each page that has them
        settings: dict = {}
        for page in self._pages:
            if hasattr(page, "get_settings"):
                settings.update(page.get_settings())

        save_settings(settings)
