"""AI Models catalog: browse, download, and delete local STT/TTS/VAD models."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.models_widgets import _ModelRow


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

        # -- Turn Detection section ---------------------------------------------
        turn_section = QLabel("Turn Detection Model")
        turn_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(turn_section)

        turn_desc = QLabel(
            "Audio-native turn completion detector (pipecat-ai/smart-turn). "
            "Analyzes prosody to decide when the user has finished speaking."
        )
        turn_desc.setWordWrap(True)
        turn_desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(turn_desc)

        turn_frame = QWidget()
        turn_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        turn_frame_layout = QVBoxLayout(turn_frame)
        turn_frame_layout.setContentsMargins(4, 4, 4, 4)
        turn_frame_layout.setSpacing(0)

        from roomkit_ui.model_manager import (
            SMART_TURN_MODEL_ID,
            SMART_TURN_SIZE,
            is_smart_turn_downloaded,
        )

        @dataclass(frozen=True)
        class _SmartTurnInfo:
            id: str
            name: str
            type: str
            size: str

        smart_turn_info = _SmartTurnInfo(
            id=SMART_TURN_MODEL_ID,
            name="Smart Turn v3.2 (CPU, int8)",
            type="turn",
            size=SMART_TURN_SIZE,
        )
        self._smart_turn_row = _ModelRow(smart_turn_info, c, show_radio=False)
        self._smart_turn_row._refresh_state(is_smart_turn_downloaded())
        self._smart_turn_row.action_btn.clicked.connect(self._download_smart_turn)
        self._smart_turn_row.delete_btn.clicked.connect(self._delete_smart_turn)
        turn_frame_layout.addWidget(self._smart_turn_row)

        layout.addWidget(turn_frame)

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

        # -- Speaker Embedding Models section ------------------------------------
        spk_section = QLabel("Speaker Embedding Models")
        spk_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(spk_section)

        spk_desc = QLabel(
            "Download a speaker embedding model for voice identification. "
            "Required for speaker diarization in Voice Channel mode."
        )
        spk_desc.setWordWrap(True)
        spk_desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(spk_desc)

        spk_frame = QWidget()
        spk_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        spk_frame_layout = QVBoxLayout(spk_frame)
        spk_frame_layout.setContentsMargins(4, 4, 4, 4)
        spk_frame_layout.setSpacing(0)

        from roomkit_ui.model_manager import SPEAKER_MODELS, is_speaker_model_downloaded

        @dataclass(frozen=True)
        class _SpeakerInfo:
            id: str
            name: str
            type: str
            size: str

        self._spk_rows: list[_ModelRow] = []
        for spk_m in SPEAKER_MODELS:
            spk_info = _SpeakerInfo(id=spk_m.id, name=spk_m.name, type="speaker", size=spk_m.size)
            row = _ModelRow(spk_info, c, show_radio=False)
            row._refresh_state(is_speaker_model_downloaded(spk_m.id))
            row.action_btn.clicked.connect(
                lambda _checked=False, mid=spk_m.id: self._download_speaker_model(mid)
            )
            row.delete_btn.clicked.connect(
                lambda _checked=False, mid=spk_m.id: self._delete_speaker_model(mid)
            )
            spk_frame_layout.addWidget(row)
            self._spk_rows.append(row)

        layout.addWidget(spk_frame)
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

    # -- Smart Turn model handlers -------------------------------------------

    def _download_smart_turn(self) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_smart_turn

        row = self._smart_turn_row
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_smart_turn(_progress)
                row.set_downloaded()
            except Exception:
                logging.exception("Smart Turn download failed")
                row.set_error()

        loop.create_task(_run())

    def _delete_smart_turn(self) -> None:
        from roomkit_ui.model_manager import delete_smart_turn

        delete_smart_turn()
        self._smart_turn_row.set_not_downloaded()

    # -- Speaker embedding model handlers ------------------------------------

    def _find_spk_row(self, model_id: str) -> _ModelRow | None:
        for row in self._spk_rows:
            if row.model.id == model_id:
                return row
        return None

    def _download_speaker_model(self, model_id: str) -> None:
        import asyncio
        import logging

        from roomkit_ui.model_manager import download_speaker_model

        row = self._find_spk_row(model_id)
        if row is None:
            return
        row.set_resolving()
        loop = asyncio.get_event_loop()

        def _progress(downloaded: int, total: int) -> None:
            pct = min(int(downloaded * 100 / total), 100) if total > 0 else 0
            loop.call_soon_threadsafe(row.set_downloading, pct)

        async def _run() -> None:
            try:
                await download_speaker_model(model_id, _progress)
                row.set_downloaded()
            except Exception:
                logging.exception("Speaker model download failed: %s", model_id)
                row.set_error()

        loop.create_task(_run())

    def _delete_speaker_model(self, model_id: str) -> None:
        from roomkit_ui.model_manager import delete_speaker_model

        delete_speaker_model(model_id)
        row = self._find_spk_row(model_id)
        if row is not None:
            row.set_not_downloaded()
