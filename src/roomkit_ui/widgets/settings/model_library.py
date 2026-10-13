"""The local model catalogue, grouped by use, with each kind's own operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from roomkit_ui import model_catalog as catalog
from roomkit_ui import model_manager as models

Progress = Callable[[int, int], None]
Download = Callable[[Progress], Awaitable[None]]


@dataclass(frozen=True)
class LibraryModel:
    id: str
    name: str
    detail: str
    size: str
    downloaded: Callable[[], bool]
    download: Download
    delete: Callable[[], None]
    # Its download stops on Cancel and resumes later (model_jobs.cancel).
    cancellable: bool = False


@dataclass(frozen=True)
class ModelGroup:
    key: str
    title: str
    description: str
    models: tuple[LibraryModel, ...]


def wakeword_encoder_model() -> LibraryModel:
    async def download(progress: Progress) -> None:
        from roomkit_ui.wakeword.encoder_download import download_encoder

        await download_encoder(progress)

    return LibraryModel(
        catalog.WAKEWORD_ENCODER_ID,
        "Wake-word encoder",
        "Recognize your wake phrase locally · Whisper tiny encoder",
        catalog.WAKEWORD_ENCODER_SIZE,
        catalog.is_wakeword_encoder_downloaded,
        download,
        lambda: catalog.wakeword_encoder_path().unlink(missing_ok=True),
    )


def model_groups() -> tuple[ModelGroup, ...]:
    return (
        ModelGroup(
            "transcription",
            "Transcription",
            "Turn speech into text for local dictation and Voice Channel conversations.",
            tuple(
                LibraryModel(
                    m.id,
                    m.name,
                    f"Speech to text · {m.type}",
                    m.size,
                    partial(models.is_model_downloaded, m.id),
                    partial(models.download_model, m.id),
                    partial(models.delete_model, m.id),
                )
                for m in models.STT_MODELS
            ),
        ),
        ModelGroup(
            "speech",
            "Speech & voices",
            "Piper voices run locally. Download the shared pronunciation data once.",
            (
                LibraryModel(
                    "espeak-ng-data",
                    "espeak-ng data",
                    "Shared pronunciation data for Piper",
                    "~1 MB",
                    models.is_espeak_ng_downloaded,
                    models.download_espeak_ng_data,
                    models.delete_espeak_ng_data,
                ),
                *(
                    LibraryModel(
                        m.id,
                        m.name,
                        "Text to speech · Piper",
                        m.size,
                        partial(models.is_tts_model_downloaded, m.id),
                        partial(models.download_tts_model, m.id),
                        partial(models.delete_tts_model, m.id),
                    )
                    for m in models.TTS_MODELS
                ),
            ),
        ),
        ModelGroup(
            "audio",
            "Audio processing",
            "Detect speech, reduce noise and recognize when a speaking turn is complete.",
            (
                *(
                    LibraryModel(
                        m.id,
                        m.name,
                        "Voice activity detection · VAD",
                        m.size,
                        partial(models.is_vad_model_downloaded, m.id),
                        partial(models.download_vad_model, m.id),
                        partial(models.delete_vad_model, m.id),
                    )
                    for m in models.VAD_MODELS
                ),
                LibraryModel(
                    models.GTCRN_MODEL_ID,
                    "GTCRN",
                    "Noise reduction · Voice Channel",
                    models.GTCRN_SIZE,
                    models.is_gtcrn_downloaded,
                    models.download_gtcrn,
                    models.delete_gtcrn,
                ),
                LibraryModel(
                    models.SMART_TURN_MODEL_ID,
                    "Smart Turn v3.2",
                    "Turn completion · CPU, int8",
                    models.SMART_TURN_SIZE,
                    models.is_smart_turn_downloaded,
                    models.download_smart_turn,
                    models.delete_smart_turn,
                ),
            ),
        ),
        ModelGroup(
            "speakers",
            "Speaker recognition",
            "Tell voices apart in Voice Channel conversations.",
            tuple(
                LibraryModel(
                    m.id,
                    m.name,
                    "Speaker identification",
                    m.size,
                    partial(models.is_speaker_model_downloaded, m.id),
                    partial(models.download_speaker_model, m.id),
                    partial(models.delete_speaker_model, m.id),
                )
                for m in models.SPEAKER_MODELS
            ),
        ),
        ModelGroup(
            "wakeword",
            "Wake word",
            "Record and manage your phrase in Wake Word. Detection also uses TEN VAD.",
            (wakeword_encoder_model(),),
        ),
    )
