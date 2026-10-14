"""A missing component, said where it is missing, with the button that adds it.

Under a provider combo whose choice is not installed, and in the chat when a
session could not start for want of one.  It follows the app's one installer
(``component_installer``), so the Components tab, a combo and the chat all
show the same install running.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from roomkit_ui.component_installer import installer
from roomkit_ui.components import Component, Installer, component_of, install_plan
from roomkit_ui.features import FEATURES
from roomkit_ui.theme_live import themed_style


class InstallOffer(QWidget):
    """Says a feature is not installed, next to the button that adds it."""

    # The extra just installed: whoever shows its features can relabel them.
    installed = Signal(str)

    def __init__(
        self,
        feature: str | None = None,
        parent: QWidget | None = None,
        *,
        color: str = "",
        done_hint: str = "",
    ) -> None:
        """*color* for the text (muted by default); *done_hint* follows the
        installer's message once the component is in ("Start the session again.")."""
        super().__init__(parent)
        self._component: Component | None = None
        self._shown = False
        self._text = ""
        self._done_hint = done_hint
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setWordWrap(True)
        themed_style(
            self._label,
            lambda c: (
                f"font-size: 12px; color: {c.get(color, color) or c['TEXT_SECONDARY']};"
                " background: transparent;"
            ),
        )
        layout.addWidget(self._label, 1)
        self._button = QPushButton()
        self._button.clicked.connect(self._act)
        layout.addWidget(self._button)

        runner = installer()
        runner.started.connect(self._on_started)
        runner.finished.connect(self._on_finished)
        self.set_feature(feature)

    def set_feature(self, feature: str | None, text: str = "") -> None:
        """Offer the component of *feature*; nothing when none or it is installed.

        *text* replaces the default "<feature> is not installed." line.
        """
        component = component_of(feature) if feature else None
        if component is not None and component.installed():
            component = None
        self._component = component
        self._text = text or (f"{FEATURES[feature].label} is not installed." if feature else "")
        self._show()

    def _set_shown(self, shown: bool) -> None:
        """setVisible, except that an offer not yet in a layout never opens as a window.

        Callers build the offer before placing it, and showing a parentless
        widget opens it as a window of its own (a flash on Windows): the
        state waits for its parent (changeEvent).
        """
        self._shown = shown
        if self.parentWidget() is not None or not shown:
            self.setVisible(shown)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.ParentChange and self.parentWidget() is not None:
            self.setVisible(self._shown)
        super().changeEvent(event)

    def _show(self) -> None:
        component = self._component
        self._set_shown(component is not None)
        if component is None:
            return
        plan = install_plan(component)
        running = installer().running
        if running is not None and running.extra == component.extra:
            self._label.setText(f"Installing {component.title}…")
            self._button.setVisible(False)
            return
        note = f" {plan.note}" if plan.how is Installer.NONE else ""
        self._label.setText(self._text + note)
        self._button.setVisible(plan.how is not Installer.NONE)
        self._button.setText("Install" if plan.how is Installer.APP else "Copy command")
        self._button.setToolTip(plan.command)
        self._button.setEnabled(plan.how is not Installer.APP or running is None)

    def _act(self) -> None:
        if self._component is None:
            return
        plan = install_plan(self._component)
        if plan.how is Installer.COMMAND:
            QApplication.clipboard().setText(plan.command)
            self._button.setText("Copied")
            return
        if plan.conflicts:
            # The Components tab asks what to give up; one click here must not.
            self._label.setText(
                f"{self._component.title} would break {', '.join(plan.conflicts)}: "
                "install it from Settings → Models & components → Components."
            )
            return
        installer().install(self._component)

    def _on_started(self, _extra: str) -> None:
        self._show()

    def _on_finished(self, extra: str, ok: bool, message: str) -> None:
        component = self._component
        if component is None or component.extra != extra:
            self._show()  # another install ended: Install is clickable again
            return
        if ok and component.installed():
            self._component = None
            self._set_shown(True)
            self._label.setText(f"{message} {self._done_hint}".strip())
            self._button.setVisible(False)
            self.installed.emit(extra)
            return
        self._show()
        self._label.setText(message)
