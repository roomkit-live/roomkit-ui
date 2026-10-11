"""Audio devices and processing settings for Audio & voice."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.features import TURN_DETECTOR_FEATURES
from roomkit_ui.widgets.settings.controls import AdvancedSection, SettingsForm, SettingsSection
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo

_TURN_HINT = (
    "Audio-native turn completion — detects when the user has finished speaking "
    "from prosody alone. Download the model in Models & components."
)

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


class AudioSettings(QWidget):
    def __init__(
        self,
        settings: dict,
        devices: tuple[list[tuple[int, str]], list[tuple[int, str]]],
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(28)

        devices_section = SettingsSection(
            "Devices", "Choose the microphone and output used for voice sessions."
        )
        layout.addWidget(devices_section)

        inputs, outputs = devices

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
        self.input_combo.setMaximumWidth(280)
        devices_section.add_row("Microphone", "Where your voice comes from.", self.input_combo)

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
        self.output_combo.setMaximumWidth(280)
        devices_section.add_row("Output", "Where the assistant speaks.", self.output_combo)
        for combo, saved in ((self.input_combo, saved_input), (self.output_combo, saved_output)):
            if saved is not None and combo.findData(saved) < 0:
                combo.addItem(f"Device {saved} (unavailable)", saved)
                combo.setCurrentIndex(combo.count() - 1)

        processing = SettingsSection(
            "Processing", "Echo cancellation and voice detection for clearer conversations."
        )
        processing.content.setContentsMargins(18, 18, 18, 18)
        proc_form = SettingsForm()
        processing.content.addLayout(proc_form)
        layout.addWidget(processing)

        # AEC
        self.aec = QComboBox()
        for label, _value in AEC_MODES:
            self.aec.addItem(label)
        current_aec = settings.get("aec_mode", "webrtc")
        for i, (_, val) in enumerate(AEC_MODES):
            if val == current_aec:
                self.aec.setCurrentIndex(i)
                break
        proc_form.addRow("Echo cancellation", self.aec)

        # Denoise
        self.denoise = QComboBox()
        for label, _value in DENOISE_MODES:
            self.denoise.addItem(label)
        current_denoise = settings.get("denoise", "none")
        for i, (_, val) in enumerate(DENOISE_MODES):
            if val == current_denoise:
                self.denoise.setCurrentIndex(i)
                break
        # Denoisers only apply to Voice Channel mode — in realtime they
        # suppress the user's barge-in speech during doubletalk.
        proc_form.addRow("Denoise (Voice Channel)", self.denoise)

        self.vad_model = QComboBox()
        proc_form.addRow("Voice detection", self.vad_model)

        self._vad_hint = QLabel("Voice activity detection — required for speaker diarization.")
        self._vad_hint.setWordWrap(True)
        self._vad_hint.setObjectName("settingsHint")
        proc_form.addRow(self._vad_hint)

        # ── VAD Advanced (collapsible) ──
        self._vad_adv_container = QWidget()
        vad_form = SettingsForm(self._vad_adv_container)

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
        self.vad_speech_pad_ms.setPlaceholderText("1000")
        vad_form.addRow("Speech Pad (ms)", self.vad_speech_pad_ms)

        self.vad_energy_silence_rms = QLineEdit(
            str(settings.get("vad_energy_silence_rms", "") or "")
        )
        self.vad_energy_silence_rms.setPlaceholderText("20 (0 = disabled)")
        vad_form.addRow("Energy Silence", self.vad_energy_silence_rms)

        self.vad_advanced = AdvancedSection("Voice detection tuning", self._vad_adv_container)
        proc_form.addRow(self.vad_advanced)

        self.vad_model.currentIndexChanged.connect(self._on_vad_changed)
        self._on_vad_changed(self.vad_model.currentIndex())

        self._add_turn_detector_fields(proc_form, settings)

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
        self._device_hint.setObjectName("settingsHint")
        proc_form.addRow(self._device_hint)
        self.inference_device.currentIndexChanged.connect(self._on_device_changed)
        self._on_device_changed(self.inference_device.currentIndex())

        self.refresh_models(settings.get("vc_vad_model", ""), settings.get("vc_turn_detector", ""))

    def refresh_models(self, vad: str | None = None, turn: str | None = None) -> None:
        from roomkit_ui.model_manager import (
            VAD_MODELS,
            is_smart_turn_downloaded,
            is_vad_model_downloaded,
        )

        vad = self.vad_model.currentData() if vad is None else vad
        turn = self.turn_detector.currentData() if turn is None else turn
        for combo, saved in ((self.vad_model, vad), (self.turn_detector, turn)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("None", "")
            if combo is self.vad_model:
                for model in VAD_MODELS:
                    if is_vad_model_downloaded(model.id):
                        combo.addItem(model.name, model.id)
            elif is_smart_turn_downloaded():
                populate_provider_combo(
                    combo, [("Smart Turn v3", "smart-turn")], TURN_DETECTOR_FEATURES
                )
                combo.setItemData(combo.count() - 1, "smart-turn")
            if saved and combo.findData(saved) < 0:
                combo.addItem(f"{saved} (model unavailable)", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved or "")))
            combo.blockSignals(False)
            combo.currentIndexChanged.emit(combo.currentIndex())

    def _on_vad_changed(self, index: int) -> None:
        has_vad = bool(self.vad_model.currentData())
        self.vad_advanced.setVisible(has_vad)
        if not has_vad:
            self.vad_advanced.set_expanded(False)

    def _add_turn_detector_fields(self, form: SettingsForm, settings: dict) -> None:
        """Turn detector (Smart Turn), its threshold and its wait for more speech."""
        self.turn_detector = QComboBox()
        self.turn_detector.addItem("None", "")
        form.addRow("Turn Detector", self.turn_detector)
        form.addRow(
            offer_install(
                self.turn_detector,
                [("Smart Turn v3", "smart-turn")],
                TURN_DETECTOR_FEATURES,
                offset=1,
            ),
        )

        self.turn_threshold = QLineEdit(str(settings.get("vc_turn_threshold", "") or ""))
        self.turn_threshold.setPlaceholderText("0.5 (0 = eager … 1 = patient)")
        self._turn_threshold_label = QLabel("Turn Threshold")
        form.addRow(self._turn_threshold_label, self.turn_threshold)

        self.turn_incomplete_wait = QLineEdit(
            str(settings.get("vc_turn_incomplete_wait_ms", "") or "")
        )
        self.turn_incomplete_wait.setPlaceholderText("1500")
        self.turn_incomplete_wait.setToolTip(
            "How long a turn judged unfinished waits for you to go on before it is answered."
        )
        self._turn_wait_label = QLabel("Unfinished Wait (ms)")
        form.addRow(self._turn_wait_label, self.turn_incomplete_wait)

        self._turn_hint = QLabel(_TURN_HINT)
        self._turn_hint.setWordWrap(True)
        self._turn_hint.setObjectName("settingsHint")
        form.addRow(self._turn_hint)

        self.turn_detector.currentIndexChanged.connect(self._on_turn_detector_changed)
        self._on_turn_detector_changed(self.turn_detector.currentIndex())

    def _on_turn_detector_changed(self, index: int) -> None:
        detector = self.turn_detector.currentData() or ""
        for widget in (
            self._turn_threshold_label,
            self.turn_threshold,
            self._turn_wait_label,
            self.turn_incomplete_wait,
        ):
            widget.setVisible(bool(detector))
        # A detector not installed is said, with its Install, by offer_install.
        self._turn_hint.setText(_TURN_HINT)

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
            "vc_turn_incomplete_wait_ms": self.turn_incomplete_wait.text().strip(),
            "inference_device": self._inference_providers[self.inference_device.currentIndex()][1],
            "input_device": self.input_combo.currentData(),
            "output_device": self.output_combo.currentData(),
        }
