"""Tests for the private-API shims in roomkit_compat.

These helpers are hasattr-guarded by design: a roomkit refactor must make
them no-op gracefully, and only these tests will notice the silent no-op.
"""

from roomkit_ui.roomkit_compat import (
    clear_diarization_enrollment,
    compose_attitude_prompt,
    detach_channel_backend,
    detach_channel_providers,
    set_ai_system_prompt,
)


class _Channel:
    def __init__(self):
        self._stt = object()
        self._tts = object()
        self._backend = object()


def test_compose_attitude_prompt_appends_section():
    out = compose_attitude_prompt("base prompt", "be cheerful")
    assert out.startswith("base prompt")
    assert "# Attitude" in out
    assert out.endswith("be cheerful")


def test_compose_attitude_prompt_empty_attitude_is_verbatim():
    assert compose_attitude_prompt("base prompt", "") == "base prompt"


def test_compose_attitude_prompt_empty_base():
    assert compose_attitude_prompt("", "") == ""
    assert "# Attitude" in compose_attitude_prompt("", "x")


def test_detach_channel_providers_clears_slots():
    ch = _Channel()
    detach_channel_providers(ch)
    assert ch._stt is None
    assert ch._tts is None
    assert ch._backend is not None  # untouched


def test_detach_channel_providers_noops_without_slots():
    detach_channel_providers(object())  # must not raise
    detach_channel_providers(None)


def test_detach_channel_backend_clears_slot():
    ch = _Channel()
    detach_channel_backend(ch)
    assert ch._backend is None
    assert ch._stt is not None  # untouched


def test_detach_channel_backend_noops_without_slot():
    detach_channel_backend(object())
    detach_channel_backend(None)


def test_set_ai_system_prompt_writes_slot():
    class _AI:
        _system_prompt = "old"

    ai = _AI()
    set_ai_system_prompt(ai, "new")
    assert ai._system_prompt == "new"


def test_set_ai_system_prompt_noops_without_slot():
    set_ai_system_prompt(object(), "new")
    set_ai_system_prompt(None, "new")


class _Manager:
    def __init__(self, names):
        self.all_speakers = list(names)


class _Diar:
    def __init__(self):
        self._manager = _Manager(["alice", "bob"])
        self._enrolled_embeddings = {"alice": [0.1], "bob": [0.2]}
        self.reset_called = False
        self.removed: list[str] = []

    def reset(self):
        self.reset_called = True

    def remove_speaker(self, name):
        self.removed.append(name)


def test_clear_diarization_enrollment_full_reset():
    d = _Diar()
    clear_diarization_enrollment(d)
    assert d.reset_called
    assert sorted(d.removed) == ["alice", "bob"]
    assert d._enrolled_embeddings == {}


def test_clear_diarization_enrollment_survives_reset_failure():
    d = _Diar()

    def _boom():
        raise RuntimeError("reset failed")

    d.reset = _boom
    clear_diarization_enrollment(d)  # must not raise
    assert sorted(d.removed) == ["alice", "bob"]
    assert d._enrolled_embeddings == {}


def test_clear_diarization_enrollment_noops_on_none():
    clear_diarization_enrollment(None)
