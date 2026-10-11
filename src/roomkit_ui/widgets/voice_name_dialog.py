"""Ask who a voice is: a name typed, or picked among the people already known."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QInputDialog, QWidget


def ask_voice_name(
    parent: QWidget | None, voice: str, current: str, known: list[str]
) -> str | None:
    """The name the user gives *voice* ("Speaker B"); "" gives it back its
    label; None when the dialog is dismissed.

    *current* is what the voice is called now, *known* the names to offer:
    enrolled speakers and the names already given in this session.
    """
    dialog = QInputDialog(parent)
    dialog.setWindowTitle("Who is this?")
    dialog.setLabelText(f"Name for {voice} (leave empty to show “{voice}” again):")
    dialog.setComboBoxEditable(True)
    dialog.setComboBoxItems(known)
    dialog.setTextValue("" if current == voice else current)
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        return " ".join(dialog.textValue().split())
    finally:
        dialog.deleteLater()
