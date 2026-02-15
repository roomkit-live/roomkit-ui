"""Audio Debug settings: pipeline debug taps, session recording, and file browser."""

from __future__ import annotations

import logging
import wave
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme import colors

logger = logging.getLogger(__name__)

_DEFAULT_DEBUG_DIR = str(Path.home() / ".local/share/roomkit-ui/debug_audio")
_DEFAULT_RECORDING_DIR = str(Path.home() / ".local/share/roomkit-ui/recordings")

_STAGES = [
    ("raw", "Raw (before processing)"),
    ("post_aec", "Post Echo Cancellation"),
    ("post_agc", "Post Gain Control"),
    ("post_denoiser", "Post Denoiser"),
    ("post_vad_speech", "VAD Speech Segments"),
    ("outbound_raw", "Outbound Raw"),
    ("outbound_final", "Outbound Final"),
]

_RECORDING_MODES = [
    ("Both", "both"),
    ("Inbound Only", "inbound_only"),
    ("Outbound Only", "outbound_only"),
]

_CHANNEL_MODES = [
    ("Stereo (L=mic, R=speaker)", "stereo"),
    ("Separate Files", "separate"),
    ("Mixed", "mixed"),
]

_MAX_FILES = 100


class _AudioFileRow(QWidget):
    """Single row: filename | size | duration | Play | Delete."""

    def __init__(
        self,
        path: Path,
        player: QMediaPlayer,
        on_delete: object,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._path = path
        self._player = player
        self._on_delete = on_delete
        c = colors()

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(8)

        name = QLabel(path.name)
        name.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_PRIMARY']}; background: transparent;"
        )
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(name, 1)

        size_kb = path.stat().st_size / 1024
        size_label = QLabel(f"{size_kb:.0f} KB")
        size_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        size_label.setFixedWidth(60)
        row.addWidget(size_label)

        dur = self._read_duration(path)
        dur_label = QLabel(f"{dur:.1f}s" if dur > 0 else "—")
        dur_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        dur_label.setFixedWidth(44)
        row.addWidget(dur_label)

        icon_color = c["TEXT_SECONDARY"]
        self._play_icon = svg_icon("play", icon_color, 16)
        self._stop_icon = svg_icon("stop", icon_color, 16)

        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._play_icon)
        self._play_btn.setFixedSize(28, 28)
        self._play_btn.setToolTip("Play")
        self._play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self._play_btn)

        del_btn = QPushButton()
        del_btn.setIcon(svg_icon("trash", icon_color, 16))
        del_btn.setFixedSize(28, 28)
        del_btn.setToolTip("Delete")
        del_btn.clicked.connect(self._delete)
        row.addWidget(del_btn)

    @staticmethod
    def _read_duration(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return frames / rate
        except Exception:
            pass
        return 0.0

    def _toggle_play(self) -> None:
        if (
            self._player.playbackState() == QMediaPlayer.PlayingState
            and self._player.source() == QUrl.fromLocalFile(str(self._path))
        ):
            self._player.stop()
            self._play_btn.setIcon(self._play_icon)
            self._play_btn.setToolTip("Play")
            return
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(self._path)))
        self._player.play()
        self._play_btn.setIcon(self._stop_icon)
        self._play_btn.setToolTip("Stop")

    def _delete(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass
        self._on_delete()  # type: ignore[operator]

    def update_play_state(self) -> None:
        """Update button icon based on current player state."""
        if (
            self._player.playbackState() == QMediaPlayer.PlayingState
            and self._player.source() == QUrl.fromLocalFile(str(self._path))
        ):
            self._play_btn.setIcon(self._stop_icon)
            self._play_btn.setToolTip("Stop")
        else:
            self._play_btn.setIcon(self._play_icon)
            self._play_btn.setToolTip("Play")


class _AudioDebugPage(QWidget):
    """Audio debug settings: pipeline taps, recording, and file browser."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Audio Debug")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Capture audio at pipeline stage boundaries and record full sessions. "
            "Changes take effect on the next session."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        # ── Pipeline Debug Taps ──
        section_style = (
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )

        taps_label = QLabel("Pipeline Debug Taps")
        taps_label.setStyleSheet(section_style)
        layout.addWidget(taps_label)

        self._taps_enable = QCheckBox("Enable Debug Taps")
        self._taps_enable.setChecked(settings.get("debug_taps_enabled", False))
        layout.addWidget(self._taps_enable)

        self._taps_fields = QWidget()
        taps_form = QFormLayout(self._taps_fields)
        taps_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        taps_form.setContentsMargins(0, 0, 0, 0)
        taps_form.setSpacing(10)
        taps_form.setLabelAlignment(Qt.AlignRight)

        self._stages_combo = QComboBox()
        self._stages_combo.addItem("All Stages")
        self._stages_combo.addItem("Custom...")
        current_stages = settings.get("debug_taps_stages", "all")
        self._stages_combo.setCurrentIndex(0 if current_stages == "all" else 1)
        taps_form.addRow("Stages", self._stages_combo)

        # Custom stage checkboxes (collapsible)
        self._custom_stages_widget = QWidget()
        custom_lay = QVBoxLayout(self._custom_stages_widget)
        custom_lay.setContentsMargins(20, 0, 0, 0)
        custom_lay.setSpacing(4)

        selected = set()
        if current_stages != "all":
            selected = {s.strip() for s in current_stages.split(",") if s.strip()}

        self._stage_checks: dict[str, QCheckBox] = {}
        for key, label in _STAGES:
            cb = QCheckBox(label)
            cb.setChecked(key in selected if selected else True)
            self._stage_checks[key] = cb
            custom_lay.addWidget(cb)

        taps_form.addRow("", self._custom_stages_widget)

        # Output directory
        dir_row = QWidget()
        dir_lay = QHBoxLayout(dir_row)
        dir_lay.setContentsMargins(0, 0, 0, 0)
        dir_lay.setSpacing(6)
        self._taps_dir = QLineEdit(settings.get("debug_output_dir", ""))
        self._taps_dir.setPlaceholderText(_DEFAULT_DEBUG_DIR)
        dir_lay.addWidget(self._taps_dir, 1)
        browse = QPushButton("Browse")
        browse.setFixedWidth(64)
        browse.clicked.connect(lambda: self._browse_dir(self._taps_dir))
        dir_lay.addWidget(browse)
        taps_form.addRow("Output", dir_row)

        hint = QLabel("Records WAV at each pipeline stage boundary for debugging audio quality.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        taps_form.addRow("", hint)

        layout.addWidget(self._taps_fields)

        # ── Session Recording ──
        rec_label = QLabel("Session Recording")
        rec_label.setStyleSheet(section_style)
        layout.addWidget(rec_label)

        self._rec_enable = QCheckBox("Enable Recording")
        self._rec_enable.setChecked(settings.get("recording_enabled", False))
        layout.addWidget(self._rec_enable)

        self._rec_fields = QWidget()
        rec_form = QFormLayout(self._rec_fields)
        rec_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        rec_form.setContentsMargins(0, 0, 0, 0)
        rec_form.setSpacing(10)
        rec_form.setLabelAlignment(Qt.AlignRight)

        self._mode_combo = QComboBox()
        current_mode = settings.get("recording_mode", "both")
        for label, val in _RECORDING_MODES:
            self._mode_combo.addItem(label)
            if val == current_mode:
                self._mode_combo.setCurrentIndex(self._mode_combo.count() - 1)
        rec_form.addRow("Mode", self._mode_combo)

        self._channels_combo = QComboBox()
        current_ch = settings.get("recording_channels", "stereo")
        for label, val in _CHANNEL_MODES:
            self._channels_combo.addItem(label)
            if val == current_ch:
                self._channels_combo.setCurrentIndex(self._channels_combo.count() - 1)
        rec_form.addRow("Channels", self._channels_combo)

        rec_dir_row = QWidget()
        rec_dir_lay = QHBoxLayout(rec_dir_row)
        rec_dir_lay.setContentsMargins(0, 0, 0, 0)
        rec_dir_lay.setSpacing(6)
        self._rec_dir = QLineEdit(settings.get("recording_output_dir", ""))
        self._rec_dir.setPlaceholderText(_DEFAULT_RECORDING_DIR)
        rec_dir_lay.addWidget(self._rec_dir, 1)
        rec_browse = QPushButton("Browse")
        rec_browse.setFixedWidth(64)
        rec_browse.clicked.connect(lambda: self._browse_dir(self._rec_dir))
        rec_dir_lay.addWidget(rec_browse)
        rec_form.addRow("Output", rec_dir_row)

        rec_hint = QLabel("Records full session audio as WAV files.")
        rec_hint.setWordWrap(True)
        rec_hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        rec_form.addRow("", rec_hint)

        layout.addWidget(self._rec_fields)

        # ── Recorded Files ──
        files_label = QLabel("Recorded Files")
        files_label.setStyleSheet(section_style)
        layout.addWidget(files_label)

        # Shared media player
        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.playbackStateChanged.connect(self._on_playback_changed)

        self._file_list_container = QWidget()
        self._file_list_layout = QVBoxLayout(self._file_list_container)
        self._file_list_layout.setContentsMargins(0, 0, 0, 0)
        self._file_list_layout.setSpacing(2)

        scroll = QScrollArea()
        scroll.setWidget(self._file_list_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setMinimumHeight(120)
        layout.addWidget(scroll, 1)

        self._no_files_label = QLabel("No recorded files found.")
        self._no_files_label.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent; padding: 8px;"
        )
        self._no_files_label.setAlignment(Qt.AlignCenter)
        self._file_list_layout.addWidget(self._no_files_label)

        # Footer buttons
        footer = QHBoxLayout()
        footer.setSpacing(8)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_files)
        footer.addWidget(refresh_btn)

        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_folder)
        footer.addWidget(open_btn)

        self._delete_all_btn = QPushButton("Delete All")
        self._delete_all_btn.clicked.connect(self._delete_all)
        footer.addWidget(self._delete_all_btn)

        footer.addStretch()
        layout.addLayout(footer)

        # Wire visibility
        self._taps_enable.toggled.connect(self._taps_fields.setVisible)
        self._stages_combo.currentIndexChanged.connect(self._on_stages_combo)
        self._rec_enable.toggled.connect(self._rec_fields.setVisible)

        # Initial state
        self._taps_fields.setVisible(self._taps_enable.isChecked())
        self._rec_fields.setVisible(self._rec_enable.isChecked())
        self._on_stages_combo(self._stages_combo.currentIndex())

        self._file_rows: list[_AudioFileRow] = []
        self._delete_confirm = False

    def _on_stages_combo(self, index: int) -> None:
        self._custom_stages_widget.setVisible(index == 1)

    def _browse_dir(self, line_edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text())
        if d:
            line_edit.setText(d)

    def _on_playback_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        for row in self._file_rows:
            row.update_play_state()

    # ── File browser ──

    def refresh_files(self) -> None:
        """Rescan output directories and rebuild the file list."""
        self._player.stop()
        self._delete_confirm = False
        self._delete_all_btn.setText("Delete All")

        # Clear old rows
        for row in self._file_rows:
            row.setParent(None)
            row.deleteLater()
        self._file_rows.clear()

        # Collect WAV files from both dirs
        files: list[Path] = []
        for d in self._output_dirs():
            dp = Path(d)
            if dp.is_dir():
                for f in dp.rglob("*.wav"):
                    if f.stat().st_size >= 44:
                        files.append(f)

        # Sort newest first, cap at _MAX_FILES
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        files = files[:_MAX_FILES]

        self._no_files_label.setVisible(len(files) == 0)

        for f in files:
            try:
                row = _AudioFileRow(f, self._player, self.refresh_files, self)
                self._file_list_layout.addWidget(row)
                self._file_rows.append(row)
            except Exception:
                logger.debug("Skipping unreadable file: %s", f)

    def _output_dirs(self) -> list[str]:
        dirs = []
        d1 = self._taps_dir.text().strip() or _DEFAULT_DEBUG_DIR
        d2 = self._rec_dir.text().strip() or _DEFAULT_RECORDING_DIR
        dirs.append(d1)
        if d2 != d1:
            dirs.append(d2)
        return dirs

    def _open_folder(self) -> None:
        from PySide6.QtGui import QDesktopServices

        for d in self._output_dirs():
            if Path(d).is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(d))
                return
        # If neither exists, open the default debug dir parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(_DEFAULT_DEBUG_DIR))

    def _delete_all(self) -> None:
        if not self._delete_confirm:
            self._delete_confirm = True
            self._delete_all_btn.setText("Confirm?")
            return
        self._player.stop()
        for d in self._output_dirs():
            dp = Path(d)
            if dp.is_dir():
                for f in dp.rglob("*.wav"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
        self._delete_confirm = False
        self._delete_all_btn.setText("Delete All")
        self.refresh_files()

    # ── Settings ──

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        # Build stages string
        if self._stages_combo.currentIndex() == 0:
            stages = "all"
        else:
            selected = [k for k, cb in self._stage_checks.items() if cb.isChecked()]
            stages = ",".join(selected) if selected else "all"

        return {
            "debug_taps_enabled": self._taps_enable.isChecked(),
            "debug_taps_stages": stages,
            "debug_output_dir": self._taps_dir.text().strip(),
            "recording_enabled": self._rec_enable.isChecked(),
            "recording_mode": _RECORDING_MODES[self._mode_combo.currentIndex()][1],
            "recording_channels": _CHANNEL_MODES[self._channels_combo.currentIndex()][1],
            "recording_output_dir": self._rec_dir.text().strip(),
        }
