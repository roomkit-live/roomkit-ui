"""Wake-word matching: DTW behaviour, threshold calibration, persistence."""

from __future__ import annotations

import numpy as np
import pytest

from roomkit_ui.wakeword import fingerprint as fp
from roomkit_ui.wakeword.detector import Detection, EmbeddingWakeDetector
from roomkit_ui.wakeword.dtw import distance_to_prototypes, dtw_distance
from roomkit_ui.wakeword.features import SAMPLE_RATE, log_mel


def _sequence(seed: int, frames: int = 40, dims: int = 16) -> np.ndarray:
    return np.random.RandomState(seed).randn(frames, dims).astype(np.float32)


def _stretch(seq: np.ndarray, factor: float) -> np.ndarray:
    """Resample along time — same content, different speaking rate."""
    n = int(len(seq) * factor)
    idx = np.linspace(0, len(seq) - 1, n)
    return np.stack(
        [np.interp(idx, np.arange(len(seq)), seq[:, d]) for d in range(seq.shape[1])], axis=1
    ).astype(np.float32)


# -- DTW ---------------------------------------------------------------------


def test_identical_sequences_have_zero_distance():
    seq = _sequence(0)
    assert dtw_distance(seq, seq) == pytest.approx(0.0, abs=1e-6)


def test_time_stretch_costs_less_than_different_content():
    """The whole point of DTW: speaking faster must not look like another word."""
    seq = _sequence(1)
    stretched = _stretch(seq, 1.4)
    other = _sequence(99)
    assert dtw_distance(seq, stretched) < dtw_distance(seq, other)


def test_empty_sequence_never_matches():
    assert dtw_distance(np.zeros((0, 16), dtype=np.float32), _sequence(2)) == float("inf")


def test_distance_uses_two_closest_prototypes():
    """One outlier prototype must not sink a genuine match."""
    query = _sequence(3)
    prototypes = [query, _stretch(query, 1.1), _sequence(50)]
    assert distance_to_prototypes(query, prototypes) < dtw_distance(query, _sequence(50))


def test_distance_without_prototypes_is_infinite():
    assert distance_to_prototypes(_sequence(4), []) == float("inf")


# -- Calibration -------------------------------------------------------------


def test_threshold_sits_between_positives_and_decoys():
    base = _sequence(5)
    prototypes = [base, _stretch(base, 1.05), _stretch(base, 0.95)]
    decoys = [_sequence(60), _sequence(61)]

    cal = fp.calibrate(prototypes, decoys)

    assert cal.worst_positive < cal.threshold < cal.closest_decoy
    assert not cal.overlapping
    assert cal.margin > 0


def test_overlapping_decoy_tightens_threshold_below_it():
    """A decoy closer than the user's own variation must never trigger."""
    base = _sequence(6)
    prototypes = [base, _sequence(70), _sequence(71)]  # deliberately scattered
    decoys = [_stretch(base, 1.02)]  # nearly the phrase itself

    cal = fp.calibrate(prototypes, decoys)

    assert cal.overlapping
    assert cal.threshold < cal.closest_decoy


def test_calibration_without_decoys_falls_back_to_spread():
    base = _sequence(7)
    prototypes = [base, _stretch(base, 1.05), _stretch(base, 0.97)]

    cal = fp.calibrate(prototypes, [])

    assert cal.threshold > 0
    assert cal.closest_decoy == float("inf")


def test_outliers_flag_takes_that_break_the_gabarit():
    durations = [1.3, 1.4, 1.35, 2.9, 1.3]  # the 2.9 s take said it twice
    assert fp.outlier_prototypes([], durations) == [3]


def test_no_outliers_when_takes_are_consistent():
    assert fp.outlier_prototypes([], [1.3, 1.4, 1.35, 1.5]) == []


# -- Fingerprint -------------------------------------------------------------


def test_fingerprint_needs_enough_prototypes_to_be_usable():
    one = fp.Fingerprint(label="dis xavier", prototypes=[_sequence(8)], threshold=0.1)
    assert not one.usable


def test_fingerprint_without_threshold_is_unusable():
    prints = [_sequence(9), _sequence(10), _sequence(11)]
    assert not fp.Fingerprint(label="x", prototypes=prints, threshold=0.0).usable


def test_matches_reports_distance_and_decision():
    base = _sequence(12)
    print_ = fp.Fingerprint(
        label="dis xavier",
        prototypes=[base, _stretch(base, 1.05), _stretch(base, 0.95)],
        threshold=1.0,  # deliberately permissive
    )
    triggered, distance = print_.matches(base)
    assert triggered
    assert distance >= 0


# -- Persistence -------------------------------------------------------------


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "storage_dir", lambda: tmp_path)
    return tmp_path


def test_save_then_load_round_trips(storage):
    original = fp.Fingerprint(
        label="dis xavier",
        prototypes=[_sequence(13), _sequence(14), _sequence(15)],
        decoys=[_sequence(16)],
        threshold=0.0625,
    )
    fp.save(original)
    restored = fp.load()

    assert restored is not None
    assert restored.label == "dis xavier"
    assert restored.threshold == pytest.approx(0.0625)
    assert len(restored.prototypes) == 3
    assert len(restored.decoys) == 1
    np.testing.assert_allclose(restored.prototypes[0], original.prototypes[0])


def test_load_without_enrolment_returns_none(storage):
    assert fp.load() is None


def test_clear_forgets_the_phrase(storage):
    fp.save(fp.Fingerprint(label="x", prototypes=[_sequence(17)], threshold=0.1))
    fp.clear()
    assert fp.load() is None


def test_corrupt_fingerprint_reads_as_not_enrolled(storage):
    fp.save(fp.Fingerprint(label="x", prototypes=[_sequence(18)], threshold=0.1))
    (storage / "fingerprint.json").write_text("{ not json")
    assert fp.load() is None


# -- Features ----------------------------------------------------------------


def test_log_mel_matches_whisper_normalisation():
    """Whisper expects (log10+4)/4 output — out-of-range input yields noise."""
    tone = (np.sin(2 * np.pi * 440 * np.arange(SAMPLE_RATE) / SAMPLE_RATE) * 8000).astype(np.int16)
    mel = log_mel(tone.tobytes())

    assert mel.shape[0] == 80
    assert mel.max() <= 1.5
    assert mel.min() >= -1.5


def test_log_mel_of_too_short_audio_is_empty():
    assert log_mel(b"\x00\x00" * 10).shape[1] == 0


# -- Detector ----------------------------------------------------------------


def _detector(threshold: float = 1.0) -> EmbeddingWakeDetector:
    prints = [_sequence(20), _sequence(21), _sequence(22)]
    return EmbeddingWakeDetector(
        "/nonexistent/encoder.onnx",
        fp.Fingerprint(label="dis xavier", prototypes=prints, threshold=threshold),
    )


def test_detector_skips_segments_outside_the_duration_window():
    """Too short or too long is not a summons — and costs no inference."""
    detector = _detector()
    assert detector.detect(b"\x00\x00" * 1000) is None  # 0.06 s
    assert detector.detect(b"\x00\x00" * (SAMPLE_RATE * 10)) is None  # 10 s


def test_detector_is_not_ready_without_enough_prototypes():
    detector = EmbeddingWakeDetector(
        "/nonexistent/encoder.onnx",
        fp.Fingerprint(label="x", prototypes=[_sequence(23)], threshold=0.1),
    )
    assert not detector.ready
    assert detector.detect(b"\x00\x00" * SAMPLE_RATE) is None


def test_missing_encoder_surfaces_rather_than_silently_failing():
    """A broken install must reach the user, not be swallowed per segment."""
    detector = _detector()
    with pytest.raises((FileNotFoundError, ImportError)):
        detector.detect(b"\x00\x00" * SAMPLE_RATE)


def test_confidence_saturates_between_zero_and_one():
    assert Detection(True, 0.0, 0.06, 1.2).confidence == 1.0
    assert Detection(True, 0.06, 0.06, 1.2).confidence == pytest.approx(1.0)
    assert Detection(False, 0.12, 0.06, 1.2).confidence == 0.0
    assert Detection(False, 1.0, 0.0, 1.2).confidence == 0.0


def test_detector_can_adopt_an_already_loaded_encoder():
    """Enrolment hands its encoder to detection — 12 MB and ~200 ms saved."""
    from roomkit_ui.wakeword.features import WhisperEmbedder

    detector = _detector()
    shared = WhisperEmbedder("/nonexistent/encoder.onnx")
    detector.share_embedder(shared)
    assert detector._embedder is shared


# -- sensitivity -------------------------------------------------------------


def test_sensitivity_scales_the_measured_threshold():
    from roomkit_ui.wakeword.page_sensitivity import apply_sensitivity

    print_ = fp.Fingerprint(label="x", prototypes=[_sequence(30)], threshold=0.08)
    assert apply_sensitivity(print_, "cautious") < 0.08

    print_.threshold = 0.08
    assert apply_sensitivity(print_, "responsive") > 0.08


def test_balanced_leaves_the_measurement_alone():
    from roomkit_ui.wakeword.page_sensitivity import apply_sensitivity

    print_ = fp.Fingerprint(label="x", prototypes=[_sequence(31)], threshold=0.0823)
    assert apply_sensitivity(print_, "balanced") == 0.0823


def test_unknown_sensitivity_falls_back_to_balanced():
    from roomkit_ui.wakeword.page_sensitivity import apply_sensitivity

    print_ = fp.Fingerprint(label="x", prototypes=[_sequence(32)], threshold=0.08)
    assert apply_sensitivity(print_, "nonsense") == 0.08
