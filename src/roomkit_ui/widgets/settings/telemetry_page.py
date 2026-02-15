"""Telemetry settings: provider selection and OTLP configuration."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

TELEMETRY_PROVIDERS = [
    ("Disabled", "none"),
    ("Console (logging)", "console"),
    ("OpenTelemetry (OTLP)", "otlp"),
]

OTLP_PROTOCOLS = [
    ("gRPC", "grpc"),
    ("HTTP/protobuf", "http"),
]


class _TelemetryPage(QWidget):
    """Telemetry settings: provider selection + OTLP configuration."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        c = colors()

        title = QLabel("Telemetry")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel("Collect timing and usage spans for STT, TTS, LLM, and pipeline stages.")
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        # Provider selector
        provider_section = QLabel("Provider")
        provider_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(provider_section)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.provider = QComboBox()
        for label, _value in TELEMETRY_PROVIDERS:
            self.provider.addItem(label)
        current = settings.get("telemetry_provider", "none")
        for i, (_, val) in enumerate(TELEMETRY_PROVIDERS):
            if val == current:
                self.provider.setCurrentIndex(i)
                break
        form.addRow("Backend", self.provider)

        self._console_hint = QLabel(
            "Logs span summaries to the Python logger (roomkit.telemetry). "
            "Useful for development and debugging."
        )
        self._console_hint.setWordWrap(True)
        self._console_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        form.addRow("", self._console_hint)

        layout.addLayout(form)

        # ── OTLP Configuration ──
        self._otlp_section = QLabel("OpenTelemetry")
        self._otlp_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(self._otlp_section)

        self._otlp_form_container = QWidget()
        otlp_form = QFormLayout(self._otlp_form_container)
        otlp_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        otlp_form.setContentsMargins(0, 0, 0, 0)
        otlp_form.setSpacing(10)
        otlp_form.setLabelAlignment(Qt.AlignRight)

        self.otlp_endpoint = QLineEdit(settings.get("otlp_endpoint", ""))
        self.otlp_endpoint.setPlaceholderText("http://localhost:4317")
        otlp_form.addRow("Endpoint", self.otlp_endpoint)

        self.otlp_protocol = QComboBox()
        for label, _value in OTLP_PROTOCOLS:
            self.otlp_protocol.addItem(label)
        current_proto = settings.get("otlp_protocol", "grpc")
        for i, (_, val) in enumerate(OTLP_PROTOCOLS):
            if val == current_proto:
                self.otlp_protocol.setCurrentIndex(i)
                break
        otlp_form.addRow("Protocol", self.otlp_protocol)

        self.otlp_service_name = QLineEdit(settings.get("otlp_service_name", "roomkit-ui"))
        self.otlp_service_name.setPlaceholderText("roomkit-ui")
        otlp_form.addRow("Service Name", self.otlp_service_name)

        self._otlp_hint = QLabel(
            "Exports traces via OTLP to collectors like Jaeger, Grafana Tempo, "
            "or any OpenTelemetry-compatible backend.\n"
            "Requires: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp"
        )
        self._otlp_hint.setWordWrap(True)
        self._otlp_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        otlp_form.addRow("", self._otlp_hint)

        layout.addWidget(self._otlp_form_container)

        layout.addStretch()

        # Wire visibility
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        self._on_provider_changed(self.provider.currentIndex())

    def _on_provider_changed(self, index: int) -> None:
        prov = TELEMETRY_PROVIDERS[index][1]
        is_otlp = prov == "otlp"
        is_console = prov == "console"
        self._console_hint.setVisible(is_console)
        self._otlp_section.setVisible(is_otlp)
        self._otlp_form_container.setVisible(is_otlp)

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "telemetry_provider": TELEMETRY_PROVIDERS[self.provider.currentIndex()][1],
            "otlp_endpoint": self.otlp_endpoint.text().strip(),
            "otlp_protocol": OTLP_PROTOCOLS[self.otlp_protocol.currentIndex()][1],
            "otlp_service_name": self.otlp_service_name.text().strip() or "roomkit-ui",
        }
