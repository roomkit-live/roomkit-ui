"""Speaker settings retain profiles and explain prerequisites without starting audio."""

import shiboken6
from PySide6.QtWidgets import QLabel

from roomkit_ui.speaker_manager import SpeakerProfile
from roomkit_ui.widgets.settings.speakers_page import _SpeakersPage


def test_speaker_refresh_removes_old_rows_immediately(qapp, monkeypatch):
    profiles = []
    monkeypatch.setattr("roomkit_ui.speaker_manager.load_speakers", lambda: profiles)
    page = _SpeakersPage({})
    try:
        page.show()
        empty = page._speakers_layout.itemAt(0).widget()
        profiles.append(SpeakerProfile(name="<Camille>", embeddings=[[1.0]], is_primary=True))
        page._refresh_speakers()
        assert empty.isHidden()  # No ghost label while deleteLater awaits the event loop.
        row = page._speaker_rows[0]
        assert any(label.text() == "<Camille>" for label in row.findChildren(QLabel))
        assert row.primary_btn.isHidden()
        profiles.clear()
        page._refresh_speakers()
        assert row.isHidden()
        assert page._speaker_rows == []
    finally:
        shiboken6.delete(page)


def test_missing_speaker_model_gives_feedback_and_preserves_settings(qapp, monkeypatch):
    monkeypatch.setattr("roomkit_ui.speaker_manager.load_speakers", lambda: [])
    monkeypatch.setattr("roomkit_ui.model_manager.is_speaker_model_downloaded", lambda _: False)
    page = _SpeakersPage(
        {
            "diarization_enabled": True,
            "diarization_model": "missing-model",
            "diarization_threshold": "0.53",
            "primary_speaker_mode": True,
            "user_name": "  Camille  Martin ",
            "speaker_first_voice_is_user": False,
        }
    )
    try:
        page._on_enroll()
        assert page._test_result.text() == "Select and download a speaker model first."
        assert not page._test_result.isHidden()
        assert page._enroll_btn.text() == "Enroll speaker"
        page.refresh_models()
        assert page.get_settings() == {
            "diarization_enabled": True,
            "diarization_model": "missing-model",
            "diarization_threshold": 0.53,
            "primary_speaker_mode": True,
            "user_name": "Camille Martin",
            "speaker_first_voice_is_user": False,
        }
    finally:
        shiboken6.delete(page)
