"""Round-trip and coercion tests for QSettings persistence."""

from roomkit_ui.settings import _DEFAULTS, load_settings, save_settings


def test_defaults_returned_when_nothing_saved():
    out = load_settings()
    assert set(out) == set(_DEFAULTS)
    assert out["provider"] == _DEFAULTS["provider"]
    assert out["input_device"] is None


def test_round_trip_preserves_values():
    save_settings({"provider": "openai", "stt_enabled": False, "vc_interruption": True})
    out = load_settings()
    assert out["provider"] == "openai"
    assert out["stt_enabled"] is False
    assert out["vc_interruption"] is True


def test_bool_strings_are_coerced():
    # QSettings ini storage stringifies bools; load must coerce them back.
    save_settings({"stt_enabled": "true", "diarization_enabled": "1", "stt_translate": "no"})
    out = load_settings()
    assert out["stt_enabled"] is True
    assert out["diarization_enabled"] is True
    assert out["stt_translate"] is False


def test_denoise_migrates_from_legacy_bool():
    save_settings({"denoise": True})
    assert load_settings()["denoise"] == "rnnoise"
    save_settings({"denoise": "false"})
    assert load_settings()["denoise"] == "none"


def test_diarization_threshold_coercion():
    save_settings({"diarization_threshold": "0.55"})
    assert load_settings()["diarization_threshold"] == 0.55
    save_settings({"diarization_threshold": "garbage"})
    assert load_settings()["diarization_threshold"] == 0.4


def test_device_indices_coercion():
    save_settings({"input_device": "3", "output_device": ""})
    out = load_settings()
    assert out["input_device"] == 3
    assert out["output_device"] is None
    save_settings({"input_device": "not-a-number"})
    assert load_settings()["input_device"] is None
