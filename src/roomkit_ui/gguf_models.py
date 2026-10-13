"""llama.cpp models from Hugging Face: what a repository offers, what this
computer can run, and downloads into the cache llama-server reads.

Downloads land in the Hugging Face hub cache (``~/.cache/huggingface/hub``
unless ``HF_HUB_CACHE``/``HF_HOME`` say otherwise), in its own layout: the
file under ``blobs/<sha256>``, linked from ``snapshots/<commit>/<name>``,
``refs/main`` naming the commit.  llama-server's ``-hf repo:quant`` caches
there too, so a model either of them fetched is listed here.  A session
starts a downloaded model from its file (:func:`resolve`), never through
``-hf``: no network at start, offline included, and llama-server never needs
the Hugging Face token.

Whether a model fits is an estimate, made as Hugging Face's hardware panel and
LM Studio make it: the file, the KV cache of the context and a margin, against
the memory a model may take here.  It warns; it never refuses a download.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import re
import shutil
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

HF_URL = "https://huggingface.co"
_TIMEOUT = 30.0
_CHUNK = 1 << 20

# llama-server's quantization when a reference names none.
DEFAULT_QUANT = "Q4_K_M"

# "Q4_K_M", "UD-Q4_K_XL", "QAD-Q4_0", "IQ4_XS", "MXFP4", "BF16": the end of a
# file's stem.  A prefix is upper case only, so "Instruct-Q4_K_M" stays Q4_K_M.
_QUANT_RE = re.compile(
    r"(?:(?<=[-_.])|^)((?:[A-Z]{2,4}-)?"
    r"(?i:I?Q\d+(?:_[A-Z0-9]+)*|TQ\d_\d|BF16|F16|F32|MXFP4(?:_MOE)?))$"
)
_SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")

Progress = Callable[[int, int], None]


class HubError(RuntimeError):
    """Hugging Face refused or failed a request; the message says what to do."""


class DownloadCancelledError(Exception):
    """The user stopped a download; what arrived stays for the next try."""


def quant_label(stem: str) -> str:
    """A GGUF file's quantization, from its name without ``.gguf``."""
    stem = _SPLIT_RE.sub("", stem)
    match = _QUANT_RE.search(stem)
    return match.group(1) if match else stem


def valid_repo(repo: str) -> bool:
    return bool(_REPO_RE.match(repo)) and ".." not in repo


@dataclass(frozen=True)
class GGUFPart:
    name: str  # path in the repository
    size: int
    sha256: str


@dataclass(frozen=True)
class GGUFFile:
    """One quantization of a repository: a file, or the parts of a split one."""

    repo: str
    quant: str
    parts: tuple[GGUFPart, ...]

    @property
    def size(self) -> int:
        return sum(part.size for part in self.parts)

    @property
    def reference(self) -> str:
        return f"{self.repo}:{self.quant}"


@dataclass(frozen=True)
class HubModel:
    repo: str
    params: int = 0  # 0 when the repository does not say
    downloads: int = 0
    gated: bool = False
    tools: bool = False  # its chat template declares tools
    architecture: str = ""


@dataclass(frozen=True)
class RepoInfo:
    model: HubModel
    commit: str
    quants: tuple[GGUFFile, ...]

    def quant(self, label: str) -> GGUFFile | None:
        wanted = label.casefold()
        return next((q for q in self.quants if q.quant.casefold() == wanted), None)


@dataclass(frozen=True)
class Recommended:
    repo: str
    quant: str
    name: str
    params: int
    size: int
    note: str

    @property
    def reference(self) -> str:
        return f"{self.repo}:{self.quant}"


# Checked for conversation and tool calls, smallest first.  Sizes are those
# of the files today; a download reads the repository again.
RECOMMENDED: tuple[Recommended, ...] = (
    Recommended(
        "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
        "Q4_K_M",
        "LFM2.5 1.2B Instruct",
        1_170_340_608,
        730_895_168,
        "Liquid AI · the fastest, for short answers and simple tool calls",
    ),
    Recommended(
        "LiquidAI/LFM2.5-2.6B-GGUF",
        "Q4_K_M",
        "LFM2.5 2.6B",
        2_697_198_592,
        1_674_455_040,
        "Liquid AI · fast, and more capable",
    ),
    Recommended(
        "unsloth/Qwen3-4B-Instruct-2507-GGUF",
        "Q4_K_M",
        "Qwen3 4B Instruct 2507",
        4_022_468_096,
        2_497_281_120,
        "Qwen · the default: balanced for conversation and tools",
    ),
    Recommended(
        "Qwen/Qwen3-8B-GGUF",
        "Q4_K_M",
        "Qwen3 8B",
        8_190_735_360,
        5_027_783_488,
        "Qwen · better answers, and it can think before replying",
    ),
    Recommended(
        "LiquidAI/LFM2.5-8B-A1B-GGUF",
        "Q4_K_M",
        "LFM2.5 8B-A1B",
        8_467_856_832,
        5_155_564_768,
        "Liquid AI · mixture of experts: an 8B model at the speed of a 1B",
    ),
    Recommended(
        "ggml-org/gpt-oss-20b-GGUF",
        "MXFP4",
        "gpt-oss 20B",
        20_914_757_184,
        12_109_566_624,
        "OpenAI's open-weight model · mixture of experts, strong with tools",
    ),
    Recommended(
        "unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF",
        "Q4_K_M",
        "Qwen3 30B-A3B Instruct 2507",
        30_532_122_624,
        18_556_686_752,
        "Qwen · mixture of experts: strong, and still fast",
    ),
)


def recommended(reference: str) -> Recommended | None:
    """The recommended model *reference* names, if it is one."""
    repo, _, quant = reference.strip().partition(":")
    wanted = f"{repo}:{quant or DEFAULT_QUANT}".casefold()
    return next((r for r in RECOMMENDED if r.reference.casefold() == wanted), None)


def group_quants(repo: str, siblings: list[dict]) -> tuple[GGUFFile, ...]:
    """A repository's quantizations, smallest first, from its file listing.

    Split files become one entry; a vision projector (``mmproj``) is no
    model; a file without its SHA-256 is left out, as it could not be checked.
    """
    groups: dict[str, list[tuple[int, int, GGUFPart]]] = {}
    for sibling in siblings:
        name = str(sibling.get("rfilename") or "")
        if not _safe_name(name) or not name.lower().endswith(".gguf"):
            continue
        if "mmproj" in PurePosixPath(name).name.lower():
            continue
        lfs = sibling.get("lfs") or {}
        sha = str(lfs.get("sha256") or "")
        size = int(sibling.get("size") or lfs.get("size") or 0)
        if not sha or size <= 0:
            continue
        stem = name[: -len(".gguf")]
        split = _SPLIT_RE.search(stem)
        base = stem[: split.start()] if split else stem
        index, count = (int(split.group(1)), int(split.group(2))) if split else (1, 1)
        groups.setdefault(base, []).append((index, count, GGUFPart(name, size, sha)))
    quants: dict[str, GGUFFile] = {}
    for base, parts in sorted(groups.items()):
        parts.sort(key=lambda p: p[0])
        count = parts[0][1]
        if [p[0] for p in parts] != list(range(1, count + 1)):
            continue  # a part is missing from the listing
        label = quant_label(PurePosixPath(base).name)
        quants.setdefault(label.casefold(), GGUFFile(repo, label, tuple(p[2] for p in parts)))
    return tuple(sorted(quants.values(), key=lambda q: q.size))


def _safe_name(name: str) -> bool:
    """A file path inside a repository: relative, no ``..``, no backslash."""
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _model_from_json(item: dict) -> HubModel | None:
    repo = str(item.get("id") or item.get("modelId") or "")
    if not valid_repo(repo):
        return None
    gguf = item.get("gguf") or {}
    gated = item.get("gated")
    return HubModel(
        repo=repo,
        params=int(gguf.get("total") or 0),
        downloads=int(item.get("downloads") or 0),
        gated=bool(gated) and gated != "false",
        tools="tools" in str(gguf.get("chat_template") or ""),
        architecture=str(gguf.get("architecture") or ""),
    )


def _billions(params: int) -> str:
    return f"{max(params / 1e9, 0.1):.1f}".removesuffix(".0") + "B"


class HubClient:
    """Hugging Face's model API, for GGUF repositories llama.cpp runs."""

    def __init__(
        self,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = HF_URL,
    ) -> None:
        self._token = (token or "").strip()
        self._transport = transport
        self._base_url = base_url.rstrip("/")

    async def _get(self, path: str, params: list[tuple[str, str]]) -> object:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, transport=self._transport
        ) as client:
            try:
                resp = await client.get(
                    f"{self._base_url}{path}", params=tuple(params), headers=headers
                )
            except httpx.HTTPError as exc:
                raise HubError(f"Hugging Face could not be reached: {exc}") from exc
        if resp.status_code >= 400:
            raise HubError(_refusal(resp.status_code, bool(self._token)))
        return resp.json()

    async def search(
        self, query: str = "", *, max_params: int = 0, limit: int = 20
    ) -> list[HubModel]:
        """Text-generation models llama.cpp runs, most downloaded first;
        with *max_params*, none larger."""
        params = [
            ("apps", "llama.cpp"),
            ("pipeline_tag", "text-generation"),
            ("sort", "downloads"),
            ("direction", "-1"),
            ("limit", str(max(1, min(limit, 100)))),
            *(("expand[]", field) for field in ("gguf", "downloads", "gated")),
        ]
        if query.strip():
            params.append(("search", query.strip()))
        if max_params > 0:
            params.append(("num_parameters", f"min:0,max:{_billions(max_params)}"))
        data = await self._get("/api/models", params)
        items = data if isinstance(data, list) else []
        models = [_model_from_json(item) for item in items if isinstance(item, dict)]
        return [model for model in models if model is not None]

    async def repo(self, repo: str) -> RepoInfo:
        """*repo*'s current commit, its model card facts and its quantizations."""
        if not valid_repo(repo):
            raise HubError(f"{repo!r} is not a Hugging Face repository name.")
        data = await self._get(f"/api/models/{repo}/revision/main", [("blobs", "true")])
        if not isinstance(data, dict):
            raise HubError(f"Hugging Face sent no description of {repo}.")
        model = _model_from_json({**data, "id": repo})
        commit = str(data.get("sha") or "")
        if model is None or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise HubError(f"Hugging Face sent no usable description of {repo}.")
        siblings = [s for s in data.get("siblings") or [] if isinstance(s, dict)]
        return RepoInfo(model, commit, group_quants(repo, siblings))


def _refusal(status: int, has_token: bool) -> str:
    if status == 401:
        return (
            "Hugging Face refused the access token: check it in Providers & keys."
            if has_token
            else "This model needs a Hugging Face account: add an access token in "
            "Providers & keys, then close Settings to save it."
        )
    if status == 403:
        return (
            "This model is gated: accept its terms on huggingface.co with the account "
            "of your access token, then try again."
        )
    if status == 404:
        return "Hugging Face has no such model or file."
    if status == 429:
        return "Hugging Face is limiting requests: wait a minute, or add an access token."
    return f"Hugging Face answered with an error ({status})."


# --- the cache --------------------------------------------------------------


def hub_cache() -> Path:
    """The Hugging Face hub cache, as huggingface_hub and llama.cpp find it."""
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if value := os.environ.get(var, "").strip():
            return Path(value).expanduser()
    if value := os.environ.get("HF_HOME", "").strip():
        return Path(value).expanduser() / "hub"
    base = os.environ.get("XDG_CACHE_HOME", "").strip() or str(Path.home() / ".cache")
    return Path(base).expanduser() / "huggingface" / "hub"


def repo_dir(repo: str, cache: Path | None = None) -> Path:
    return (cache or hub_cache()) / ("models--" + repo.replace("/", "--"))


@dataclass(frozen=True)
class CachedModel:
    repo: str
    quant: str
    path: Path  # the file llama-server loads: the first part of a split one
    files: tuple[Path, ...]
    size: int

    @property
    def reference(self) -> str:
        return f"{self.repo}:{self.quant}"

    @property
    def name(self) -> str:
        return _SPLIT_RE.sub("", self.path.name[: -len(".gguf")])


def _snapshots(root: Path) -> list[Path]:
    """*root*'s snapshots, the one ``refs/main`` names first."""
    folder = root / "snapshots"
    try:
        snapshots = [p for p in folder.iterdir() if p.is_dir()]
    except OSError:
        return []
    try:
        main = (root / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        main = ""

    def order(path: Path) -> tuple[bool, float]:
        try:
            return path.name != main, -path.stat().st_mtime
        except OSError:
            return path.name != main, 0.0

    return sorted(snapshots, key=order)


def _scan_repo(root: Path) -> list[CachedModel]:
    repo = root.name.removeprefix("models--").replace("--", "/", 1)
    found: dict[str, CachedModel] = {}
    for snapshot in _snapshots(root):
        groups: dict[str, list[tuple[int, int, Path]]] = {}
        for path in sorted(snapshot.rglob("*.gguf")):
            if "mmproj" in path.name.lower():
                continue
            stem = path.name[: -len(".gguf")]
            split = _SPLIT_RE.search(stem)
            index, count = (int(split.group(1)), int(split.group(2))) if split else (1, 1)
            base = str(path.parent / _SPLIT_RE.sub("", stem))
            groups.setdefault(base, []).append((index, count, path))
        for base, parts in groups.items():
            parts.sort(key=lambda p: p[0])
            files = tuple(p[2] for p in parts)
            # A dangling link is a part whose blob never finished.
            if len(parts) != parts[0][1] or not all(f.is_file() for f in files):
                continue
            quant = quant_label(Path(base).name)
            if quant.casefold() in found:
                continue  # an older snapshot's copy of the same quantization
            size = sum(f.stat().st_size for f in files)
            found[quant.casefold()] = CachedModel(repo, quant, files[0], files, size)
    return list(found.values())


def cached_models(cache: Path | None = None) -> list[CachedModel]:
    """Every complete GGUF model in the cache, by repository then size."""
    root = cache or hub_cache()
    try:
        repos = sorted(p for p in root.glob("models--*--*") if p.is_dir())
    except OSError:
        return []
    models = [model for repo in repos for model in _scan_repo(repo)]
    return sorted(models, key=lambda m: (m.repo.casefold(), m.size))


def cached(reference: str, cache: Path | None = None) -> CachedModel | None:
    """The downloaded model *reference* (``repo:quant``) names, if any."""
    repo, _, quant = reference.strip().partition(":")
    if not valid_repo(repo):
        return None
    wanted = (quant or DEFAULT_QUANT).casefold()
    root = cache or hub_cache()
    try:
        dirs = [p for p in root.glob("models--*--*") if p.is_dir()]
    except OSError:
        return None
    target = repo_dir(repo, root).name.casefold()
    for folder in dirs:
        if folder.name.casefold() == target:
            models = _scan_repo(folder)
            return next((m for m in models if m.quant.casefold() == wanted), None)
    return None


def resolve(reference: str, cache: Path | None = None) -> Path | None:
    """The file of a downloaded ``repo:quant``, for llama-server's ``-m``."""
    model = cached(reference, cache)
    return model.path if model else None


def delete(model: CachedModel, cache: Path | None = None) -> None:
    """Remove *model*'s files and the blobs behind them; the repository's
    folder goes with its last model."""
    root = repo_dir(model.repo, cache)
    blobs = (root / "blobs").resolve()
    for path in model.files:
        if not path.resolve().is_relative_to(root.resolve()):
            raise OSError(f"{path} is outside the cache")
    for path in model.files:
        target = path.resolve() if path.is_symlink() else None
        path.unlink(missing_ok=True)
        if target is not None and target.parent == blobs:
            target.unlink(missing_ok=True)
    # Older snapshots linking the same blobs now point nowhere.
    for link in (root / "snapshots").rglob("*"):
        if link.is_symlink() and not link.exists():
            link.unlink()
    if not _scan_repo(root):
        shutil.rmtree(root, ignore_errors=True)


# --- downloads --------------------------------------------------------------


def download(
    file: GGUFFile,
    commit: str,
    *,
    token: str = "",
    progress: Progress | None = None,
    cancelled: threading.Event | None = None,
    cache: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    base_url: str = HF_URL,
) -> Path:
    """Download *file* at *commit* into the hub cache and return the path
    llama-server loads.

    A part already there is kept, an interrupted one resumes, and each is
    held to its size and SHA-256 before it takes its place.  Blocking: run
    it in a worker thread.  *cancelled* stops it between chunks
    (:class:`DownloadCancelledError`), keeping what arrived.
    """
    if not valid_repo(file.repo) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise HubError(f"{file.repo}@{commit} is not a valid revision.")
    root = repo_dir(file.repo, cache)
    total = file.size
    done = 0

    def on_bytes(count: int) -> None:
        nonlocal done
        done += count
        if progress is not None:
            progress(done, total)

    if progress is not None:
        progress(0, total)
    headers = {"User-Agent": "roomkit-ui"}
    if token.strip():
        # httpx drops it on a redirect to another host (the file CDN).
        headers["Authorization"] = f"Bearer {token.strip()}"
    with httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True, transport=transport, headers=headers
    ) as client:
        for part in file.parts:
            if not re.fullmatch(r"[0-9a-f]{64}", part.sha256):
                raise HubError(f"{part.name} has no SHA-256 to check it against.")
            snapshot = root / "snapshots" / commit
            link = snapshot / PurePosixPath(part.name)
            # Not resolve(): a finished part is a link into blobs/.
            inside = Path(os.path.normpath(link)).is_relative_to(snapshot)
            if not _safe_name(part.name) or not inside:
                raise HubError(f"{part.name} would land outside the cache.")
            blob = root / "blobs" / part.sha256
            if _complete(link, part.size) or _complete(blob, part.size):
                on_bytes(part.size)
            else:
                url = f"{base_url}/{file.repo}/resolve/{commit}/{quote(part.name)}"
                _fetch(client, url, blob, part, on_bytes, cancelled)
            _link(link, blob)
    refs = root / "refs" / "main"
    refs.parent.mkdir(parents=True, exist_ok=True)
    refs.write_text(commit, encoding="utf-8")
    return root / "snapshots" / commit / PurePosixPath(file.parts[0].name)


def _complete(path: Path, size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def _fetch(
    client: httpx.Client,
    url: str,
    blob: Path,
    part: GGUFPart,
    on_bytes: Callable[[int], None],
    cancelled: threading.Event | None,
) -> None:
    blob.parent.mkdir(parents=True, exist_ok=True)
    partial = blob.with_name(blob.name + ".incomplete")
    hasher = hashlib.sha256()
    offset = 0
    if partial.is_file():
        with open(partial, "rb") as fp:
            while chunk := fp.read(_CHUNK):
                hasher.update(chunk)
                offset += len(chunk)
        if offset > part.size:
            partial.unlink()
            hasher, offset = hashlib.sha256(), 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    try:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                raise HubError(_refusal(resp.status_code, "Authorization" in client.headers))
            if offset and resp.status_code != 206:
                hasher, offset = hashlib.sha256(), 0  # the range was ignored: start over
            on_bytes(offset)
            with open(partial, "ab" if offset else "wb") as fp:
                for chunk in resp.iter_bytes(_CHUNK):
                    if cancelled is not None and cancelled.is_set():
                        raise DownloadCancelledError(part.name)
                    fp.write(chunk)
                    hasher.update(chunk)
                    offset += len(chunk)
                    on_bytes(len(chunk))
    except httpx.HTTPError as exc:
        raise HubError(f"The download of {part.name} stopped: {exc}") from exc
    if offset != part.size or hasher.hexdigest() != part.sha256:
        partial.unlink(missing_ok=True)
        raise HubError(f"{part.name} arrived damaged; it was discarded. Try again.")
    os.replace(partial, blob)


def _link(link: Path, blob: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        if link.resolve() == blob.resolve() or not blob.exists():
            return
        link.unlink()
    try:
        link.symlink_to(os.path.relpath(blob, link.parent))
    except OSError:
        # No symlinks (Windows without the privilege): the file itself, as
        # huggingface_hub does.
        os.replace(blob, link)


# --- this computer ----------------------------------------------------------

GiB = 1 << 30


@dataclass(frozen=True)
class Machine:
    memory: int  # RAM, bytes
    budget: int  # what a model may take: the GPU's share of unified memory, else most RAM
    unified: bool  # Apple silicon: the GPU uses the RAM

    def describe(self) -> str:
        # In GiB, as computers are sold: "16 GB" of RAM is 16 GiB.
        memory = f"{round(self.memory / GiB)} GB of memory"
        share = f"about {round(self.budget / GiB)} GB of it for a model"
        return f"{memory}, {share} on the GPU" if self.unified else f"{memory}, {share}"


def machine() -> Machine:
    memory = _total_memory()
    unified = sys.platform == "darwin" and platform.machine() == "arm64"
    if unified:
        # macOS lets the GPU wire about 2/3 of the RAM, 3/4 past 36 GB,
        # unless iogpu.wired_limit_mb says otherwise.
        limit = _sysctl_int(b"iogpu.wired_limit_mb") * (1 << 20)
        budget = limit or int(memory * (0.75 if memory > 36 * GiB else 2 / 3))
    else:
        budget = int(memory * 0.75)  # the system and the app keep the rest
    return Machine(memory, min(budget, memory), unified)


def _total_memory() -> int:
    if sys.platform == "win32":

        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return 8 * GiB
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, AttributeError):
        return 8 * GiB


def _sysctl_int(name: bytes) -> int:
    try:
        libc = ctypes.CDLL(None)
        value = ctypes.c_int64(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if libc.sysctlbyname(name, ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            return 0
        return max(int(value.value), 0)
    except (OSError, AttributeError):
        return 0


def memory_needed(size: int, params: int, context: int) -> int:
    """Memory a model takes: its file, its KV cache for *context* tokens,
    then 0.8 GB and 5 % for the runtime (hfit's estimate).  The KV cache per
    token grows with depth: about 120 KB for small models, 330 KB at 70B."""
    billions = (params or size / 0.6) / 1e9
    kv_per_token = min(120 + 3 * billions, 330) * 1024
    return int(size * 1.05 + kv_per_token * max(context, 0) + 0.8e9)


FITS = "fits"
TIGHT = "tight"
TOO_BIG = "too_big"

FIT_LABELS = {
    FITS: ("Runs well here", "success"),
    TIGHT: ("Tight on memory", "warning"),
    TOO_BIG: ("Too big for this computer", "error"),
}


def fit(size: int, params: int, context: int, here: Machine) -> str:
    need = memory_needed(size, params, context)
    if need <= here.budget * 0.75:
        return FITS
    return TIGHT if need <= here.budget else TOO_BIG


def max_params(here: Machine, context: int = 32768) -> int:
    """The largest model, in parameters, whose Q4 file (0.6 byte a parameter)
    is not too big *here* for *context* tokens: the search's ceiling, judged
    as :func:`fit` judges, so a model it calls tight is not hidden."""
    low, high = 0, 2_000_000_000_000
    while high - low > 50_000_000:
        middle = (low + high) // 2
        if memory_needed(int(middle * 0.6), middle, context) <= here.budget:
            low = middle
        else:
            high = middle
    return max(low, 500_000_000)


def gb(size: int) -> str:
    value = size / 1e9
    return f"{value:.2f} GB" if value < 10 else f"{value:.0f} GB"
