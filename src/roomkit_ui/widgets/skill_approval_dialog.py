"""Ask the user whether a program may run on behalf of a skill an MCP server serves."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from roomkit_ui.skill_approval import SkillApproval


def show_skill_approval(parent: QWidget | None, approval: SkillApproval) -> QMessageBox:
    """Open the question beside the conversation, without blocking it.

    The answer settles *approval*; an approval settled elsewhere (no answer
    in time, the session ended) closes the box.  Refuse is the default and
    what Esc gives.
    """
    box = QMessageBox(parent)
    box.setWindowTitle("Allow this skill to run programs?")
    box.setIcon(QMessageBox.Question)
    # The skill's name comes from its server: shown as text, never markup.
    box.setTextFormat(Qt.PlainText)
    box.setText(approval.question)
    allow = box.addButton("Allow", QMessageBox.AcceptRole)
    refuse = box.addButton("Refuse", QMessageBox.RejectRole)
    box.setDefaultButton(refuse)
    box.setEscapeButton(refuse)
    box.setAttribute(Qt.WA_DeleteOnClose)
    box.finished.connect(lambda _result: approval.answer(box.clickedButton() is allow))

    def close_when_settled(_future: object) -> None:
        try:
            if box.isVisible():
                box.reject()
        except RuntimeError:
            pass  # already answered and deleted

    approval.future.add_done_callback(close_when_settled)
    box.open()
    return box
