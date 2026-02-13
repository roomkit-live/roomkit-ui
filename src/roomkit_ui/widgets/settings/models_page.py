"""AI Models catalog: browse, download, and delete local STT/TTS/VAD models."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors


class _ModelRow(QWidget):
    """A single row in the local model list: radio + name + type + size + action + progress."""

    def __init__(self, model, c: dict, show_radio: bool = True, parent=None) -> None:
        super().__init__(parent)
        from roomkit_ui.model_manager import is_model_downloaded

        self.model = model
        self._c = c

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Top line: radio + info + buttons
        top = QHBoxLayout()
        top.setSpacing(8)

        self.radio = QRadioButton()
        if not show_radio:
            self.radio.hide()
        top.addWidget(self.radio)

        name_label = QLabel(model.name)
        name_label.setStyleSheet("font-size: 13px; font-weight: 500; background: transparent;")
        top.addWidget(name_label)

        type_label = QLabel(model.type)
        type_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" background: {c['BG_TERTIARY']}; border-radius: 4px;"
            f" padding: 1px 6px;"
        )
        top.addWidget(type_label)

        size_label = QLabel(model.size)
        size_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        top.addWidget(size_label)

        top.addStretch()

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {c['ACCENT_GREEN']}; background: transparent;"
        )
        top.addWidget(self.status_label)

        self.action_btn = QPushButton()
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setFixedHeight(26)
        top.addWidget(self.action_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedHeight(26)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
            f" background: transparent; border: 1px solid {c['ACCENT_RED']};"
            f" color: {c['ACCENT_RED']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {c['ACCENT_RED']};"
            f" color: white; }}"
        )
        top.addWidget(self.delete_btn)

        outer.addLayout(top)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {c['BG_TERTIARY']};"
            f" border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {c['ACCENT_BLUE']};"
            f" border-radius: 3px; }}"
        )
        self.progress_bar.hide()
        outer.addWidget(self.progress_bar)

        self._refresh_state(is_model_downloaded(model.id))

    def _refresh_state(self, downloaded: bool) -> None:
        c = self._c
        self.progress_bar.hide()
        if downloaded:
            self.status_label.setText("\u2713 Ready")
            self.status_label.setStyleSheet(
                f"font-size: 12px; color: {c['ACCENT_GREEN']}; background: transparent;"
            )
            self.action_btn.hide()
            self.delete_btn.show()
        else:
            self.status_label.setText("")
            self.action_btn.setText("Download")
            self.action_btn.setStyleSheet(
                f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
                f" background: {c['ACCENT_BLUE']}; color: white;"
                f" border: none; border-radius: 4px; }}"
                f"QPushButton:hover {{ opacity: 0.8; }}"
            )
            self.action_btn.setEnabled(True)
            self.action_btn.show()
            self.delete_btn.hide()

    def set_downloading(self, pct: int) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.show()
        self.status_label.setText(f"{pct}%")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
        )

    def set_resolving(self) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.show()
        self.status_label.setText("Resolving\u2026")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
        )

    def set_downloaded(self) -> None:
        self.progress_bar.setRange(0, 100)  # restore determinate mode
        self._refresh_state(True)

    def set_not_downloaded(self) -> None:
        self.progress_bar.setRange(0, 100)
        self._refresh_state(False)

    def set_error(self) -> None:
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 100)
        self.action_btn.setText("Retry")
        self.action_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
            f" background: {self._c['ACCENT_BLUE']}; color: white;"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ opacity: 0.8; }}"
        )
        self.action_btn.setEnabled(True)
        self.action_btn.show()
        self.status_label.setText("Error")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['ACCENT_RED']}; background: transparent;"
        )


class _ModelsPage(QWidget):
    """AI Models catalog: browse, download, and delete local STT models."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        c = colors()

        title = QLabel("AI Models")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Download local speech-to-text models for offline dictation. "
            "Downloaded models will appear in the Dictation settings."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        model_section = QLabel("Available Models")
        model_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(model_section)

        model_frame = QWidget()
        model_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        frame_layout = QVBoxLayout(model_frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        frame_layout.setSpacing(0)

        from roomkit_ui.model_manager import STT_MODELS

        self._model_rows: list[_ModelRow] = []
        for model in STT_MODELS:
            row = _ModelRow(model, c, show_radio=False)
            row.action_btn.clicked.connect(
                lambda _checked=False, m=model.id: self._download_model(m)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, m=model.id: self._delete_model(m)
            )
            frame_layout.addWidget(row)
            self._model_rows.append(row)

        layout.addWidget(model_frame)

        # -- Denoiser Models section -----------------------------------------
        denoise_section = QLabel("Denoiser Models")
        denoise_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(denoise_section)

        from roomkit_ui.model_manager import (
            GTCRN_MODEL_ID,
            GTCRN_SIZE,
            is_gtcrn_downloaded,
        )

        @dataclass(frozen=True)
        class _DenoiserModel:
            id: str
            name: str
            type: str
            size: str

        gtcrn_info = _DenoiserModel(
            id=GTCRN_MODEL_ID,
            name="GTCRN",
            type="denoiser",
            size=GTCRN_SIZE,
        )

        denoise_frame = QWidget()
        denoise_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        denoise_frame_layout = QVBoxLayout(denoise_frame)
        denoise_frame_layout.setContentsMargins(4, 4, 4, 4)
        denoise_frame_layout.setSpacing(0)

        self._gtcrn_row = _ModelRow(gtcrn_info, c, show_radio=False)
        # Override the initial state check since _ModelRow uses is_model_downloaded
        self._gtcrn_row._refresh_state(is_gtcrn_downloaded())
        self._gtcrn_row.action_btn.clicked.connect(self._download_gtcrn)
        self._gtcrn_row.delete_btn.clicked.connect(self._delete_gtcrn)
        denoise_frame_layout.addWidget(self._gtcrn_row)

        layout.addWidget(denoise_frame)

        # -- VAD Models section -------------------------------------------------
        vad_section = QLabel("Voice Activity Detection Models")
        vad_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(vad_section)

        vad_desc = QLabel(
            "Download a VAD model for Voice Channel mode. "
            "Required to detect speech segments for offline STT models."
        )
        vad_desc.setWordWrap(True)
        vad_desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(vad_desc)

        vad_frame = QWidget()
        vad_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        vad_frame_layout = QVBoxLayout(vad_frame)
        vad_frame_layout.setContentsMargins(4, 4, 4, 4)
        vad_frame_layout.setSpacing(0)

        from roomkit_ui.model_manager import VAD_MODELS, is_vad_model_downloaded

        self._vad_rows: list[_ModelRow] = []
        for vad_m in VAD_MODELS:
            row = _ModelRow(vad_m, c, show_radio=False)
            row._refresh_state(is_vad_model_downloaded(vad_m.id))
            row.action_btn.clicked.connect(
                lambda _checked=False, mid=vad_m.id: self._download_vad_model(mid)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, mid=vad_m.id: self._delete_vad_model(mid)
            )
            vad_frame_layout.addWidget(row)
            self._vad_rows.append(row)

        layout.addWidget(vad_frame)

        # -- TTS Models section -------------------------------------------------
        tts_section = QLabel("Text-to-Speech Models")
        tts_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(tts_section)

        tts_desc = QLabel(
            "Download local TTS models for Voice Channel mode. "
            "espeak-ng data is a shared dependency required by all Piper models."
        )
        tts_desc.setWordWrap(True)
        tts_desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(tts_desc)

        tts_frame = QWidget()
        tts_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        tts_frame_layout = QVBoxLayout(tts_frame)
        tts_frame_layout.setContentsMargins(4, 4, 4, 4)
        tts_frame_layout.setSpacing(0)

        # espeak-ng-data row (shared dependency)
        from roomkit_ui.model_manager import is_espeak_ng_downloaded

        @dataclass(frozen=True)
        class _EspeakInfo:
            id: str
            name: str
            type: str
            size: str

        espeak_info = _EspeakInfo(
            id="espeak-ng-data",
            name="espeak-ng data",
            type="shared",
            size="~1 MB",
        )
        self._espeak_row = _ModelRow(espeak_info, c, show_radio=False)
        self._espeak_row._refresh_state(is_espeak_ng_downloaded())
        self._espeak_row.action_btn.clicked.connect(self._download_espeak)
        self._espeak_row.delete_btn.clicked.connect(self._delete_espeak)
        tts_frame_layout.addWidget(self._espeak_row)

        # TTS model rows
        from roomkit_ui.model_manager import TTS_MODELS, is_tts_model_downloaded

        @dataclass(frozen=True)
        class _TTSInfo:
            id: str
            name: str
            type: str
            size: str

        self._tts_rows: list[_ModelRow] = []
        for tts_m in TTS_MODELS:
            info = _TTSInfo(id=tts_m.id, name=tts_m.name, type="tts", size=tts_m.size)
            row = _ModelRow(info, c, show_radio=False)
            row._refresh_state(is_tts_model_downloaded(tts_m.id))
            row.action_btn.clicked.connect(
                lambda _checked=False, mid=tts_m.id: self._download_tts_model(mid)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, mid=tts_m.id: self._delete_tts_model(mid)
            )
            tts_frame_layout.addWidget(row)
            self._tts_rows.append(row)

        layout.addWidget(tts_frame)
        layout.addStretch()

    def _find_row(self, model_id: str) -> _ModelRow | None:
        for row in self._model_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_model

        row = self._find_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("Model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_model(self, model_id: str) -> None:
        from roomkit_ui.model_manager import delete_model

        delete_model(model_id)
        row = self._find_row(model_id)
        if row is not None:
            row.set_not_downloaded()

    def _download_gtcrn(self) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_gtcrn

        row = self._gtcrn_row
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_gtcrn(_progress)
                row.set_downloaded()
            except Exception:
                logging.exception("GTCRN download failed")
                row.set_error()

        loop.create_task(_run())

    def _delete_gtcrn(self) -> None:
        from roomkit_ui.model_manager import delete_gtcrn

        delete_gtcrn()
        self._gtcrn_row.set_not_downloaded()

    # -- TTS model handlers --------------------------------------------------

    def _find_tts_row(self, model_id: str) -> _ModelRow | None:
        for row in self._tts_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_espeak(self) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_espeak_ng_data

        row = self._espeak_row
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_espeak_ng_data(_progress)
                row.set_downloaded()
            except Exception:
                logging.exception("espeak-ng-data download failed")
                row.set_error()

        loop.create_task(_run())

    def _delete_espeak(self) -> None:
        from roomkit_ui.model_manager import delete_espeak_ng_data

        delete_espeak_ng_data()
        self._espeak_row.set_not_downloaded()

    def _download_tts_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_tts_model

        row = self._find_tts_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_tts_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("TTS model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_tts_model(self, model_id: str) -> None:
        from roomkit_ui.model_manager import delete_tts_model

        delete_tts_model(model_id)
        row = self._find_tts_row(model_id)
        if row is not None:
            row.set_not_downloaded()

    # -- VAD model handlers --------------------------------------------------

    def _find_vad_row(self, model_id: str) -> _ModelRow | None:
        for row in self._vad_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_vad_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_vad_model

        row = self._find_vad_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_vad_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("VAD model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_vad_model(self, model_id: str) -> None:
        from roomkit_ui.model_manager import delete_vad_model

        delete_vad_model(model_id)
        row = self._find_vad_row(model_id)
        if row is not None:
            row.set_not_downloaded()
