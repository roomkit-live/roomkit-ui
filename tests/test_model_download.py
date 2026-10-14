"""Model downloads: bounded waits, resumable espeak-ng data, one download at a time."""

import hashlib
import io
import socket
import threading
import time

import pytest

import roomkit_ui.model_catalog as catalog
import roomkit_ui.model_download as md


class _FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "get_models_dir", lambda: tmp_path)
    monkeypatch.setattr(md, "get_models_dir", lambda: tmp_path)
    return tmp_path


# -- a stalled connection fails instead of hanging ------------------------


@pytest.fixture
def silent_server():
    """Accepts connections and never answers."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    held = []
    stop = threading.Event()

    def accept():
        srv.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}/model.onnx"
    stop.set()
    thread.join()
    for conn in held:
        conn.close()
    srv.close()


def test_a_stalled_download_times_out(tmp_path, silent_server, monkeypatch):
    monkeypatch.setattr(md, "_TIMEOUT", 0.5)
    target = tmp_path / "model.onnx"

    started = time.monotonic()
    with pytest.raises(OSError):  # TimeoutError, or URLError wrapping it
        md._download_file(silent_server, target)

    assert time.monotonic() - started < 3
    assert not target.exists()
    assert not target.with_suffix(".onnx.part").exists()


def test_a_download_shorter_than_its_content_length_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        md, "_urlopen", lambda req: _FakeResponse(b"x" * 10, {"Content-Length": "100"})
    )

    with pytest.raises(RuntimeError, match="size mismatch"):
        md._download_file("https://example.invalid/f", tmp_path / "model.onnx")


def test_smart_turn_is_checked_against_its_pinned_sha256(models_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(md, "_urlopen", lambda req: _FakeResponse(b"", {"Content-Length": "8"}))
    monkeypatch.setattr(md, "_download_file", lambda *a, **kw: calls.append(kw))

    md._download_smart_turn_sync()

    assert calls[0]["expected_sha256"] == catalog.SMART_TURN_SHA256


# -- espeak-ng-data is complete only once every file is in ----------------


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()  # noqa: S324


_ESPEAK = {"phontab": b"P" * 10, "phondata": b"D" * 20, "lang/roa/fr": b"F" * 5}


@pytest.fixture
def espeak_repo(monkeypatch):
    """The Contents API listing and a raw server that can be made to fail."""
    entries = [
        {"path": f"tts/espeak-ng-data/{rel}", "size": len(data), "sha": _blob_sha(data)}
        for rel, data in _ESPEAK.items()
    ]
    monkeypatch.setattr(md, "_list_gh_tree", lambda path: entries)
    failing: set[str] = set()

    def urlopen(url):
        rel = url.rsplit("espeak-ng-data/", 1)[1]
        if rel in failing:
            raise OSError("connection reset")
        return _FakeResponse(_ESPEAK[rel])

    monkeypatch.setattr(md, "_urlopen", urlopen)
    return failing


def test_espeak_cut_short_after_phontab_is_not_downloaded(models_dir, espeak_repo):
    espeak_repo.add("lang/roa/fr")

    with pytest.raises(OSError):
        md._download_espeak_ng_sync()

    assert (catalog.espeak_ng_data_path() / "phontab").is_file()
    assert catalog.is_espeak_ng_downloaded() is False


def test_espeak_resumes_and_replaces_a_truncated_file(models_dir, espeak_repo):
    espeak_repo.add("lang/roa/fr")
    with pytest.raises(OSError):
        md._download_espeak_ng_sync()
    (catalog.espeak_ng_data_path() / "phondata").write_bytes(b"D" * 3)  # truncated by a crash
    espeak_repo.clear()

    md._download_espeak_ng_sync()

    data_dir = catalog.espeak_ng_data_path()
    assert catalog.is_espeak_ng_downloaded() is True
    assert (data_dir / "phondata").read_bytes() == _ESPEAK["phondata"]
    assert (data_dir / "lang" / "roa" / "fr").read_bytes() == _ESPEAK["lang/roa/fr"]


def test_an_install_made_before_the_marker_still_counts(models_dir):
    data_dir = catalog.espeak_ng_data_path()
    data_dir.mkdir(parents=True)
    (data_dir / "phontab").write_bytes(b"P")

    assert catalog.is_espeak_ng_downloaded() is True


# -- one download per model at a time --------------------------------------


def test_a_second_download_of_the_same_model_joins_the_first(models_dir, monkeypatch):
    # Settings reopened mid-download: a second click must not start another
    # download into the same .part file.
    release = threading.Event()
    started = []

    def slow_download(url, target, expected_size=0, on_bytes=None, expected_sha256=None):
        started.append(url)
        on_bytes(4)
        release.wait(5)
        target.write_bytes(b"done")

    monkeypatch.setattr(md, "_urlopen", lambda req: _FakeResponse(b"", {"Content-Length": "8"}))
    monkeypatch.setattr(md, "_download_file", slow_download)
    first_seen, second_seen = [], []

    first = threading.Thread(
        target=md._download_gtcrn_sync, args=(lambda d, t: first_seen.append(d),)
    )
    first.start()
    while not started:
        time.sleep(0.01)
    second = threading.Thread(
        target=md._download_gtcrn_sync, args=(lambda d, t: second_seen.append(d),)
    )
    second.start()
    time.sleep(0.1)
    release.set()
    first.join(5)
    second.join(5)

    assert len(started) == 1
    assert second_seen == [4]  # caught up on the progress already made
    assert catalog.is_gtcrn_downloaded()


def test_a_joined_download_reports_the_failure_to_every_caller(models_dir, monkeypatch):
    release = threading.Event()
    started = []

    def failing_download(*a, **kw):
        started.append(1)
        release.wait(5)
        raise RuntimeError("size mismatch")

    monkeypatch.setattr(md, "_urlopen", lambda req: _FakeResponse(b"", {"Content-Length": "8"}))
    monkeypatch.setattr(md, "_download_file", failing_download)
    errors = []

    def run():
        try:
            md._download_gtcrn_sync()
        except RuntimeError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=run) for _ in range(2)]
    threads[0].start()
    while not started:
        time.sleep(0.01)
    threads[1].start()
    time.sleep(0.1)
    release.set()
    for t in threads:
        t.join(5)

    assert len(started) == 1
    assert len(errors) == 2


# -- small files now, LFS files after, under one progress total ---------------


def test_an_stt_model_writes_small_files_and_downloads_lfs_ones_with_one_total(
    models_dir, monkeypatch
):
    model = catalog.STT_MODELS[0]
    small, *lfs_files = model.files[::-1]  # tokens.txt is small; the onnx files are LFS
    oid = "a" * 64
    pointer = f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize 10\n".encode()

    def urlopen(url):
        return _FakeResponse(b"tok 0\n" if url.endswith(small) else pointer)

    downloads: list[tuple[str, int, str]] = []

    def download_file(url, target, *, expected_size, on_bytes, expected_sha256):
        downloads.append((target.name, expected_size, expected_sha256))
        on_bytes(expected_size)

    reports: list[tuple[int, int]] = []
    monkeypatch.setattr(md, "_urlopen", urlopen)
    monkeypatch.setattr(md, "_lfs_download_url", lambda oid, size: f"https://lfs/{oid}")
    monkeypatch.setattr(md, "_download_file", download_file)

    md._download_model_sync(model.id, lambda done, total: reports.append((done, total)))

    assert (md.model_path(model.id) / small).read_bytes() == b"tok 0\n"
    assert sorted(d[0] for d in downloads) == sorted(lfs_files)
    total = 10 * len(lfs_files)
    assert reports[0] == (0, total) and reports[-1] == (total, total)


# -- release assets are held to their published sha256 ------------------------------


@pytest.mark.parametrize(
    ("download", "expected"),
    [
        (lambda: md._download_gtcrn_sync(), catalog.GTCRN_SHA256),
        *(
            (lambda model_id=model_id: md._download_speaker_model_sync(model_id), digest)
            for model_id, digest in catalog._SPEAKER_ASSET_SHA256.items()
        ),
    ],
)
def test_release_assets_are_checked_against_their_published_sha256(
    models_dir, monkeypatch, download, expected
):
    """GTCRN and the speaker models were held to their size alone: a damaged or
    replaced file of the right size would have been kept."""
    checked = []

    def fake_download(url, target, expected_size=0, on_bytes=None, expected_sha256=None):
        checked.append(expected_sha256)
        target.write_bytes(b"model")

    monkeypatch.setattr(md, "_urlopen", lambda req: _FakeResponse(b"", {"Content-Length": "5"}))
    monkeypatch.setattr(md, "_download_file", fake_download)

    download()

    assert checked == [expected]
