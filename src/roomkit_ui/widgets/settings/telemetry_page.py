"""Telemetry destination and optional OTLP export configuration."""

from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.controls import SettingsForm, SettingsSection, label
from roomkit_ui.widgets.settings.feature_hints import (
    offer_install,
    populate_provider_combo,
    refresh_provider_combo,
)

TELEMETRY_PROVIDERS = [
    ("Disabled", "none"),
    ("Local logs", "console"),
    ("OpenTelemetry (OTLP)", "otlp"),
]
OTLP_PROTOCOLS = [("gRPC", "grpc"), ("HTTP/protobuf", "http")]
_FEATURES = {"otlp": "telemetry"}


class _TelemetryPage(QWidget):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        destination = SettingsSection(
            "Trace destination",
            "Inspect timing and usage for speech recognition, responses and audio processing.",
        )
        destination.content.setContentsMargins(18, 16, 18, 16)
        form = SettingsForm()
        self.provider = QComboBox()
        populate_provider_combo(self.provider, TELEMETRY_PROVIDERS, _FEATURES)
        for index, (_, value) in enumerate(TELEMETRY_PROVIDERS):
            if value == settings.get("telemetry_provider", "none"):
                self.provider.setCurrentIndex(index)
        form.addRow("Send traces to", self.provider)
        self.hint = label("", "settingsHint")
        form.addWidget(self.hint)
        self.install_offer = offer_install(self.provider, TELEMETRY_PROVIDERS, _FEATURES)
        form.addWidget(self.install_offer)
        destination.content.addLayout(form)
        layout.addWidget(destination)
        self.export = SettingsSection(
            "Collector connection",
            "Exports session traces to the collector you configure. "
            "Changes apply to the next session.",
        )
        self.export.content.setContentsMargins(18, 16, 18, 16)
        fields = SettingsForm()
        self.otlp_protocol = QComboBox()
        for title, value in OTLP_PROTOCOLS:
            self.otlp_protocol.addItem(title, value)
        self.otlp_protocol.setCurrentIndex(
            max(0, self.otlp_protocol.findData(settings.get("otlp_protocol", "grpc")))
        )
        fields.addRow("Protocol", self.otlp_protocol)
        self.otlp_endpoint = QLineEdit(settings.get("otlp_endpoint", ""))
        fields.addRow("Collector endpoint", self.otlp_endpoint)
        fields.addWidget(
            label("Leave blank to use the local address shown above.", "settingsHint")
        )
        self.otlp_service_name = QLineEdit(settings.get("otlp_service_name", "roomkit-ui"))
        self.otlp_service_name.setPlaceholderText("roomkit-ui")
        fields.addRow("Service name", self.otlp_service_name)
        self.export.content.addLayout(fields)
        layout.addWidget(self.export)
        self.provider.currentIndexChanged.connect(self._update_provider)
        self.otlp_protocol.currentIndexChanged.connect(self._update_endpoint)
        self._update_provider()
        self._update_endpoint()

    def _update_provider(self) -> None:
        provider = TELEMETRY_PROVIDERS[self.provider.currentIndex()][1]
        self.export.setVisible(provider == "otlp")
        self.hint.setText(
            {
                "none": "No diagnostic traces are collected. "
                "Audio capture is configured separately.",
                "console": "Writes trace summaries to the local application logs "
                "(roomkit.telemetry). Applies to the next session.",
                "otlp": "Requires the OpenTelemetry component. "
                "If it is missing, the app falls back to local logs.",
            }[provider]
        )

    def _update_endpoint(self) -> None:
        self.otlp_endpoint.setPlaceholderText(
            "http://localhost:4318/v1/traces"
            if self.otlp_protocol.currentData() == "http"
            else "http://localhost:4317"
        )

    def refresh(self) -> None:
        refresh_provider_combo(self.provider, TELEMETRY_PROVIDERS, _FEATURES)
        self.install_offer.set_feature(
            _FEATURES.get(TELEMETRY_PROVIDERS[self.provider.currentIndex()][1])
        )

    def get_settings(self) -> dict:
        return {
            "telemetry_provider": TELEMETRY_PROVIDERS[self.provider.currentIndex()][1],
            "otlp_endpoint": self.otlp_endpoint.text().strip(),
            "otlp_protocol": self.otlp_protocol.currentData(),
            "otlp_service_name": self.otlp_service_name.text().strip() or "roomkit-ui",
        }
