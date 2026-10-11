"""At-a-glance view of the actual transcription → reasoning → speech providers."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.controls import label


class PipelineSummary(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAccessibleName("Voice Channel processing order")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.providers = []
        for index, title in enumerate(("TRANSCRIBE", "REASON", "SPEAK")):
            if index:
                arrow = label("→", "settingsHint")
                arrow.setAlignment(Qt.AlignCenter)
                layout.addWidget(arrow)
            card = QFrame()
            card.setObjectName("settingsPipelineStep")
            card.setMinimumHeight(76)
            body = QVBoxLayout(card)
            body.setContentsMargins(14, 14, 14, 14)
            body.setSpacing(8)
            body.addWidget(label(f"0{index + 1} · {title}", "settingsPipelineCaption"))
            provider = label("", "settingsRowTitle")
            body.addWidget(provider)
            self.providers.append(provider)
            layout.addWidget(card, 1)

    def set_providers(self, transcription: str, reasoning: str, speech: str) -> None:
        for widget, value in zip(self.providers, (transcription, reasoning, speech), strict=True):
            widget.setText(value)
