"""Browse and play session recordings and diagnostic WAVs without nested scrolling."""

from __future__ import annotations

import os
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QHideEvent, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.paths import data_dir
from roomkit_ui.widgets.settings.controls import FeedbackLabel, label, navigation_link

# QtMultimedia belongs to PySide6-Addons; the core install can still manage files.
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    _HAS_MULTIMEDIA = True
except ImportError:
    _HAS_MULTIMEDIA = False

_MAX_FILES = 100


@dataclass
class AudioFile:
    path: Path
    size: int
    modified_ns: int
    sources: set[str]


class _FileName(QLabel):
    """Constrain generated filenames while exposing the full path on hover."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._filename = path.name
        self.setObjectName("settingsRowTitle")
        self.setTextFormat(Qt.PlainText)
        self.setAccessibleName(path.name)
        self.setToolTip(str(path))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setText(path.name)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self._filename, Qt.ElideMiddle, self.width()))


class AudioFileRow(QFrame):
    play_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, entry: AudioFile, can_play: bool) -> None:
        super().__init__()
        self.entry = entry
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        layout.addWidget(_FileName(entry.path))
        modified = datetime.fromtimestamp(entry.modified_ns / 1e9).strftime("%b %d, %H:%M")
        duration = self._duration(entry.path)
        size = (
            f"{entry.size / 1024:.0f} KB"
            if entry.size < 1024**2
            else f"{entry.size / 1024**2:.1f} MB"
        )
        layout.addWidget(
            label(
                f"{' + '.join(sorted(entry.sources))} · {modified} · {size} · {duration}",
                "settingsHint",
            )
        )
        actions = QHBoxLayout()
        self.play = QPushButton("Play")
        self.play.setEnabled(can_play)
        self.play.setAccessibleName(f"Play {entry.path.name}")
        if not can_play:
            self.play.setToolTip(
                "In-app playback requires PySide6-Addons. Open the folder to use another player."
            )
        self.play.clicked.connect(lambda: self.play_requested.emit(entry))
        delete = QPushButton("Delete…")
        delete.setAccessibleName(f"Delete {entry.path.name}")
        delete.clicked.connect(lambda: self.delete_requested.emit(entry))
        for button in (self.play, delete):
            button.setAutoDefault(False)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

    @staticmethod
    def _duration(path: Path) -> str:
        try:
            with wave.open(str(path), "rb") as audio:
                return f"{audio.getnframes() / audio.getframerate():.1f} s"
        except (OSError, EOFError, wave.Error, ZeroDivisionError):
            return "Duration unavailable"


class RecordingsPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._recording_dir = settings.get("recording_output_dir", "")
        self._debug_dir = settings.get("debug_output_dir", "")
        self._rows: list[AudioFileRow] = []
        self._pending: list[AudioFile] = []
        self._player = QMediaPlayer(self) if _HAS_MULTIMEDIA else None
        self._audio_output = QAudioOutput(self) if _HAS_MULTIMEDIA else None
        if self._player is not None and self._audio_output is not None:
            self._player.setAudioOutput(self._audio_output)
            self._player.playbackStateChanged.connect(self._playback_changed)
            self._player.errorOccurred.connect(self._playback_error)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(label("Recorded audio", "settingsSectionTitle"))
        layout.addWidget(
            label(
                "Listen to session recordings and compare pipeline captures. "
                "WAV files are stored unencrypted on disk.",
                "settingsHint",
            )
        )
        self.recording_link = navigation_link("Session recording settings →")
        self.recording_link.clicked.connect(lambda: self.navigate_requested.emit("privacy"))
        layout.addWidget(self.recording_link, 0, Qt.AlignLeft)
        folders = QHBoxLayout()
        self.session_folder = navigation_link("Open recordings folder ↗")
        self.capture_folder = navigation_link("Open capture folder ↗")
        self.session_folder.clicked.connect(lambda: self._open_folder("Sessions"))
        self.capture_folder.clicked.connect(lambda: self._open_folder("Pipeline"))
        folders.addWidget(self.session_folder)
        folders.addWidget(self.capture_folder)
        folders.addStretch()
        layout.addLayout(folders)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an audio file…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Find an audio file")
        filters.addWidget(self.search, 1)
        self.source = QComboBox()
        self.source.setAccessibleName("Audio source")
        for title, value in [
            ("All audio", ""),
            ("Session recordings", "Sessions"),
            ("Pipeline captures", "Pipeline"),
        ]:
            self.source.addItem(title, value)
        filters.addWidget(self.source)
        layout.addLayout(filters)
        toolbar = QHBoxLayout()
        self.count = label("", "settingsHint")
        toolbar.addWidget(self.count, 1)
        refresh = QPushButton("Refresh")
        refresh.setAutoDefault(False)
        refresh.clicked.connect(self.refresh_files)
        toolbar.addWidget(refresh)
        self.delete_shown = QPushButton("Delete shown files…")
        self.delete_shown.setAutoDefault(False)
        self.delete_shown.clicked.connect(
            lambda: self._confirm_delete([row.entry for row in self._rows])
        )
        toolbar.addWidget(self.delete_shown)
        layout.addLayout(toolbar)
        self.confirmation = QWidget()
        confirm_layout = QVBoxLayout(self.confirmation)
        self._confirm_layout = confirm_layout
        confirm_layout.setContentsMargins(0, 0, 0, 0)
        self.confirm_text = label("", "settingsHint")
        self.confirm_text.setTextFormat(Qt.PlainText)
        confirm_layout.addWidget(self.confirm_text)
        self._confirm_filename: _FileName | None = None
        confirm_actions = QHBoxLayout()
        self.confirm_delete = QPushButton("Delete permanently")
        self.confirm_delete.setObjectName("settingsDanger")
        self.confirm_delete.clicked.connect(self._delete_pending)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self._cancel_delete)
        for button in (self.confirm_delete, cancel):
            button.setAutoDefault(False)
            confirm_actions.addWidget(button)
        confirm_actions.addStretch()
        confirm_layout.addLayout(confirm_actions)
        self.confirmation.hide()
        layout.addWidget(self.confirmation)
        self.feedback = FeedbackLabel()
        layout.addWidget(self.feedback)
        if not _HAS_MULTIMEDIA:
            layout.addWidget(
                label(
                    "In-app playback is unavailable in this install. "
                    "Open a folder to listen with another player.",
                    "settingsHint",
                )
            )
        self.empty = label("", "settingsDescription")
        layout.addWidget(self.empty)
        self.files = QVBoxLayout()
        self.files.setSpacing(8)
        layout.addLayout(self.files)
        self.search.textChanged.connect(self.refresh_files)
        self.source.currentIndexChanged.connect(self.refresh_files)

    def _roots(self) -> dict[str, Path]:
        return {
            "Sessions": Path(self._recording_dir.strip() or data_dir() / "recordings"),
            "Pipeline": Path(self._debug_dir.strip() or data_dir() / "debug_audio"),
        }

    def set_recording_directory(self, directory: str) -> None:
        self._recording_dir = directory
        self._cancel_delete()

    def set_debug_directory(self, directory: str) -> None:
        self._debug_dir = directory
        self._cancel_delete()

    def refresh_files(self) -> None:
        self.stop_playback()
        self._cancel_delete()
        self.feedback.setText("")
        while self.files.count():
            item = self.files.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.hide()
                widget.deleteLater()
        self._rows.clear()
        entries: dict[Path, AudioFile] = {}
        errors: list[OSError] = []
        for source, root in self._roots().items():
            button = self.session_folder if source == "Sessions" else self.capture_folder
            button.setToolTip(str(root))
            # os.walk does not follow directory symlinks and reports inaccessible folders.
            for directory, _, names in os.walk(root, onerror=errors.append):
                for name in names:
                    path = Path(directory) / name
                    if path.suffix.lower() != ".wav" or path.is_symlink():
                        continue
                    try:
                        stat = path.stat()
                        if stat.st_size < 44 or not path.is_file():
                            continue
                        path = path.resolve()
                        if path in entries:
                            entries[path].sources.add(source)
                        else:
                            entries[path] = AudioFile(
                                path, stat.st_size, stat.st_mtime_ns, {source}
                            )
                    except OSError as exc:
                        errors.append(exc)
        query = self.search.text().strip().casefold()
        source_filter = self.source.currentData()
        matches = sorted(
            (
                entry
                for entry in entries.values()
                if query in entry.path.name.casefold()
                and (not source_filter or source_filter in entry.sources)
            ),
            key=lambda entry: entry.modified_ns,
            reverse=True,
        )
        for entry in matches[:_MAX_FILES]:
            row = AudioFileRow(entry, self._player is not None)
            row.play_requested.connect(self._toggle_play)
            row.delete_requested.connect(lambda item: self._confirm_delete([item]))
            self._rows.append(row)
            self.files.addWidget(row)
        count = len(self._rows)
        self.count.setText(
            f"{count} of {len(matches)} files · newest first"
            if len(matches) > _MAX_FILES
            else f"{count} {'file' if count == 1 else 'files'} · newest first"
        )
        self.delete_shown.setEnabled(bool(count))
        self.empty.setText(
            "No matching audio files. Try another name or source."
            if entries
            else "No audio files yet. Enable session recording or pipeline capture, "
            "then start a session and refresh."
        )
        self.empty.setVisible(not count)
        # Missing default folders are a normal first-run state.
        failures = [error for error in errors if not isinstance(error, FileNotFoundError)]
        if failures:
            reason = failures[0].strerror or str(failures[0])
            self.feedback.set_status(f"Some audio files could not be read: {reason}", "error")
            self.feedback.setToolTip(str(failures[0]))

    def _open_folder(self, source: str) -> None:
        root = self._roots()[source]
        if not root.is_dir():
            self.feedback.set_status(
                "This folder does not exist yet. It will be created when audio is recorded."
            )
            self.feedback.setToolTip(str(root))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(root.resolve()))):
            self.feedback.set_status("Could not open the audio folder.", "error")

    def stop_playback(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())

    def _toggle_play(self, entry: AudioFile) -> None:
        if self._player is None:
            return
        url = QUrl.fromLocalFile(str(entry.path))
        playing = (
            self._player.source() == url
            and self._player.playbackState() == QMediaPlayer.PlayingState
        )
        self.stop_playback()
        if not playing:
            self.feedback.setText("")
            self._player.setSource(url)
            self._player.play()

    def _playback_changed(self) -> None:
        if self._player is None:
            return
        for row in self._rows:
            playing = (
                self._player.source() == QUrl.fromLocalFile(str(row.entry.path))
                and self._player.playbackState() == QMediaPlayer.PlayingState
            )
            row.play.setText("Stop" if playing else "Play")
            row.play.setAccessibleName(f"{'Stop' if playing else 'Play'} {row.entry.path.name}")

    def _playback_error(self, _error, message: str) -> None:
        self.feedback.set_status(f"Could not play this file: {message}", "error")

    def _confirm_delete(self, entries: list[AudioFile]) -> None:
        self._cancel_delete()
        self._pending = list(entries)
        if not entries:
            return
        target = "this file" if len(entries) == 1 else f"these {len(entries)} displayed files"
        self.confirm_text.setText(f"Permanently delete {target}? This cannot be undone.")
        if len(entries) == 1:
            self._confirm_filename = _FileName(entries[0].path)
            self._confirm_layout.insertWidget(1, self._confirm_filename)
        self.confirmation.show()
        self.confirm_delete.setFocus()

    def _cancel_delete(self) -> None:
        self._pending = []
        if self._confirm_filename is not None:
            self._confirm_layout.removeWidget(self._confirm_filename)
            self._confirm_filename.hide()
            self._confirm_filename.deleteLater()
            self._confirm_filename = None
        self.confirmation.hide()

    def _delete_pending(self) -> None:
        entries = self._pending[:]
        self.stop_playback()
        deleted = 0
        errors: list[str] = []
        failed_files: list[str] = []
        for entry in entries:
            try:
                stat = entry.path.stat()
                if entry.path.is_symlink() or (stat.st_size, stat.st_mtime_ns) != (
                    entry.size,
                    entry.modified_ns,
                ):
                    errors.append("A file changed since it was listed. Refresh and try again.")
                    failed_files.append(str(entry.path))
                    continue
                entry.path.unlink()
                deleted += 1
            except OSError as exc:
                errors.append(exc.strerror or str(exc))
                failed_files.append(str(entry.path))
        self.refresh_files()
        self.feedback.set_status(
            f"Deleted {deleted} {'file' if deleted == 1 else 'files'}."
            + (f" Could not delete {len(errors)}: {errors[0]}" if errors else ""),
            "error" if errors else "success",
        )
        self.feedback.setToolTip("\n".join(failed_files))

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        self.stop_playback()
        self._cancel_delete()
        super().hideEvent(event)
