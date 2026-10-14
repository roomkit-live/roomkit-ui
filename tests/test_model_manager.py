"""Tests for LFS pointer parsing and download integrity checks."""

import hashlib
import io
import urllib.request

import pytest

from roomkit_ui.model_manager import _download_file, _resolve_lfs_pointer

_POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:0123abcd\nsize 12345\n"


def test_resolve_lfs_pointer_valid():
    assert _resolve_lfs_pointer(_POINTER) == ("0123abcd", 12345)


def test_resolve_lfs_pointer_rejects_regular_content():
    assert _resolve_lfs_pointer(b"onnx binary \x00\x01 garbage") is None
    assert _resolve_lfs_pointer(b"") is None


def test_resolve_lfs_pointer_missing_oid():
    assert _resolve_lfs_pointer(b"version https://git-lfs.github.com/spec/v1\nsize 5\n") is None


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def served_bytes(monkeypatch):
    payload = b"model-bytes" * 1000

    def _fake_urlopen(req, *a, **kw):
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    return payload


def test_download_file_writes_atomically(tmp_path, served_bytes):
    target = tmp_path / "model.onnx"
    digest = hashlib.sha256(served_bytes).hexdigest()
    _download_file(
        "https://example.invalid/f",
        target,
        expected_size=len(served_bytes),
        expected_sha256=digest,
    )
    assert target.read_bytes() == served_bytes
    assert not target.with_suffix(".onnx.part").exists()


def test_download_file_rejects_sha256_mismatch(tmp_path, served_bytes):
    target = tmp_path / "model.onnx"
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        _download_file(
            "https://example.invalid/f",
            target,
            expected_sha256="0" * 64,
        )
    assert not target.exists()
    assert not target.with_suffix(".onnx.part").exists()


def test_download_file_rejects_size_mismatch(tmp_path, served_bytes):
    target = tmp_path / "model.onnx"
    with pytest.raises(RuntimeError, match="size mismatch"):
        _download_file(
            "https://example.invalid/f",
            target,
            expected_size=len(served_bytes) + 1,
        )
    assert not target.exists()


def test_download_file_counts_bytes(tmp_path, served_bytes):
    target = tmp_path / "model.onnx"
    seen: list[int] = []
    _download_file("https://example.invalid/f", target, on_bytes=seen.append)
    assert sum(seen) == len(served_bytes)


@pytest.mark.parametrize(
    ("model_id", "padding"),
    [("kroko-streaming-fr", 1.5), ("kroko-streaming-en", 1.5), ("zipformer-streaming", 0.66)],
)
def test_kroko_gets_the_trailing_silence_its_last_words_need(model_id, padding):
    """With roomkit's 0.66 s Kroko dropped the last words ("demain à ne");
    a model that declares nothing keeps roomkit's default."""
    from roomkit_ui.model_manager import build_stt_config

    assert build_stt_config(model_id).tail_padding_s == padding


def test_nemotron_streams_and_finds_its_language_itself():
    from roomkit_ui.model_manager import build_stt_config, is_streaming_model

    config = build_stt_config("nemotron-streaming")

    assert is_streaming_model("nemotron-streaming")
    assert (config.mode, config.model_type) == ("transducer", "")  # streaming, not offline
    assert config.encoder.endswith("nemotron-streaming/v1/encoder.int8.onnx")
