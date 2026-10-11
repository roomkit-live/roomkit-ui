"""Guided enrolment: which takes are accepted, and how the steps progress."""

from __future__ import annotations

import numpy as np
import pytest

from roomkit_ui.wakeword.enroller import (
    DECOY_STEP,
    PROTOTYPE_STEPS,
    Enroller,
    EnrolmentState,
    Take,
)

SAMPLE_RATE = 16000


def _pcm(seconds: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


@pytest.fixture
def enroller(monkeypatch, tmp_path, inline_jobs):
    """An enroller whose microphone and encoder are stubbed out."""
    encoder = tmp_path / "encoder.onnx"
    encoder.write_bytes(b"")
    e = Enroller(str(encoder), "/nonexistent/vad.onnx", jobs=inline_jobs)
    monkeypatch.setattr(e._capture, "start", lambda: True)
    monkeypatch.setattr(e._capture, "stop", lambda: None)
    monkeypatch.setattr(
        e._embedder, "embed", lambda pcm: np.random.RandomState(len(pcm) % 97).randn(50, 8)
    )
    monkeypatch.setattr(e._embedder, "load", lambda: None)
    e.begin("dis xavier")
    return e


# -- step progression --------------------------------------------------------


def test_starts_on_the_first_condition(enroller):
    assert enroller.state.current_step is PROTOTYPE_STEPS[0]


def test_covers_every_condition_before_finishing(enroller):
    """Each condition must be enrolled, or distant speech goes undetected."""
    finished = []
    enroller.phase_finished.connect(lambda: finished.append(True))

    for _ in range(enroller.state.total_takes):
        enroller._on_segment(_pcm(1.4), 1.4)

    assert len(enroller.state.prototypes) == sum(s.takes for s in PROTOTYPE_STEPS)
    assert finished


def test_moves_to_the_next_condition_once_its_takes_are_done(enroller):
    for _ in range(PROTOTYPE_STEPS[0].takes):
        enroller._on_segment(_pcm(1.4), 1.4)
    assert enroller.state.current_step is PROTOTYPE_STEPS[1]


def test_announces_each_step_with_its_progress(enroller):
    seen = []
    enroller.step_changed.connect(lambda p, h, done, of: seen.append((p, done, of)))
    enroller._on_segment(_pcm(1.4), 1.4)
    assert seen
    prompt, done, of = seen[-1]
    assert done == 1
    assert of == PROTOTYPE_STEPS[0].takes


# -- take validation ---------------------------------------------------------


def test_rejects_a_take_that_is_too_short(enroller):
    rejected = []
    enroller.take_rejected.connect(rejected.append)
    enroller._on_segment(_pcm(0.2), 0.2)
    assert rejected
    assert not enroller.state.prototypes


def test_rejects_a_take_that_is_too_long(enroller):
    rejected = []
    enroller.take_rejected.connect(rejected.append)
    enroller._on_segment(_pcm(6.0), 6.0)
    assert rejected
    assert not enroller.state.prototypes


def test_rejects_a_take_whose_length_breaks_ranks(enroller):
    """The 2.7 s take where the phrase was said twice must not get in."""
    enroller._on_segment(_pcm(1.4), 1.4)
    rejected = []
    enroller.take_rejected.connect(rejected.append)
    enroller._on_segment(_pcm(2.9), 2.9)
    assert rejected
    assert len(enroller.state.prototypes) == 1


def test_rejection_explains_itself_to_the_user(enroller):
    rejected = []
    enroller.take_rejected.connect(rejected.append)
    enroller._on_segment(_pcm(0.2), 0.2)
    assert "short" in rejected[0].lower()


def test_accepts_consistent_takes(enroller):
    enroller._on_segment(_pcm(1.4), 1.4)
    enroller._on_segment(_pcm(1.5), 1.5)
    assert len(enroller.state.prototypes) == 2


# -- decoys ------------------------------------------------------------------


def test_decoys_are_not_held_to_the_phrase_length(enroller):
    """Decoys are different words on purpose — length consistency is irrelevant."""
    for _ in range(enroller.state.total_takes):
        enroller._on_segment(_pcm(1.4), 1.4)
    enroller.begin_decoys()

    enroller._on_segment(_pcm(0.6), 0.6)
    enroller._on_segment(_pcm(2.5), 2.5)

    assert len(enroller.state.decoys) == 2


def test_decoy_phase_uses_its_own_step(enroller):
    enroller.begin_decoys()
    assert enroller.state.current_step is DECOY_STEP


# -- result ------------------------------------------------------------------


def test_finish_builds_a_calibrated_fingerprint(enroller):
    for _ in range(enroller.state.total_takes):
        enroller._on_segment(_pcm(1.4), 1.4)
    enroller.begin_decoys()
    for _ in range(DECOY_STEP.takes):
        enroller._on_segment(_pcm(1.0), 1.0)

    fingerprint, calibration = enroller.finish()

    assert fingerprint.label == "dis xavier"
    assert fingerprint.usable
    assert len(fingerprint.decoys) == DECOY_STEP.takes
    assert calibration.threshold == fingerprint.threshold


def test_fingerprint_is_unusable_when_enrolment_was_abandoned(enroller):
    enroller._on_segment(_pcm(1.4), 1.4)
    fingerprint, _ = enroller.finish()
    assert not fingerprint.usable


# -- state -------------------------------------------------------------------


def test_state_counts_takes_within_the_current_step():
    state = EnrolmentState(label="x")
    state.prototypes = [Take(np.zeros((4, 2)), 1.3)] * PROTOTYPE_STEPS[0].takes
    state.step_index = 1
    assert state.taken_in_step == 0


def test_state_total_covers_all_prototype_steps():
    assert EnrolmentState().total_takes == sum(s.takes for s in PROTOTYPE_STEPS)
