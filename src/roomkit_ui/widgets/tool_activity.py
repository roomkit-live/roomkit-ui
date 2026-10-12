"""Compact tool activity with optional, plain-text execution details."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.mcp_app_state import AppToolResults
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.widgets.buttons import KeyboardButton

if TYPE_CHECKING:
    from roomkit_ui.widgets.mcp_app_widget import MCPAppWidget

_TITLES = {
    "get_current_date": "Current date",
    "get_current_time": "Local time",
    "get_roomkit_info": "About RoomKit",
    "list_attitudes": "Available personalities",
    "set_attitude": "Change personality",
    "paste_text": "Paste text",
    "end_conversation": "End conversation",
    "name_speaker": "Name a speaker",
    "recall_conversations": "Search past conversations",
}
_STATUS = {"running": "Working…", "completed": "Done", "failed": "Failed", "cancelled": "Stopped"}
_PREVIEW_LIMIT = 20_000


def tool_title(name: str) -> str:
    """Readable names without claiming anything about what the tool returned."""
    if name in _TITLES:
        return _TITLES[name]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    words = re.sub(r"[_-]+", " ", words).strip()
    return words[:1].upper() + words[1:] if words else "Tool"


def _preview(text: str) -> str:
    if len(text) <= _PREVIEW_LIMIT:
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except (ValueError, RecursionError):
            pass
    if len(text) > _PREVIEW_LIMIT:
        return text[:_PREVIEW_LIMIT] + "\n\n… Preview limited to 20,000 characters."
    return text or "No content returned."


class _Title(QLabel):
    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setTextFormat(Qt.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, self.width()))
        super().resizeEvent(event)


class _ActivityIcon(QWidget):
    """A small spinner only while the call is running and its row is visible."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.status = "running"
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    def set_status(self, status: str) -> None:
        self.status = status
        self._animate()
        self.update()

    def _animate(self) -> None:
        if self.status == "running" and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._animate()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        c = colors()
        color = c["ACCENT_RED"] if self.status == "failed" else c["ACCENT_BRAND"]
        if self.status == "cancelled":
            color = c["TEXT_SECONDARY"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.status == "running":
            pen = QPen(QColor(color), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(QRectF(2, 2, 14, 14), -self._angle * 16, 250 * 16)
        else:
            name = {"completed": "check", "failed": "information-circle", "cancelled": "stop"}
            svg_icon(name[self.status], color, 18).paint(painter, self.rect())
        painter.end()


class ToolActivity(QFrame):
    """One invocation, updated in place; its raw input never fills the transcript."""

    def __init__(self, call: ToolCall, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.call = call
        self.result: ToolResult | None = None
        self._details: QPlainTextEdit | None = None
        self._app: MCPAppWidget | None = None
        self.app_html = ""
        self.app_results = AppToolResults()
        self.setObjectName("toolActivity")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._header = KeyboardButton(self)
        self._header.setObjectName("toolHeader")
        self._header.setCheckable(True)
        self._header.setAccessibleDescription("Details collapsed")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setFixedHeight(48)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(10)
        self._icon = _ActivityIcon(self._header)
        self._title = _Title(tool_title(call.name), self._header)
        self._status = QLabel(self._header)
        self._chevron = QLabel(self._header)
        self._chevron.setFixedSize(14, 14)
        for widget in (self._icon, self._title, self._status, self._chevron):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            header_layout.addWidget(widget, 1 if widget is self._title else 0)
        self._layout.addWidget(self._header)
        self._header.toggled.connect(self._toggle_details)
        self._update_status()
        bind_theme(self, self._render_theme)

    def finish(self, result: ToolResult) -> None:
        if result.call_id != self.call.id or self.result is not None:
            return
        self.result = result
        self._update_status()
        if self._details is not None:
            self._fill_details()
        self._render_theme()

    def snapshot(self) -> dict:
        entry: dict = {
            "kind": "tool",
            "call": asdict(self.call),
            "result": asdict(self.result) if self.result else None,
        }
        if self.app_html:
            entry["app_html"] = self.app_html
        if responses := self.app_results.snapshot():
            entry["app_results"] = responses
        return entry

    def attach_app(self, widget: MCPAppWidget) -> None:
        self.release_app()
        self._app = widget
        self._layout.insertWidget(1, widget)

    def freeze_app(self) -> None:
        if self._app is not None:
            self._app.set_read_only(self.app_results)

    def release_app(self) -> None:
        if self._app is not None:
            self._layout.removeWidget(self._app)
            self._app.hide()
            self._app.deleteLater()
            self._app = None

    def deleteLater(self) -> None:  # noqa: N802
        # Parent destruction alone does not call the Python MCPAppWidget
        # override which releases its HTTP content and fullscreen window.
        self.release_app()
        self._icon._timer.stop()
        super().deleteLater()

    def _update_status(self) -> None:
        status = self.result.status if self.result else "running"
        self._status.setText(_STATUS[status])
        self._icon.set_status(status)
        self._header.setAccessibleName(f"{tool_title(self.call.name)} — {_STATUS[status]}")
        self._header.setToolTip(f"{self.call.name}\nShow or hide details")

    def _toggle_details(self, expanded: bool) -> None:
        if expanded and self._details is None:
            self._details = QPlainTextEdit(self)
            self._details.setReadOnly(True)
            self._details.setAccessibleName(f"Details for {tool_title(self.call.name)}")
            self._details.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
            self._details.setFixedHeight(210)
            self._layout.addWidget(self._details)
            self._fill_details()
        if self._details is not None:
            self._details.setVisible(expanded)
        self._header.setAccessibleDescription(
            "Details expanded" if expanded else "Details collapsed"
        )
        self._render_theme()

    def _fill_details(self) -> None:
        assert self._details is not None
        source = f"\nSource: {self.call.server_name}" if self.call.server_name else ""
        result = _preview(self.result.text) if self.result else "Waiting for the result…"
        self._details.setPlainText(
            f"Tool: {self.call.name}{source}\n\nInput\n{_preview(self.call.arguments_json)}"
            f"\n\nResult\n{result}"
        )

    def _render_theme(self) -> None:
        c = colors()
        self.setStyleSheet(
            f"QFrame#toolActivity {{ background: {c['BG_SECONDARY']}; border: none;"
            " border-radius: 14px; margin: 0 16px; }"
        )
        self._header.setStyleSheet(
            "QPushButton#toolHeader { background: transparent; border: 1px solid transparent;"
            " border-radius: 14px; padding: 0; }"
            f"QPushButton#toolHeader:hover {{ background: {c['BG_TERTIARY']}; }}"
            'QPushButton#toolHeader[keyboardFocus="true"] {'
            f" border-color: {c['ACCENT_BRAND']}; }}"
        )
        self._title.setStyleSheet(
            f"color: {c['TEXT_PRIMARY']}; background: transparent;"
            " font-size: 13px; font-weight: 500;"
        )
        status_color = (
            c["ACCENT_RED"]
            if self.result and self.result.status == "failed"
            else c["TEXT_SECONDARY"]
        )
        self._status.setStyleSheet(
            f"color: {status_color}; background: transparent; font-size: 11px;"
        )
        self._chevron.setStyleSheet("background: transparent;")
        self._chevron.setPixmap(
            svg_icon(
                "chevron-down" if self._header.isChecked() else "chevron-right",
                c["TEXT_SECONDARY"],
                14,
            ).pixmap(14, 14)
        )
        self._icon.update()
        if self._details is not None:
            self._details.setStyleSheet(
                f"QPlainTextEdit {{ background: transparent; color: {c['TEXT_SECONDARY']};"
                f" border: none; border-top: 1px solid {c['BG_TERTIARY']};"
                " padding: 10px; font-size: 12px;"
                f" selection-background-color: {c['ACCENT_BRAND']}; }}"
            )
