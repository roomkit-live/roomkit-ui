"""AECDumpRecorder: faithful pass-through, faithful record.

The dump feeds roomkit's offline AEC bench, so what matters is that (a)
wrapping changes nothing for the wrapped provider, and (b) the JSONL
preserves the exact arrival interleaving of reference, capture and
activation events — that ordering is the whole value of the format.
"""

import base64
import json

from roomkit_ui.aec_dump import AECDumpRecorder


class _Frame:
    def __init__(self, data: bytes):
        self.data = data
        self.sample_rate = 24000
        self.channels = 1
        self.sample_width = 2


class _InnerAEC:
    """Identity AEC recording every call it receives."""

    name = "fake_aec"

    def __init__(self):
        self.calls = []

    def process(self, frame, stream):
        self.calls.append(("process", stream))
        return _Frame(frame.data[::-1])  # visibly transformed output

    def feed_reference(self, frame, stream):
        self.calls.append(("ref", stream))

    def set_active(self, active):
        self.calls.append(("set_active", active))

    def set_stream_active(self, stream, active):
        self.calls.append(("act", stream, active))

    def reset(self, stream):
        self.calls.append(("reset", stream))

    def extra_knob(self):
        return 42


def _events(path):
    lines = (path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [json.loads(line) for line in lines[1:]]


def test_passthrough_and_interleaved_record(tmp_path):
    inner = _InnerAEC()
    rec = AECDumpRecorder(inner, tmp_path)

    rec.set_stream_active("s1", True)
    rec.feed_reference(_Frame(b"\x01\x02"), "s1")
    out = rec.process(_Frame(b"\x03\x04"), "s1")
    rec.feed_reference(_Frame(b"\x05\x06"), "s1")
    rec.set_stream_active("s1", False)
    rec.reset("s1")

    assert out.data == b"\x04\x03"  # inner's transform reached the caller
    assert ("reset", "s1") in inner.calls
    assert rec.extra_knob() == 42  # beyond-ABC attributes pass through
    assert rec.name == "fake_aec+dump"

    session_dir = next(tmp_path.iterdir())
    header, events = _events(session_dir)
    assert header["format"] == "aec-dump/1"
    assert header["sample_rate"] == 24000
    assert header["provider"] == "fake_aec"
    assert [e["t"] for e in events] == ["act", "ref", "cap", "ref", "act"]
    cap = events[2]
    assert base64.b64decode(cap["i"]) == b"\x03\x04"
    assert base64.b64decode(cap["o"]) == b"\x04\x03"
    assert events[0]["a"] is True and events[4]["a"] is False

    # Listening copies exist for every populated track.
    names = {p.name for p in session_dir.iterdir()}
    assert {"events.jsonl", "ref.wav", "mic_in.wav", "mic_out.wav"} <= names


def test_event_cap_stops_recording_not_audio(tmp_path, monkeypatch):
    import roomkit_ui.aec_dump as mod

    monkeypatch.setattr(mod, "_MAX_EVENTS", 3)
    rec = AECDumpRecorder(_InnerAEC(), tmp_path)
    for _ in range(10):
        rec.process(_Frame(b"\x01\x02"), "s1")
    rec.reset("s1")

    _, events = _events(next(tmp_path.iterdir()))
    assert len(events) == 3  # capped, but every process() call still ran


def test_reset_without_events_writes_nothing(tmp_path):
    rec = AECDumpRecorder(_InnerAEC(), tmp_path)
    rec.reset("s1")
    assert list(tmp_path.iterdir()) == []
