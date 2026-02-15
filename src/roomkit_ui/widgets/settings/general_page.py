"""General settings: audio device selection, theme, hotkey, audio processing."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.hotkey_button import HotkeyButton

THEMES = [
    ("Dark", "dark"),
    ("Light", "light"),
]

AEC_MODES = [
    ("WebRTC (recommended)", "webrtc"),
    ("Speex", "speex"),
    ("None", "none"),
]

DENOISE_MODES = [
    ("None", "none"),
    ("RNNoise (Linux/macOS)", "rnnoise"),
    ("GTCRN (cross-platform)", "gtcrn"),
]


def _list_audio_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (input_devices, output_devices) as lists of (index, name)."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs: list[tuple[int, str]] = []
        outputs: list[tuple[int, str]] = []
        for i, d in enumerate(devices):
            name = d["name"]
            if d["max_input_channels"] > 0:
                inputs.append((i, name))
            if d["max_output_channels"] > 0:
                outputs.append((i, name))
        return inputs, outputs
    except Exception:
        return [], []


class _GeneralPage(QWidget):
    """General settings: audio device selection + theme."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        c = colors()

        title = QLabel("General")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # Theme selector
        theme_section = QLabel("Appearance")
        theme_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(theme_section)

        theme_form = QFormLayout()
        theme_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        theme_form.setSpacing(10)
        theme_form.setLabelAlignment(Qt.AlignRight)
        self.theme_combo = QComboBox()
        for label, _value in THEMES:
            self.theme_combo.addItem(label)
        current_theme = settings.get("theme", "dark")
        for i, (_, val) in enumerate(THEMES):
            if val == current_theme:
                self.theme_combo.setCurrentIndex(i)
                break
        theme_form.addRow("Theme", self.theme_combo)
        layout.addLayout(theme_form)

        # Assistant hotkey
        hotkey_section = QLabel("Assistant Hotkey")
        hotkey_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(hotkey_section)

        hotkey_form = QFormLayout()
        hotkey_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        hotkey_form.setSpacing(10)
        hotkey_form.setLabelAlignment(Qt.AlignRight)

        self.assistant_hotkey_enabled = QCheckBox("Enable global hotkey to start/stop session")
        self.assistant_hotkey_enabled.setChecked(
            bool(settings.get("assistant_hotkey_enabled", True))
        )
        hotkey_form.addRow("", self.assistant_hotkey_enabled)

        self.assistant_hotkey = HotkeyButton()
        self.assistant_hotkey.set_value(settings.get("assistant_hotkey", "<ctrl>+<shift>+a"))
        hotkey_form.addRow("Hotkey", self.assistant_hotkey)

        hotkey_hint = QLabel("Press the button, then press your desired key combination.")
        hotkey_hint.setWordWrap(True)
        hotkey_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        hotkey_form.addRow("", hotkey_hint)

        layout.addLayout(hotkey_form)

        # Audio devices
        section = QLabel("Audio Devices")
        section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(section)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        inputs, outputs = _list_audio_devices()

        self.input_combo = QComboBox()
        self.input_combo.addItem("System Default", None)
        for idx, name in inputs:
            self.input_combo.addItem(name, idx)
        saved_input = settings.get("input_device")
        if saved_input is not None:
            for i in range(self.input_combo.count()):
                if self.input_combo.itemData(i) == saved_input:
                    self.input_combo.setCurrentIndex(i)
                    break
        form.addRow("Microphone", self.input_combo)

        self.output_combo = QComboBox()
        self.output_combo.addItem("System Default", None)
        for idx, name in outputs:
            self.output_combo.addItem(name, idx)
        saved_output = settings.get("output_device")
        if saved_output is not None:
            for i in range(self.output_combo.count()):
                if self.output_combo.itemData(i) == saved_output:
                    self.output_combo.setCurrentIndex(i)
                    break
        form.addRow("Speaker", self.output_combo)

        layout.addLayout(form)

        # Audio processing
        proc_section = QLabel("Audio Processing")
        proc_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(proc_section)

        proc_form = QFormLayout()
        proc_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        proc_form.setSpacing(10)
        proc_form.setLabelAlignment(Qt.AlignRight)

        # AEC
        self.aec = QComboBox()
        for label, _value in AEC_MODES:
            self.aec.addItem(label)
        current_aec = settings.get("aec_mode", "webrtc")
        for i, (_, val) in enumerate(AEC_MODES):
            if val == current_aec:
                self.aec.setCurrentIndex(i)
                break
        proc_form.addRow("Echo Cancel", self.aec)

        # Denoise
        self.denoise = QComboBox()
        for label, _value in DENOISE_MODES:
            self.denoise.addItem(label)
        current_denoise = settings.get("denoise", "none")
        for i, (_, val) in enumerate(DENOISE_MODES):
            if val == current_denoise:
                self.denoise.setCurrentIndex(i)
                break
        proc_form.addRow("Denoise", self.denoise)

        # VAD model (used by both voice channel STT and realtime diarization)
        from roomkit_ui.model_manager import VAD_MODELS, is_vad_model_downloaded

        self.vad_model = QComboBox()
        self.vad_model.addItem("None", "")
        for vm in VAD_MODELS:
            if is_vad_model_downloaded(vm.id):
                self.vad_model.addItem(vm.name, vm.id)
        saved_vad = settings.get("vc_vad_model", "")
        for i in range(self.vad_model.count()):
            if self.vad_model.itemData(i) == saved_vad:
                self.vad_model.setCurrentIndex(i)
                break
        proc_form.addRow("VAD", self.vad_model)

        self._vad_hint = QLabel("Voice activity detection — required for speaker diarization.")
        self._vad_hint.setWordWrap(True)
        self._vad_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        proc_form.addRow("", self._vad_hint)

        # ── VAD Advanced (collapsible) ──
        self._vad_adv_toggle = QPushButton("\u25b8 Advanced")
        self._vad_adv_toggle.setFlat(True)
        self._vad_adv_toggle.setCursor(Qt.PointingHandCursor)
        self._vad_adv_toggle.setStyleSheet(
            "text-align: left; font-size: 12px; font-weight: 600;"
            f" color: {c['TEXT_SECONDARY']}; background: transparent; border: none;"
            " padding: 2px 0;"
        )
        self._vad_adv_toggle.clicked.connect(self._toggle_vad_advanced)
        proc_form.addRow("", self._vad_adv_toggle)

        self._vad_adv_container = QWidget()
        vad_form = QFormLayout(self._vad_adv_container)
        vad_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        vad_form.setSpacing(10)
        vad_form.setLabelAlignment(Qt.AlignRight)

        self.vad_threshold = QLineEdit(str(settings.get("vad_threshold", "") or ""))
        self.vad_threshold.setPlaceholderText("0.35 (lower = more sensitive)")
        vad_form.addRow("Threshold", self.vad_threshold)

        self.vad_silence_ms = QLineEdit(str(settings.get("vad_silence_ms", "") or ""))
        self.vad_silence_ms.setPlaceholderText("500")
        vad_form.addRow("Silence (ms)", self.vad_silence_ms)

        self.vad_min_speech_ms = QLineEdit(str(settings.get("vad_min_speech_ms", "") or ""))
        self.vad_min_speech_ms.setPlaceholderText("250")
        vad_form.addRow("Min Speech (ms)", self.vad_min_speech_ms)

        self.vad_speech_pad_ms = QLineEdit(str(settings.get("vad_speech_pad_ms", "") or ""))
        self.vad_speech_pad_ms.setPlaceholderText("300")
        vad_form.addRow("Speech Pad (ms)", self.vad_speech_pad_ms)

        self.vad_energy_silence_rms = QLineEdit(
            str(settings.get("vad_energy_silence_rms", "") or "")
        )
        self.vad_energy_silence_rms.setPlaceholderText("20 (0 = disabled)")
        vad_form.addRow("Energy Silence", self.vad_energy_silence_rms)

        self._vad_adv_container.hide()
        proc_form.addRow("", self._vad_adv_container)

        self.vad_model.currentIndexChanged.connect(self._on_vad_changed)
        self._on_vad_changed(self.vad_model.currentIndex())

        # Turn detector (smart turn)
        from roomkit_ui.model_manager import is_smart_turn_downloaded

        self.turn_detector = QComboBox()
        self.turn_detector.addItem("None", "")
        if is_smart_turn_downloaded():
            self.turn_detector.addItem("Smart Turn v3", "smart-turn")
        saved_td = settings.get("vc_turn_detector", "")
        for i in range(self.turn_detector.count()):
            if self.turn_detector.itemData(i) == saved_td:
                self.turn_detector.setCurrentIndex(i)
                break
        proc_form.addRow("Turn Detector", self.turn_detector)

        self.turn_threshold = QLineEdit(str(settings.get("vc_turn_threshold", "") or ""))
        self.turn_threshold.setPlaceholderText("0.5 (0 = eager … 1 = patient)")
        self._turn_threshold_label = QLabel("Turn Threshold")
        proc_form.addRow(self._turn_threshold_label, self.turn_threshold)

        self._turn_hint = QLabel(
            "Audio-native turn completion — detects when the user has finished speaking "
            "from prosody alone. Download the model in AI Models tab."
        )
        self._turn_hint.setWordWrap(True)
        self._turn_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        proc_form.addRow("", self._turn_hint)

        self.turn_detector.currentIndexChanged.connect(self._on_turn_detector_changed)
        self._on_turn_detector_changed(self.turn_detector.currentIndex())

        # Inference device
        from roomkit_ui.model_manager import detect_providers

        self._inference_providers = detect_providers()
        self.inference_device = QComboBox()
        for label, _value in self._inference_providers:
            self.inference_device.addItem(label)
        current_device = settings.get("inference_device", "cpu")
        for i, (_, val) in enumerate(self._inference_providers):
            if val == current_device:
                self.inference_device.setCurrentIndex(i)
                break
        proc_form.addRow("Inference Device", self.inference_device)

        self._device_hint = QLabel()
        self._device_hint.setWordWrap(True)
        self._device_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        proc_form.addRow("", self._device_hint)
        self.inference_device.currentIndexChanged.connect(self._on_device_changed)
        self._on_device_changed(self.inference_device.currentIndex())

        layout.addLayout(proc_form)
        layout.addStretch()

    def _toggle_vad_advanced(self) -> None:
        visible = not self._vad_adv_container.isVisible()
        self._vad_adv_container.setVisible(visible)
        self._vad_adv_toggle.setText("\u25be Advanced" if visible else "\u25b8 Advanced")

    def _on_vad_changed(self, index: int) -> None:
        has_vad = bool(self.vad_model.currentData())
        self._vad_adv_toggle.setVisible(has_vad)
        if not has_vad:
            self._vad_adv_container.hide()
            self._vad_adv_toggle.setText("\u25b8 Advanced")

    def _on_turn_detector_changed(self, index: int) -> None:
        has_detector = bool(self.turn_detector.currentData())
        self._turn_threshold_label.setVisible(has_detector)
        self.turn_threshold.setVisible(has_detector)

    def _on_device_changed(self, index: int) -> None:
        val = self._inference_providers[index][1]
        if val == "cuda":
            self._device_hint.setText(
                "Affects local STT models only. Requires the sherpa-onnx CUDA wheel "
                "and cuDNN 9: uv pip install sherpa-onnx==1.12.23+cuda12.cudnn9 "
                "-f https://k2-fsa.github.io/sherpa/onnx/cuda.html"
            )
            self._device_hint.show()
        elif val == "coreml":
            self._device_hint.setText("Affects local STT models only.")
            self._device_hint.show()
        else:
            self._device_hint.hide()

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "theme": THEMES[self.theme_combo.currentIndex()][1],
            "aec_mode": AEC_MODES[self.aec.currentIndex()][1],
            "denoise": DENOISE_MODES[self.denoise.currentIndex()][1],
            "vc_vad_model": self.vad_model.currentData() or "",
            "vad_threshold": self.vad_threshold.text().strip(),
            "vad_silence_ms": self.vad_silence_ms.text().strip(),
            "vad_min_speech_ms": self.vad_min_speech_ms.text().strip(),
            "vad_speech_pad_ms": self.vad_speech_pad_ms.text().strip(),
            "vad_energy_silence_rms": self.vad_energy_silence_rms.text().strip(),
            "vc_turn_detector": self.turn_detector.currentData() or "",
            "vc_turn_threshold": self.turn_threshold.text().strip(),
            "inference_device": self._inference_providers[self.inference_device.currentIndex()][1],
            "input_device": self.input_combo.currentData(),
            "output_device": self.output_combo.currentData(),
            "assistant_hotkey_enabled": self.assistant_hotkey_enabled.isChecked(),
            "assistant_hotkey": self.assistant_hotkey.value(),
        }
