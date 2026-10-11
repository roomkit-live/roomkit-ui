"""Diagnostics preserves settings and scopes destructive actions to reviewed files."""

import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from roomkit_ui.widgets.settings import about_page, recordings_page
from roomkit_ui.widgets.settings.audio_capture_page import AudioCapturePage
from roomkit_ui.widgets.settings.diagnostics_page import DiagnosticsPage
from roomkit_ui.widgets.settings.recordings_page import RecordingsPage
from roomkit_ui.widgets.settings.telemetry_page import _TelemetryPage


def wav(path, frames=160):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * frames)
    return path.resolve()


@pytest.fixture
def browser(qapp, tmp_path):
    page = RecordingsPage(
        {
            "recording_output_dir": str(tmp_path / "sessions"),
            "debug_output_dir": str(tmp_path / "pipeline"),
        }
    )
    yield page
    shiboken6.delete(page)


def test_browser_filters_sources_and_names_and_deduplicates_overlapping_roots(browser, tmp_path):
    session = wav(tmp_path / "sessions" / "Hello.WAV")
    pipeline = wav(tmp_path / "pipeline" / "raw.wav")
    browser.refresh_files()
    assert {row.entry.path for row in browser._rows} == {session, pipeline}
    browser.search.setText("HELLO")
    assert [row.entry.path for row in browser._rows] == [session]
    browser.search.clear()
    browser.source.setCurrentIndex(2)
    assert [row.entry.path for row in browser._rows] == [pipeline]
    browser.set_debug_directory(str(tmp_path))
    browser.source.setCurrentIndex(0)
    assert len(browser._rows) == 2
    assert next(row.entry.sources for row in browser._rows if row.entry.path == session) == {
        "Pipeline",
        "Sessions",
    }


def test_bulk_delete_only_deletes_shown_snapshot(browser, tmp_path, monkeypatch):
    monkeypatch.setattr(recordings_page, "_MAX_FILES", 2)
    paths = [wav(tmp_path / "sessions" / f"session-{i}.wav") for i in range(4)]
    other = wav(tmp_path / "pipeline" / "raw.wav")
    browser.source.setCurrentIndex(1)
    shown = {row.entry.path for row in browser._rows}
    assert len(shown) == 2
    assert browser.count.text().startswith("2 of 4 files")
    browser.delete_shown.click()
    assert all(path.exists() for path in paths)
    new_file = wav(tmp_path / "sessions" / "new.wav")
    browser.confirm_delete.click()
    assert all(not path.exists() for path in shown)
    assert all(path.exists() for path in set(paths) - shown)
    assert other.exists() and new_file.exists()
    assert browser.feedback.text() == "Deleted 2 files."


@pytest.mark.parametrize("change", ["filter", "refresh", "folder", "hide"])
def test_pending_deletion_is_cancelled_when_context_changes(browser, tmp_path, change):
    path = wav(tmp_path / "sessions" / "session.wav")
    browser.show()
    browser.refresh_files()
    browser.delete_shown.click()
    assert browser._pending
    if change == "filter":
        browser.search.setText("different")
    elif change == "refresh":
        browser.refresh_files()
    elif change == "folder":
        browser.set_recording_directory(str(tmp_path))
    else:
        browser.hide()
    assert browser._pending == []
    assert browser.confirmation.isHidden()
    assert path.exists()


def test_files_modified_since_display_are_not_deleted(browser, tmp_path):
    path = wav(tmp_path / "sessions" / "live.wav")
    browser.refresh_files()
    browser.delete_shown.click()
    wav(path, frames=320)
    browser.confirm_delete.click()
    assert path.exists()
    assert "changed since it was listed" in browser.feedback.text()


def test_unlink_failure_is_visible_and_does_not_hide_remaining_files(
    browser, tmp_path, monkeypatch
):
    path = wav(tmp_path / "sessions" / "protected.wav")
    browser.refresh_files()
    browser.delete_shown.click()
    monkeypatch.setattr(Path, "unlink", MagicMock(side_effect=PermissionError("Access denied")))
    browser.confirm_delete.click()
    assert path.exists()
    assert "Access denied" in browser.feedback.text()
    assert browser.feedback.property("tone") == "error"
    assert len(browser._rows) == 1


def test_missing_and_unreadable_folders_have_distinct_feedback(browser, monkeypatch):
    browser.refresh_files()
    assert browser.feedback.text() == ""
    assert browser.empty.isVisibleTo(browser)

    def inaccessible(_root, *, onerror):
        onerror(PermissionError("Access denied"))
        return []

    monkeypatch.setattr(recordings_page.os, "walk", inaccessible)
    browser.refresh_files()
    assert "Access denied" in browser.feedback.text()


def test_missing_multimedia_keeps_browsing_available(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(recordings_page, "_HAS_MULTIMEDIA", False)
    path = wav(tmp_path / "audio.wav")
    page = RecordingsPage(
        {"recording_output_dir": str(tmp_path), "debug_output_dir": str(tmp_path / "debug")}
    )
    page.refresh_files()
    assert page._player is None
    assert page._rows[0].entry.path == path
    assert not page._rows[0].play.isEnabled()
    assert page.delete_shown.isEnabled()
    shiboken6.delete(page)


@pytest.mark.skipif(not recordings_page._HAS_MULTIMEDIA, reason="QtMultimedia unavailable")
def test_playback_switches_files_and_stops_on_hide(browser, tmp_path):
    browser.show()
    wav(tmp_path / "sessions" / "a.wav")
    wav(tmp_path / "sessions" / "b.wav")
    browser.refresh_files()
    player = MagicMock()
    browser._player = player
    player.source.return_value = QUrl()
    first, second = [row.entry for row in browser._rows]
    browser._toggle_play(first)
    assert player.setSource.call_args.args[0] == QUrl.fromLocalFile(str(first.path))
    browser._toggle_play(second)
    assert player.setSource.call_args.args[0] == QUrl.fromLocalFile(str(second.path))
    player.source.return_value = QUrl.fromLocalFile(str(second.path))
    player.playbackState.return_value = recordings_page.QMediaPlayer.PlayingState
    browser._playback_changed()
    assert browser._rows[1].play.text() == "Stop"
    play_count = player.play.call_count
    browser._toggle_play(second)
    assert player.play.call_count == play_count
    browser.hide()
    assert player.setSource.call_args.args[0].isEmpty()


def test_empty_custom_stages_turn_off_capture_and_never_expand_to_all(qapp):
    page = AudioCapturePage({"debug_taps_enabled": True, "debug_taps_stages": "raw"})
    page.stage_checks["raw"].setChecked(False)
    assert page.get_settings()["debug_taps_stages"] == ""
    assert not page.get_settings()["debug_taps_enabled"]
    assert not page.enabled.isEnabled()
    restored = AudioCapturePage(page.get_settings())
    assert restored.stages.currentIndex() == 1
    assert not restored.enabled.isEnabled()
    page.stage_checks["post_aec"].setChecked(True)
    assert page.enabled.isEnabled()
    assert not page.enabled.isChecked()
    page.enabled.setChecked(True)
    assert page.get_settings()["debug_taps_stages"] == "post_aec"
    shiboken6.delete(page)
    shiboken6.delete(restored)


def test_capture_preserves_configuration_when_disabled_and_unknown_stages(qapp):
    settings = {
        "debug_taps_enabled": True,
        "debug_taps_stages": "raw,future_stage",
        "debug_output_dir": "/tmp/capture",
    }
    page = AudioCapturePage(settings)
    page.enabled.setChecked(False)
    assert page.get_settings() == {**settings, "debug_taps_enabled": False}
    shiboken6.delete(page)


def test_otlp_protocol_changes_default_hint_without_overwriting_custom_endpoint(qapp):
    page = _TelemetryPage(
        {
            "telemetry_provider": "otlp",
            "otlp_endpoint": "https://collector.example/traces",
            "otlp_service_name": "voice",
        }
    )
    page.otlp_protocol.setCurrentIndex(1)
    assert page.otlp_endpoint.placeholderText() == "http://localhost:4318/v1/traces"
    page.provider.setCurrentIndex(0)
    assert page.export.isHidden()
    assert page.get_settings() == {
        "telemetry_provider": "none",
        "otlp_endpoint": "https://collector.example/traces",
        "otlp_protocol": "http",
        "otlp_service_name": "voice",
    }
    page.provider.setCurrentIndex(2)
    assert not page.export.isHidden()
    shiboken6.delete(page)


def test_diagnostics_only_owns_capture_and_telemetry_settings(qapp, tmp_path):
    page = DiagnosticsPage({"recording_enabled": True, "recording_output_dir": str(tmp_path)})
    assert set(page.get_settings()) == {
        "debug_taps_enabled",
        "debug_taps_stages",
        "debug_output_dir",
        "telemetry_provider",
        "otlp_endpoint",
        "otlp_protocol",
        "otlp_service_name",
    }
    page.capture.directory.setText(str(tmp_path / "pipeline"))
    assert page.recordings._roots()["Pipeline"] == tmp_path / "pipeline"
    shiboken6.delete(page)


def test_about_has_installed_version_copy_info_and_complete_license(qapp, monkeypatch):
    monkeypatch.setattr(about_page, "version", lambda package: "1.2.3")
    page = about_page._AboutPage()
    assert page.version.text() == "1.2.3"
    page.copy_info.click()
    assert QApplication.clipboard().text().startswith("RoomKit UI 1.2.3\n")
    assert page.license.content.isHidden()
    page.license.button.click()
    assert not page.license.content.isHidden()
    assert (
        page.license_text.text().split()
        == (Path(__file__).parents[1] / "LICENSE").read_text().split()
    )
    shiboken6.delete(page)


def test_about_works_without_distribution_metadata(qapp, monkeypatch):
    monkeypatch.setattr(
        about_page, "version", MagicMock(side_effect=about_page.PackageNotFoundError)
    )
    page = about_page._AboutPage()
    assert page.version.text() == "Development build"
    shiboken6.delete(page)
