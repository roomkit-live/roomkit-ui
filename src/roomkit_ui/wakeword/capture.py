"""Microphone → VAD → speech segments, as Qt signals.

Shared by enrolment and by the permanent listener: both want the same
thing — whole utterances, not a stream — and the VAD is what makes the
wake word affordable, since the encoder only runs while someone speaks.

Audio arrives on PortAudio's thread and is handed to Qt through a queue
drained by a timer.  Running the VAD inside the audio callback would
risk underruns; running it in the Qt thread keeps every signal emission
on the thread its receivers live on.
"""

from __future__ import annotations

import logging
import queue
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from roomkit_ui.wakeword.resample import StreamResampler

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BLOCK_FRAMES = 320  # 20 ms
_DRAIN_INTERVAL_MS = 20
# Speech threshold for raw (undenoised) mic input.  roomkit's 0.35 default
# assumes a denoiser upstream, which the wake-word path deliberately lacks.
_VAD_THRESHOLD = 0.5
_SILENCE_MS = 500
_MIN_SPEECH_MS = 250
_PRE_ROLL_MS = 300


class SegmentCapture(QObject):
    """Emits one signal per complete utterance heard on the microphone."""

    segment = Signal(bytes, float)  # PCM 16 kHz mono, duration in seconds
    speech_started = Signal()
    level = Signal(float)  # 0-1, for a meter during enrolment
    error = Signal(str)

    def __init__(
        self,
        vad_model_path: str,
        *,
        input_device: int | None = None,
        source: Any = None,
        capture_rate: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._vad_path = vad_model_path
        self._input_device = input_device
        # A shared roomkit capture source, when this install has one.  With it
        # we subscribe instead of opening the device, so a session can start
        # without the microphone ever changing hands.
        self._source = source
        self._subscription: Any = None
        # A shared source dictates its own rate.  Without one we open the
        # device ourselves, at *capture_rate* when given: enrolment asks for
        # the shared source's rate so its takes go through the same
        # conversion as the audio detection will later compare them with.
        self._capture_rate = int(
            getattr(source, "sample_rate", None) or capture_rate or SAMPLE_RATE
        )
        self._resampler: StreamResampler | None = None
        if self._capture_rate != SAMPLE_RATE:
            self._resampler = StreamResampler(self._capture_rate, SAMPLE_RATE)
        self._vad: Any = None
        self._stream: Any = None
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._draining = False
        self._stop_pending = False
        self._timer = QTimer(self)
        self._timer.setInterval(_DRAIN_INTERVAL_MS)
        self._timer.timeout.connect(self._drain)

    @property
    def running(self) -> bool:
        return self._stream is not None or self._subscription is not None

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> bool:
        """Begin receiving audio. Returns False after emitting ``error``."""
        if self.running:
            return True
        try:
            self._vad = self._build_vad()
            if self._resampler is not None:
                self._resampler.reset()  # no history from a previous run
            if self._source is not None:
                # Enqueue and return: the shared source fans out synchronously
                # on its capture thread, and the VAD is far too slow for that.
                self._subscription = self._source.subscribe(
                    lambda frame: self._queue.put(frame.data), name="wakeword"
                )
            else:
                self._stream = self._open_stream()
        except Exception as exc:
            logger.exception("Wake word capture failed to start")
            self._teardown()
            self.error.emit(str(exc))
            return False
        self._timer.start()
        return True

    def mark(self) -> Any:
        """A replay marker on the shared source, or ``None`` without one.

        Taken at SPEECH_START so a session opened later can replay the whole
        utterance — the wake phrase and whatever followed it.
        """
        if self._source is None:
            return None
        return self._source.mark()

    def stop(self) -> None:
        """Release the microphone. Safe to call when already stopped.

        Closing the stream while draining would deadlock: ``stream.stop()``
        waits for the audio callback to return, and a segment handler runs
        inside the drain.  When that happens the teardown is deferred to the
        next event-loop turn instead, once the stack has unwound.
        """
        self._timer.stop()
        if self._draining:
            self._stop_pending = True
            return
        self._stop_pending = False
        self._teardown()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _teardown(self) -> None:
        if self._subscription is not None:
            try:
                # Detach only — the source belongs to whoever created it and
                # keeps running for its other subscribers.
                self._subscription.unsubscribe()
            except Exception:
                logger.exception("Wake word capture: unsubscribe failed")
            self._subscription = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("Wake word capture: stream close failed")
            self._stream = None
        if self._vad is not None:
            try:
                self._vad.close()
            except Exception:
                pass
            self._vad = None

    # -- construction --------------------------------------------------------

    def _build_vad(self) -> Any:
        from roomkit.voice.pipeline.vad.sherpa_onnx import (
            SherpaOnnxVADConfig,
            SherpaOnnxVADProvider,
        )

        return SherpaOnnxVADProvider(
            SherpaOnnxVADConfig(
                model=self._vad_path,
                model_type="ten",
                threshold=_VAD_THRESHOLD,
                silence_threshold_ms=_SILENCE_MS,
                min_speech_duration_ms=_MIN_SPEECH_MS,
                speech_pad_ms=_PRE_ROLL_MS,
            )
        )

    def _open_stream(self) -> Any:
        import sounddevice as sd

        def on_audio(indata, _frames, _time, status) -> None:
            if status:
                logger.debug("Wake word capture status: %s", status)
            self._queue.put(bytes(indata))

        stream = sd.RawInputStream(
            samplerate=self._capture_rate,
            blocksize=self._capture_rate * BLOCK_FRAMES // SAMPLE_RATE,
            dtype="int16",
            channels=1,
            callback=on_audio,
            device=self._input_device,
        )
        stream.start()
        return stream

    # -- processing ----------------------------------------------------------

    def _drain(self) -> None:
        """Feed queued audio through the VAD, on the Qt thread."""
        self._draining = True
        try:
            for _ in range(64):  # bounded: never monopolise the event loop
                try:
                    chunk = self._queue.get_nowait()
                except queue.Empty:
                    return
                self.feed(chunk)
        finally:
            self._draining = False
            if self._stop_pending:
                # A handler asked to stop mid-drain; now the stack has
                # unwound it is safe to close the device.
                QTimer.singleShot(0, self.stop)

    def _to_detection_rate(self, pcm: bytes) -> bytes:
        """Resample a block to 16 kHz, the rate the VAD and encoder expect.

        A shared source runs at the transport's rate — 24 kHz for every
        realtime provider but ElevenLabs — while speech models here are
        16 kHz.  Enrolment and detection both go through this, so the
        fingerprints stay comparable to what detection later measures.
        """
        if self._resampler is None:
            return pcm
        return self._resampler.process(pcm)

    def feed(self, pcm: bytes) -> None:
        """Push one block through the VAD (public so it can be driven in tests)."""
        if self._vad is None:
            return
        pcm = self._to_detection_rate(pcm)
        from roomkit.voice.audio_frame import AudioFrame
        from roomkit.voice.pipeline.vad.base import VADEventType

        try:
            event = self._vad.process(AudioFrame(data=pcm, sample_rate=SAMPLE_RATE), "wakeword")
        except Exception:
            logger.exception("Wake word VAD failed — block dropped")
            return
        if event is None:
            return

        if event.type == VADEventType.SPEECH_START:
            self.speech_started.emit()
        elif event.type == VADEventType.AUDIO_LEVEL and event.level_db is not None:
            self.level.emit(max(0.0, min(1.0, (event.level_db + 60.0) / 60.0)))
        elif event.type == VADEventType.SPEECH_END and event.audio_bytes:
            # audio_bytes carries the whole utterance including the pre-roll,
            # so the start of the phrase is never clipped.
            audio = event.audio_bytes
            self.segment.emit(audio, len(audio) / (SAMPLE_RATE * 2))
