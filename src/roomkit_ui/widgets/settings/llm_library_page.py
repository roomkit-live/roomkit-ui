"""Local LLMs for llama.cpp: recommended models, a Hugging Face search and the
models already on this computer.

Downloads run through ``model_jobs`` (they outlive the dialog) into the
Hugging Face cache, where a session finds them (``gguf_models.resolve``).
Whether a model fits is an estimate shown as a badge: it warns, it never
refuses a download.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from roomkit_ui import gguf_models as hub
from roomkit_ui.providers.llamacpp import DEFAULT_CONTEXT
from roomkit_ui.widgets.settings.controls import FeedbackLabel, SettingsSection, StatusBadge, label
from roomkit_ui.widgets.settings.model_jobs import DownloadState, model_downloads
from roomkit_ui.widgets.settings.model_library import LibraryModel, Progress
from roomkit_ui.widgets.settings.models_widgets import _ModelRow

logger = logging.getLogger(__name__)

_RESULTS = 20


def model_id(reference: str) -> str:
    """A GGUF download's ID in ``model_jobs``."""
    return f"gguf:{reference}"


async def download_gguf(repo: str, quant: str, token: str, progress: Progress) -> None:
    """Read *repo* again (its commit, each file's SHA-256), then download
    *quant* on a worker thread.  Cancelling stops it between chunks; what
    arrived stays for the next try."""
    info = await hub.HubClient(token).repo(repo)
    file = info.quant(quant)
    if file is None:
        raise hub.HubError(f"{repo} no longer offers {quant}.")
    cancelled = threading.Event()
    job = asyncio.ensure_future(
        asyncio.to_thread(
            hub.download,
            file,
            info.commit,
            token=token,
            progress=progress,
            cancelled=cancelled,
        )
    )
    try:
        await asyncio.shield(job)
    except asyncio.CancelledError:
        cancelled.set()
        with contextlib.suppress(Exception):
            await job
        raise


def _params(params: int) -> str:
    value = params / 1e9
    return f"{value:.1f}B".replace(".0B", "B") if value >= 1 else f"{params / 1e6:.0f}M"


def _count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1e6:.1f}M".replace(".0M", "M")
    return f"{value / 1e3:.0f}k" if value >= 1000 else str(value)


def _context(settings: dict) -> int:
    try:
        value = int(str(settings.get("vc_llamacpp_context", "") or "").strip())
    except ValueError:
        return DEFAULT_CONTEXT
    return value if value > 0 else DEFAULT_CONTEXT


def _params_of(reference: str) -> int:
    """A recommended model's parameter count; 0 (estimated from the file) otherwise."""
    known = hub.recommended(reference)
    return known.params if known else 0


class _HubResult(QWidget):
    """A search result: the repository, then its sizes once asked for."""

    def __init__(self, model: hub.HubModel, page: LLMLibrary) -> None:
        super().__init__()
        self.setObjectName("settingsLibraryItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAccessibleName(model.repo)
        self.model = model
        self.info: hub.RepoInfo | None = None
        self._page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        layout.addWidget(label(model.repo, "settingsRowTitle"))
        facts = [
            f"{_params(model.params)} parameters" if model.params else "",
            f"{_count(model.downloads)} downloads",
            "tool calls" if model.tools else "no tool calls declared",
            "gated: needs an access token" if model.gated else "",
        ]
        layout.addWidget(label(" · ".join(f for f in facts if f), "settingsHint"))
        actions = QHBoxLayout()
        self.quants = QComboBox()
        self.quants.setAccessibleName(f"Size of {model.repo}")
        self.quants.hide()
        self.quants.currentIndexChanged.connect(lambda _i: self.refresh())
        actions.addWidget(self.quants)
        self.badge = StatusBadge()
        self.badge.hide()
        actions.addWidget(self.badge)
        actions.addStretch(1)
        self.sizes_btn = QPushButton("Show sizes")
        self.download_btn = QPushButton("Download")
        self.cancel_btn = QPushButton("Cancel")
        for button, verb in (
            (self.sizes_btn, "Show the sizes of"),
            (self.download_btn, "Download"),
            (self.cancel_btn, "Cancel the download of"),
        ):
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(f"{verb} {model.repo}")
            actions.addWidget(button)
        self.download_btn.hide()
        self.cancel_btn.hide()
        layout.addLayout(actions)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("settingsDownloadProgress")
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.error = label("", "settingsError")
        self.error.setTextFormat(Qt.PlainText)
        self.error.hide()
        layout.addWidget(self.error)
        self.sizes_btn.clicked.connect(lambda: page.load_sizes(self))
        self.download_btn.clicked.connect(lambda: page.download(self.selected(), self.model))
        self.cancel_btn.clicked.connect(lambda: page.cancel(self.selected()))

    def selected(self) -> hub.GGUFFile | None:
        if self.info is None or self.quants.currentIndex() < 0:
            return None
        return self.info.quants[self.quants.currentIndex()]

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def set_info(self, info: hub.RepoInfo) -> None:
        """List *info*'s sizes, the best one for this computer selected."""
        self.info = info
        self.sizes_btn.hide()
        if not info.quants:
            self.show_error("This repository lists no GGUF file RoomKit can check.")
            return
        page = self._page
        self.quants.blockSignals(True)
        for quant in info.quants:
            verdict = page.fit(quant.size, self.model.params)
            self.quants.addItem(f"{quant.quant} · {hub.gb(quant.size)}")
            self.quants.setItemData(
                self.quants.count() - 1, hub.FIT_LABELS[verdict][0], Qt.ToolTipRole
            )
        self.quants.setCurrentIndex(self._best(info))
        self.quants.blockSignals(False)
        self.quants.show()
        self.refresh()

    def _best(self, info: hub.RepoInfo) -> int:
        """Q4_K_M when it is not too big; else the largest that runs well; else the smallest."""
        verdicts = [self._page.fit(q.size, self.model.params) for q in info.quants]
        for i, quant in enumerate(info.quants):
            if quant.quant.upper() == hub.DEFAULT_QUANT and verdicts[i] != hub.TOO_BIG:
                return i
        fitting = [i for i, verdict in enumerate(verdicts) if verdict == hub.FITS]
        return fitting[-1] if fitting else 0

    def refresh(self) -> None:
        quant = self.selected()
        if quant is None:
            return
        state = self._page.state(quant.reference)
        phase = state.phase if state else ""
        active = phase in {"resolving", "downloading"}
        downloaded = not active and hub.cached(quant.reference) is not None
        self.badge.set_status(
            *(
                ("Downloaded", "success")
                if downloaded
                else hub.FIT_LABELS[self._page.fit(quant.size, self.model.params)]
            )
        )
        self.badge.show()
        self.download_btn.setVisible(not active and not downloaded)
        self.download_btn.setText("Retry download" if phase == "error" else "Download")
        self.cancel_btn.setVisible(active)
        self.quants.setEnabled(not active)
        self.progress_bar.setVisible(active)
        self.progress_bar.setRange(0, 0 if phase == "resolving" else 100)
        self.progress_bar.setValue(state.percent if state else 0)
        self.show_error(state.error if state else "")


class LLMLibrary(QWidget):
    """The LLMs tab of Models & components."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        saved = str(settings.get("huggingface_token", "") or "")
        # Replaced by the panel with the Providers & keys field, unsaved edits included.
        self.token: Callable[[], str] = lambda: saved
        self._saved_token = saved
        self.machine = hub.machine()
        self.context = _context(settings)
        self._runner = model_downloads()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(
            label(
                f"This computer: {self.machine.describe()}. Whether a model fits is an "
                f"estimate for a {self.context:,}-token context: its file, its memory for "
                "the conversation and a margin. One marked too big may not load, or run "
                "slowly. Downloads continue when you close Settings; choose a downloaded "
                "model in Conversation → Think · LLM, the Agent tab or Text chat.",
                "settingsHint",
            )
        )

        self.recommended = SettingsSection(
            "Recommended",
            "Checked for conversation and tool calls, smallest first. Q4_K_M keeps most "
            "of a model's quality at about a third of its size.",
        )
        self.rows: dict[str, _ModelRow] = {}
        for rec in hub.RECOMMENDED:
            model = self._library_model(
                rec.reference,
                rec.name,
                f"{rec.note} · {_params(rec.params)} parameters · {rec.quant}",
                hub.gb(rec.size),
            )
            self._add_row(self.recommended, model, self.fit(rec.size, rec.params))
        layout.addWidget(self.recommended)

        self.search_section = SettingsSection(
            "Search Hugging Face",
            "Models llama.cpp runs, most downloaded first. Anyone can publish there: a "
            "model may not call tools well, or may need a newer llama.cpp than RoomKit's.",
        )
        box = QWidget()
        form = QVBoxLayout(box)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search models (qwen, llama, gemma, mistral…)")
        self.search.setAccessibleName("Search Hugging Face models")
        self.search.setClearButtonEnabled(True)
        form.addWidget(self.search)
        self.fits_only = QCheckBox("Only models this computer can run")
        self.fits_only.setChecked(True)
        form.addWidget(self.fits_only)
        self.status = FeedbackLabel()
        form.addWidget(self.status)
        self.search_section.content.addWidget(box)
        self.results: list[_HubResult] = []
        layout.addWidget(self.search_section)

        self.local = SettingsSection(
            "On this computer",
            f"GGUF models in the Hugging Face cache ({hub.hub_cache()}), including those "
            "llama.cpp downloaded on its own.",
        )
        self.local_empty = label("No GGUF model downloaded yet.", "settingsHint")
        self.local_empty.setContentsMargins(18, 16, 18, 16)
        self.local.content.addWidget(self.local_empty)
        self.local_rows: dict[str, _ModelRow] = {}
        self._local_refs: tuple[str, ...] | None = None
        layout.addWidget(self.local)

        self._searched = False
        self._seq = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.search_now)
        self.search.textChanged.connect(lambda _text: self._timer.start())
        self.fits_only.toggled.connect(lambda _checked: self._timer.start())
        self._runner.changed.connect(self._download_changed)
        self.refresh()

    # --- shared ---------------------------------------------------------

    def fit(self, size: int, params: int) -> str:
        return hub.fit(size, params, self.context, self.machine)

    def state(self, reference: str) -> DownloadState | None:
        return self._runner.states.get(model_id(reference))

    def _token_now(self) -> str:
        try:
            return self.token()
        except RuntimeError:  # the Providers field went with the dialog
            return self._saved_token

    def _library_model(self, reference: str, name: str, detail: str, size: str) -> LibraryModel:
        repo, _, quant = reference.partition(":")
        token = self._token_now

        async def download(progress: Progress) -> None:
            await download_gguf(repo, quant, token(), progress)

        def delete() -> None:
            model = hub.cached(reference)
            if model is not None:
                hub.delete(model)

        return LibraryModel(
            model_id(reference),
            name,
            detail,
            size,
            lambda: hub.cached(reference) is not None,
            download,
            delete,
            cancellable=True,
        )

    def _add_row(
        self, section: SettingsSection, model: LibraryModel, verdict: str, *, local: bool = False
    ) -> _ModelRow:
        row = _ModelRow(model, badge=hub.FIT_LABELS[verdict])
        row.action_btn.clicked.connect(lambda _checked=False, m=model: self._runner.start(m))
        row.cancel_btn.clicked.connect(lambda _checked=False, m=model: self._runner.cancel(m.id))
        row.delete_btn.clicked.connect(lambda _checked=False, m=model: self._delete(m))
        section.content.addWidget(row)
        rows = self.local_rows if local else self.rows
        rows[model.id] = row
        row.refresh(self._runner.states.get(model.id))
        return row

    def _delete(self, model: LibraryModel) -> None:
        state = self._runner.states.get(model.id)
        if state and state.phase in {"resolving", "downloading"}:
            return
        try:
            model.delete()
        except OSError as exc:
            row = self.rows.get(model.id) or self.local_rows.get(model.id)
            if row is not None:
                row.error.setText(f"Could not delete files: {exc}")
                row.error.show()
            return
        self._runner.clear(model.id)  # its rows and lists refresh from the signal

    def download(self, quant: hub.GGUFFile | None, model: hub.HubModel) -> None:
        if quant is None:
            return
        name = f"{model.repo.rsplit('/', 1)[-1]} · {quant.quant}"
        self._runner.start(
            self._library_model(quant.reference, name, model.repo, hub.gb(quant.size))
        )

    def cancel(self, quant: hub.GGUFFile | None) -> None:
        if quant is not None:
            self._runner.cancel(model_id(quant.reference))

    def refresh(self) -> None:
        for key, row in self.rows.items():
            row.refresh(self._runner.states.get(key))
        for result in self.results:
            result.refresh()
        self._rebuild_local()
        if self.isVisible() and not self._searched:
            self.search_now()

    @Slot(str)
    def _download_changed(self, key: str) -> None:
        if not key.startswith("gguf:"):
            return
        state = self._runner.states.get(key)
        if key in self.rows:
            self.rows[key].refresh(state)
        if key in self.local_rows:
            self.local_rows[key].refresh(state)
        for result in self.results:
            quant = result.selected()
            if quant is not None and model_id(quant.reference) == key:
                result.refresh()
        if state is None or state.phase == "error":
            self._rebuild_local()

    # --- on this computer ------------------------------------------------

    def _rebuild_local(self) -> None:
        """List the cache again; rows change only when what is there does."""
        models = hub.cached_models()
        refs = tuple(m.reference for m in models)
        if refs == self._local_refs:
            return
        self._local_refs = refs
        for row in self.local_rows.values():
            row.hide()
            row.deleteLater()
        self.local_rows.clear()
        for cached in models:
            model = LibraryModel(
                model_id(cached.reference),
                cached.name,
                f"{cached.repo} · {cached.quant}",
                hub.gb(cached.size),
                lambda: True,
                _nothing,
                partial(hub.delete, cached),
            )
            verdict = self.fit(cached.size, _params_of(cached.reference))
            self._add_row(self.local, model, verdict, local=True)
        self.local_empty.setVisible(not models)

    # --- search ------------------------------------------------------------

    def search_now(self) -> None:
        self._timer.stop()
        self._searched = True
        self._seq += 1
        fits_only = self.fits_only.isChecked()
        max_params = hub.max_params(self.machine, self.context) if fits_only else 0
        if _schedule(self.run_search(self.search.text().strip(), max_params, self._seq)):
            self.status.set_status("Searching Hugging Face…", "active")

    async def run_search(self, query: str, max_params: int, seq: int) -> None:
        try:
            models = await hub.HubClient(self._token_now()).search(
                query, max_params=max_params, limit=_RESULTS
            )
        except Exception as exc:
            if not isinstance(exc, hub.HubError):
                logger.exception("Hugging Face search failed")
            if self._latest(seq):
                self.status.set_status(f"Search failed: {exc}", "error")
            return
        if not self._latest(seq):
            return
        self._render(models)
        if models:
            self.status.set_status(f"{len(models)} most downloaded models", "neutral")
        else:
            self.status.set_status(
                "No model found. Try another name"
                + (", or turn off “Only models this computer can run”." if max_params else "."),
                "neutral",
            )

    def _latest(self, seq: int) -> bool:
        """Whether search *seq* may still update the tab: answers arrive out of
        order, and none may touch the tab once Settings has closed."""
        return isValid(self) and seq == self._seq

    def _render(self, models: list[hub.HubModel]) -> None:
        for result in self.results:
            result.hide()
            result.deleteLater()
        self.results = []
        for model in models:
            result = _HubResult(model, self)
            self.search_section.content.addWidget(result)
            self.results.append(result)

    def load_sizes(self, result: _HubResult) -> None:
        if _schedule(self.read_sizes(result)):
            result.sizes_btn.setEnabled(False)
            result.sizes_btn.setText("Reading…")

    async def read_sizes(self, result: _HubResult) -> None:
        try:
            info = await hub.HubClient(self._token_now()).repo(result.model.repo)
        except Exception as exc:
            if not isinstance(exc, hub.HubError):
                logger.exception("Reading %s failed", result.model.repo)
            if isValid(result):
                result.sizes_btn.setEnabled(True)
                result.sizes_btn.setText("Show sizes")
                result.show_error(str(exc))
            return
        if isValid(result):
            result.set_info(info)


def _schedule(coro: Coroutine[Any, Any, None]) -> bool:
    """Run *coro* on the app's loop; False, and nothing started, without one
    (a test, or the app closing)."""
    try:
        asyncio.get_running_loop().create_task(coro)  # qasync's, in the app
    except RuntimeError:
        coro.close()
        return False
    return True


async def _nothing(_progress: Progress) -> None:
    """A model already on disk has nothing to download."""
