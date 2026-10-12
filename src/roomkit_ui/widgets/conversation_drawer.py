"""Full-width sliding history panel for the compact conversation window."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.conversations import Conversation
from roomkit_ui.icons import svg_icon
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.buttons import KeyboardButton
from roomkit_ui.widgets.menus import menu_action
from roomkit_ui.widgets.settings.style import settings_colors
from roomkit_ui.widgets.sliding_panel import SlidingPanel


class _ConversationDelegate(QStyledItemDelegate):
    """Keep the title and date on separate lines, even in a narrow window."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(0, 62)

    def paint(self, painter, option, index) -> None:
        title, _, detail = index.data().partition("\n")
        c = settings_colors()
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        focused = bool(option.state & QStyle.State_HasFocus)
        hovered = bool(option.state & QStyle.State_MouseOver)
        enabled = bool(option.state & QStyle.State_Enabled)
        if selected or focused or (hovered and enabled):
            painter.setPen(QColor(c["accent"]) if focused else Qt.NoPen)
            painter.setBrush(QColor(c["selected"] if selected else c["soft"]))
            painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -3), 7, 7)
        foreground = c["accent"] if selected and enabled else c["muted"]
        icon_rect = QRect(option.rect.x() + 12, option.rect.y() + 12, 18, 18)
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(
                painter, icon_rect, Qt.AlignCenter, QIcon.Selected if selected else QIcon.Normal
            )
        rect = option.rect.adjusted(42, 8, -44, -8)
        font = QFont(option.font)
        for text, size, color, offset in (
            (title, 13, foreground, 0),
            (detail, 11, c["muted"], 22),
        ):
            font.setPixelSize(size)
            painter.setFont(font)
            painter.setPen(QColor(color))
            line = QFontMetrics(font).elidedText(text, Qt.ElideRight, rect.width())
            line_rect = rect.translated(0, offset)
            line_rect.setHeight(22)
            painter.drawText(line_rect, Qt.AlignLeft | Qt.AlignVCenter, line)
        painter.setPen(QColor(foreground))
        painter.drawText(
            option.rect.adjusted(option.rect.width() - 40, 0, -4, -6),
            Qt.AlignCenter,
            "⋯",
        )
        painter.restore()


class ConversationDrawer(SlidingPanel):
    selected = Signal(str)
    new_requested = Signal()
    settings_requested = Signal()
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__("Conversations", parent)
        layout = self.body
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search conversations…")
        self._search.setAccessibleName("Search conversations")
        self._search.setClearButtonEnabled(True)
        self._search_icon = self._search.addAction(QIcon(), QLineEdit.LeadingPosition)
        self._search_icon.triggered.connect(self._search.setFocus)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)
        layout.addSpacing(12)
        self._new = KeyboardButton("New conversation")
        self._new.setObjectName("newConversation")
        self._new.setMinimumHeight(42)
        self._new.setIconSize(QSize(18, 18))
        self._new.clicked.connect(self.new_requested.emit)
        layout.addWidget(self._new)
        self._notice = QLabel()
        self._notice.setObjectName("drawerNotice")
        self._notice.setWordWrap(True)
        self._notice.hide()
        layout.addWidget(self._notice)
        self._section = QLabel("Recent")
        self._section.setObjectName("drawerSection")
        self._section.setFixedHeight(44)
        self._section.setContentsMargins(12, 6, 0, 0)
        section_font = self._section.font()
        section_font.setCapitalization(QFont.AllUppercase)
        section_font.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        self._section.setFont(section_font)
        layout.addWidget(self._section)
        self._list = QListWidget()
        self._list.setItemDelegate(_ConversationDelegate(self._list))
        self._list.setAccessibleName("Saved conversations")
        self._list.setMouseTracking(True)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._choose)
        self._list.itemActivated.connect(self._choose)
        self._list.viewport().installEventFilter(self)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        rename = QShortcut(QKeySequence(Qt.Key_F2), self._list)
        rename.activated.connect(self._rename_current)
        # Delete, and Backspace: the key macOS labels Delete.
        for key in (Qt.Key_Delete, Qt.Key_Backspace):
            delete = QShortcut(QKeySequence(key), self._list)
            delete.activated.connect(self._delete_current)
        layout.addWidget(self._list, 1)
        self._empty = QLabel("Your conversations will appear here.")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty, 1)
        footer = QFrame()
        footer.setObjectName("drawerFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 10, 0, 0)
        self._settings = KeyboardButton()
        self._settings.setObjectName("drawerSettings")
        self._settings.setAccessibleName("Settings")
        self._settings.setMinimumHeight(42)
        settings_row = QHBoxLayout(self._settings)
        settings_row.setContentsMargins(12, 0, 12, 0)
        settings_row.setSpacing(12)
        self._settings_icon = QLabel()
        self._settings_icon.setFixedSize(18, 18)
        settings_label = QLabel("Settings")
        settings_label.setObjectName("drawerSettingsLabel")
        for label in (self._settings_icon, settings_label):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            settings_row.addWidget(label)
        settings_row.addStretch()
        self._settings.clicked.connect(self.settings_requested.emit)
        footer_layout.addWidget(self._settings)
        layout.addWidget(footer)
        for button in (self._close, self._new, self._settings):
            button.setCursor(Qt.PointingHandCursor)
        self._conversations: list[Conversation] = []
        self._selected = ""
        self._busy = False
        bind_theme(self, self._render_theme)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._new.setEnabled(not busy)
        self._list.setEnabled(not busy)
        self._settings.setEnabled(not busy)
        self._settings.setToolTip(
            "Finish the current activity to open Settings." if busy else "Settings"
        )
        self.set_notice("Finish the current activity to switch conversations." if busy else "")

    def set_notice(self, text: str) -> None:
        self._notice.setText(text)
        self._notice.setVisible(bool(text))

    def set_conversations(self, conversations: list[Conversation], selected: str = "") -> None:
        self._conversations = conversations
        self._selected = selected
        self._filter()

    def _filter(self) -> None:
        query = self._search.text().strip().casefold()
        conversations = (
            [c for c in self._conversations if query in c.title.casefold()]
            if query
            else self._conversations[:30]
        )
        self._section.setText("Search results" if query else "Recent")
        self._list.clear()
        for conversation in conversations:
            try:
                date = datetime.fromisoformat(conversation.updated_at).astimezone()
                detail = date.strftime("%b %d · %H:%M")
            except ValueError:
                detail = "Saved conversation"
            if not conversation.persistent:
                detail += " · Not saved"
            item = QListWidgetItem(f"{conversation.title}\n{detail}")
            item.setIcon(self._conversation_icon)
            item.setData(Qt.UserRole, conversation.id)
            item.setToolTip(conversation.title)
            item.setData(
                Qt.AccessibleDescriptionRole,
                "Press F2 to rename this conversation, Delete to delete it.",
            )
            self._list.addItem(item)
            if conversation.id == self._selected:
                self._list.setCurrentItem(item)
        self._empty.setText(
            "No matching conversations." if query else "Your conversations will appear here."
        )
        self._empty.setVisible(not conversations)
        self._list.setVisible(bool(conversations))

    def _rename_current(self) -> None:
        if (item := self._list.currentItem()) is not None and not self._busy:
            self.rename_requested.emit(item.data(Qt.UserRole))

    def _delete_current(self) -> None:
        if (item := self._list.currentItem()) is not None and not self._busy:
            self.delete_requested.emit(item.data(Qt.UserRole))

    def _context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None or self._busy:
            return
        conversation_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu_action(menu, "Rename", "pencil")
        delete = menu_action(menu, "Delete…", "trash", destructive=True)
        try:
            chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
            if chosen == rename:
                self.rename_requested.emit(conversation_id)
            elif chosen == delete:
                self.delete_requested.emit(conversation_id)
        finally:
            menu.deleteLater()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self._list.viewport()
            and event.type()
            in (
                QEvent.MouseButtonPress,
                QEvent.MouseButtonRelease,
            )
            and event.button() == Qt.LeftButton
        ):
            pos = event.position().toPoint()
            item = self._list.itemAt(pos)
            if item is not None and pos.x() >= self._list.visualItemRect(item).right() - 40:
                if event.type() == QEvent.MouseButtonRelease:
                    self._context_menu(pos)
                return True
        return super().eventFilter(watched, event)

    def _choose(self, item: QListWidgetItem) -> None:
        if not self._busy:
            self.selected.emit(item.data(Qt.UserRole))

    def _styles(self, c: dict[str, str]) -> str:
        return super()._styles(c) + (
            f"QLabel#drawerNotice {{ color: {c['muted']}; padding: 10px; }}"
            f"QLabel#drawerSettingsLabel {{ color: {c['muted']};"
            " font-size: 13px; font-weight: 500; }"
            f"QPushButton#newConversation {{ background: {c['soft']}; color: {c['accent']}; }}"
            "QListWidget { background: transparent; border: none; outline: none;"
            f" color: {c['text']}; font-size: 13px; }}"
        )

    def _render_theme(self) -> None:
        super()._render_theme()
        c = settings_colors()
        self._search_icon.setIcon(svg_icon("magnifying-glass", c["muted"], 18))
        self._new.setIcon(svg_icon("plus", c["accent"], 18))
        self._settings_icon.setPixmap(svg_icon("cog-6-tooth", c["muted"], 18).pixmap(18, 18))
        self._conversation_icon = svg_icon("chat-bubble", c["muted"], 18)
        self._conversation_icon.addPixmap(
            svg_icon("chat-bubble", c["accent"], 18).pixmap(18, 18), QIcon.Selected
        )
        for row in range(self._list.count()):
            self._list.item(row).setIcon(self._conversation_icon)
