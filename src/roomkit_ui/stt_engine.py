"""STT engine — records speech via a roomkit STT room and pastes transcribed text."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from typing import Any

from PySide6.QtCore import QObject, Signal

from roomkit_ui.model_manager import build_stt_config, is_model_downloaded, is_streaming_model
from roomkit_ui.settings import load_settings

logger = logging.getLogger(__name__)


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _copy_to_clipboard(text: str) -> None:
    """Copy *text* to the system clipboard."""
    if sys.platform == "darwin":
        subprocess.run(
            ["pbcopy"],
            input=text.encode(),
            check=True,
            timeout=5,
        )
    elif _is_wayland():
        subprocess.run(
            ["wl-copy", "--", text],
            check=True,
            timeout=5,
        )
    else:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(),
            check=True,
            timeout=5,
        )


def _is_terminal_focused() -> bool:
    """Check if the focused X11 window is a terminal emulator."""
    try:
        # Get active window ID
        wid_result = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        wid = wid_result.stdout.strip()
        if not wid:
            return False
        # Get WM_CLASS via xprop (works on all xdotool versions)
        result = subprocess.run(
            ["xprop", "-id", wid, "WM_CLASS"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        wm_class = result.stdout.strip().lower()
        terminal_classes = (
            "terminal",
            "konsole",
            "alacritty",
            "kitty",
            "xterm",
            "urxvt",
            "tilix",
            "terminator",
            "gnome-terminal",
            "xfce4-terminal",
            "mate-terminal",
            "sakura",
            "st",
            "wezterm",
            "foot",
            "claude",
        )
        return any(t in wm_class for t in terminal_classes)
    except Exception:
        return False


def _simulate_paste() -> bool:
    """Simulate paste keystroke into the focused window.

    Terminals typically use Ctrl+Shift+V, while other apps use Ctrl+V.
    Returns True on success, False if permission is missing.
    """
    if sys.platform == "darwin":
        # Use AppleScript via System Events — this is more reliable than
        # CGEventPost from PyInstaller bundles, where CGEventPost silently
        # drops events even when Accessibility permission is granted.
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "v" using command down',
                ],
                check=True,
                timeout=5,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "AppleScript paste failed (rc=%d): %s",
                exc.returncode,
                exc.stderr.decode(errors="replace").strip(),
            )
            return False
    elif _is_wayland():
        subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], check=True, timeout=5)
    elif _is_terminal_focused():
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"],
            check=True,
            timeout=5,
        )
    else:
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True, timeout=5)
    return True


def _get_frontmost_bundle() -> str | None:
    """Return the bundle ID of the frontmost app (macOS only).

    Returns None if the frontmost app is our own process, since restoring
    focus to ourselves would cause the paste to go to the wrong window.
    """
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front and front.processIdentifier() != os.getpid():
            return front.bundleIdentifier()
        return None
    except Exception:
        return None


def _activate_bundle(bundle_id: str) -> None:
    """Bring an app to the front by bundle ID (macOS only)."""
    if sys.platform != "darwin" or not bundle_id:
        return
    try:
        from AppKit import NSRunningApplication

        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps:
            # 3 = NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps
            apps[0].activateWithOptions_(3)
            logger.info("Activated app: %s", bundle_id)
    except Exception:
        logger.exception("Failed to activate app: %s", bundle_id)


class STTEngine(QObject):
    """Records speech via a roomkit STT room and pastes the result.

    Supports two providers:
    - **OpenAI**: ``RealtimeVoiceChannel`` with ``create_response=False``
    - **Local**: ``VoiceChannel`` with ``SherpaOnnxSTTProvider`` + ``LocalAudioBackend``
    """

    recording_changed = Signal(bool)
    text_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recording = False
        self._busy = False  # guards against overlapping start/stop
        self._kit: Any = None
        self._channel: Any = None
        self._session: Any = None
        self._provider: Any = None
        self._transport: Any = None
        self._accumulated_text: list[str] = []
        self._transcription_event: asyncio.Event | None = None
        self._prev_app: str | None = None  # bundle ID of app that was focused before recording
        # Local STT state (VoiceChannel + LocalAudioBackend)
        self._local_provider: Any = None
        self._local_backend: Any = None
        self._local_session: Any = None
        self._local_flush_event: asyncio.Event | None = None
        self._batch_mode: bool = False

    @property
    def recording(self) -> bool:
        return self._recording

    def toggle_recording(self) -> None:
        logger.info(
            "toggle_recording: recording=%s busy=%s",
            self._recording,
            self._busy,
        )
        if self._recording:
            asyncio.ensure_future(self._stop_recording())
        else:
            asyncio.ensure_future(self._start_recording())

    # -- transcription callback ------------------------------------------------

    def _on_transcription(self, _session: Any, text: str, role: str, is_final: bool) -> None:
        if role == "user" and is_final and text.strip():
            logger.info("STT transcription (final): %s", text)
            self._accumulated_text.append(text.strip())
            if self._transcription_event is not None:
                self._transcription_event.set()

    # -- lifecycle -------------------------------------------------------------

    async def _start_recording(self) -> None:
        if self._recording or self._busy:
            logger.warning(
                "_start_recording skipped: recording=%s busy=%s",
                self._recording,
                self._busy,
            )
            return

        self._busy = True
        self._recording = True
        self.recording_changed.emit(True)
        self._accumulated_text.clear()
        self._prev_app = _get_frontmost_bundle()
        logger.info("Saved frontmost app: %s", self._prev_app)

        # --- Fake mode: skip roomkit, just use hardcoded text ---
        if os.environ.get("STT_FAKE"):
            logger.info("STT fake mode — will paste test text on stop")
            self._busy = False
            return

        settings = load_settings()
        stt_provider = settings.get("stt_provider", "openai")

        if stt_provider == "local":
            await self._start_local_recording(settings)
        elif stt_provider == "deepgram":
            await self._start_deepgram_recording(settings)
        else:
            await self._start_openai_recording(settings)

    async def _start_openai_recording(self, settings: dict) -> None:
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            self.error_occurred.emit(
                "OpenAI API key is required for dictation. Open Settings to enter it."
            )
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)
            return

        try:
            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.providers.openai.realtime import OpenAIRealtimeProvider
            from roomkit.voice.realtime.local_transport import LocalAudioTransport

            self._kit = RoomKit()

            self._provider = OpenAIRealtimeProvider(
                api_key=api_key,
                model=settings.get("openai_model", "gpt-4o-realtime-preview"),
            )
            self._provider.on_transcription(self._on_transcription)
            provider = self._provider

            sample_rate = 24000
            input_device = settings.get("input_device")

            transport = LocalAudioTransport(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=20,
                mute_mic_during_playback=False,
                input_device=input_device,
            )
            self._transport = transport

            self._channel = RealtimeVoiceChannel(
                "stt",
                provider=provider,
                transport=transport,
                input_sample_rate=sample_rate,
            )
            self._kit.register_channel(self._channel)

            await self._kit.create_room(room_id="stt-room")
            await self._kit.attach_channel("stt-room", "stt")

            self._session = await self._channel.start_session(
                "stt-room",
                "stt-user",
                connection=None,
                metadata={
                    "provider_config": {
                        "turn_detection_type": "server_vad",
                        "create_response": False,
                    },
                },
            )

            # Set transcription language if configured.
            stt_language = settings.get("stt_language", "")
            if stt_language:
                await self._provider.send_event(
                    self._session,
                    {
                        "type": "session.update",
                        "session": {
                            "input_audio_transcription": {
                                "model": "gpt-4o-transcribe",
                                "language": stt_language,
                            },
                        },
                    },
                )
                logger.info("Set STT language: %s", stt_language)

            logger.info(
                "Dictation started: provider=openai, model=%s, rate=%dHz",
                settings.get("openai_model", "gpt-4o-realtime-preview"),
                sample_rate,
            )

        except Exception as exc:
            logger.exception("Failed to start STT session")
            self._recording = False
            self.recording_changed.emit(False)
            self.error_occurred.emit(str(exc))
            await self._cleanup()
        finally:
            self._busy = False

    # -- local STT (VoiceChannel + LocalAudioBackend + SherpaOnnxSTTProvider) --

    async def _start_local_recording(self, settings: dict) -> None:
        model_id = settings.get("stt_model", "")
        if not model_id:
            self.error_occurred.emit(
                "No local STT model selected. Go to Settings → AI Models to choose one."
            )
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)
            return

        if not is_model_downloaded(model_id):
            self.error_occurred.emit(
                f"Model '{model_id}' is not downloaded. Go to Settings → AI Models to download it."
            )
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)
            return

        try:
            from roomkit import (
                ChannelBinding,
                ChannelType,
                HookExecution,
                HookResult,
                HookTrigger,
                RoomKit,
                VoiceChannel,
            )
            from roomkit.voice.backends.local import LocalAudioBackend
            from roomkit.voice.pipeline import AudioPipelineConfig
            from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTProvider
        except ImportError as exc:
            self.error_occurred.emit(
                f"Missing dependency for local STT: {exc}. Install with: pip install sherpa-onnx"
            )
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)
            return

        try:
            language = settings.get("stt_language", "") or "en"
            translate = bool(settings.get("stt_translate", False))
            inference_device = settings.get("inference_device", "cpu")
            config = build_stt_config(
                model_id,
                language,
                translate=translate,
                provider=inference_device,
            )
            # Dictation: the user controls start/stop, so disable endpoint
            # detection — we get one single final result on flush instead
            # of splitting the transcription into segments at pauses.
            config.enable_endpoint_detection = False
            stt_provider = SherpaOnnxSTTProvider(config)

            self._local_provider = stt_provider
            self._batch_mode = not is_streaming_model(model_id)
            input_device = settings.get("input_device")

            backend = LocalAudioBackend(
                input_sample_rate=16000,
                output_sample_rate=16000,
                channels=1,
                block_duration_ms=20,
                input_device=input_device,
            )
            self._local_backend = backend

            voice = VoiceChannel(
                "stt",
                stt=stt_provider,
                backend=backend,
                pipeline=AudioPipelineConfig(),
                batch_mode=self._batch_mode,
            )
            self._channel = voice

            self._kit = RoomKit()
            self._kit.register_channel(voice)

            await self._kit.create_room(room_id="stt-room")
            await self._kit.attach_channel("stt-room", "stt")

            if not self._batch_mode:
                # Streaming: capture transcriptions via hook
                accumulated = self._accumulated_text

                @self._kit.hook(
                    HookTrigger.ON_PARTIAL_TRANSCRIPTION,
                    execution=HookExecution.ASYNC,
                )
                async def _on_partial(result, ctx):
                    logger.info("Local STT partial: %s", result.text)

                self._local_flush_event = asyncio.Event()
                flush_event = self._local_flush_event

                @self._kit.hook(HookTrigger.ON_TRANSCRIPTION)
                async def _on_transcription(text, ctx):
                    if text and text.strip():
                        logger.info("Local STT final: %s", text)
                        accumulated.append(text.strip())
                    flush_event.set()
                    return HookResult.block("dictation-only")

            # Connect backend, bind session, start listening.
            self._local_session = await backend.connect("stt-room", "stt-user", "stt")
            binding = ChannelBinding(
                room_id="stt-room",
                channel_id="stt",
                channel_type=ChannelType.VOICE,
            )
            voice.bind_session(self._local_session, "stt-room", binding)
            await backend.start_listening(self._local_session)

            mode = "batch" if self._batch_mode else "streaming"
            task = "translate" if translate else "transcribe"
            logger.info(
                "Dictation started: provider=local, model=%s, mode=%s, task=%s, rate=16000Hz",
                model_id,
                mode,
                task,
            )

        except Exception as exc:
            logger.exception("Failed to start local STT session")
            self._recording = False
            self.recording_changed.emit(False)
            self.error_occurred.emit(str(exc))
            self._cleanup_local()
        finally:
            self._busy = False

    # -- Deepgram STT (VoiceChannel + LocalAudioBackend + DeepgramSTTProvider) --

    async def _start_deepgram_recording(self, settings: dict) -> None:
        api_key = settings.get("deepgram_api_key", "")
        if not api_key:
            self.error_occurred.emit(
                "Deepgram API key is required for dictation. Open Settings to enter it."
            )
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)
            return

        try:
            from roomkit import (
                ChannelBinding,
                ChannelType,
                HookResult,
                HookTrigger,
                RoomKit,
                VoiceChannel,
            )
            from roomkit.voice.backends.local import LocalAudioBackend
            from roomkit.voice.pipeline import AudioPipelineConfig
            from roomkit.voice.stt.deepgram import DeepgramConfig, DeepgramSTTProvider
        except ImportError as exc:
            self.error_occurred.emit(f"Missing dependency for Deepgram STT: {exc}.")
            self._recording = False
            self._busy = False
            self.recording_changed.emit(False)
            return

        try:
            language = settings.get("stt_language", "") or "en"
            dg_config = DeepgramConfig(
                api_key=api_key,
                model=settings.get("deepgram_model", "nova-3"),
                language=language,
            )
            stt_provider = DeepgramSTTProvider(dg_config)

            self._local_provider = stt_provider
            self._batch_mode = False  # Deepgram is always streaming
            input_device = settings.get("input_device")

            backend = LocalAudioBackend(
                input_sample_rate=16000,
                output_sample_rate=16000,
                channels=1,
                block_duration_ms=20,
                input_device=input_device,
            )
            self._local_backend = backend

            voice = VoiceChannel(
                "stt",
                stt=stt_provider,
                backend=backend,
                pipeline=AudioPipelineConfig(),
                batch_mode=False,
            )
            self._channel = voice

            self._kit = RoomKit()
            self._kit.register_channel(voice)

            await self._kit.create_room(room_id="stt-room")
            await self._kit.attach_channel("stt-room", "stt")

            # Streaming: capture transcriptions via hook
            accumulated = self._accumulated_text
            self._local_flush_event = asyncio.Event()
            flush_event = self._local_flush_event

            @self._kit.hook(HookTrigger.ON_TRANSCRIPTION)
            async def _on_transcription(text, ctx):
                if text and text.strip():
                    logger.info("Deepgram STT final: %s", text)
                    accumulated.append(text.strip())
                flush_event.set()
                return HookResult.block("dictation-only")

            # Connect backend, bind session, start listening.
            self._local_session = await backend.connect("stt-room", "stt-user", "stt")
            binding = ChannelBinding(
                room_id="stt-room",
                channel_id="stt",
                channel_type=ChannelType.VOICE,
            )
            voice.bind_session(self._local_session, "stt-room", binding)
            await backend.start_listening(self._local_session)

            logger.info(
                "Dictation started: provider=deepgram, model=%s, language=%s, rate=16000Hz",
                dg_config.model,
                language,
            )

        except Exception as exc:
            logger.exception("Failed to start Deepgram STT session")
            self._recording = False
            self.recording_changed.emit(False)
            self.error_occurred.emit(str(exc))
            self._cleanup_local()
        finally:
            self._busy = False

    async def _stop_recording(self) -> None:
        if not self._recording:
            return
        if self._busy:
            # Start is still in progress; just flag recording off so it
            # won't continue once start finishes.
            self._recording = False
            self.recording_changed.emit(False)
            return

        self._recording = False
        self.recording_changed.emit(False)
        logger.info("STT recording stopped")

        try:
            if os.environ.get("STT_FAKE"):
                self._accumulated_text.append("Hello, this is a test transcription.")
            elif self._local_provider is not None:
                await self._stop_local_recording()
            else:
                # Only commit if we don't already have text from VAD —
                # committing an empty buffer causes a harmless but noisy error.
                if not self._accumulated_text:
                    await self._commit_and_wait()

            # Emit / paste the text BEFORE cleanup (cleanup is slow).
            text = " ".join(self._accumulated_text).strip()
            if text:
                logger.info("Emitting text_ready: %s", text[:80])
                # Restore focus to the app that was active before recording,
                # then give it a moment to come forward before pasting.
                if self._prev_app:
                    _activate_bundle(self._prev_app)
                    await asyncio.sleep(0.25)
                else:
                    await asyncio.sleep(0.15)
                self.text_ready.emit(text)
            else:
                logger.info("No transcription captured")
        finally:
            # Snapshot the objects and clear self._ immediately so a new
            # recording cycle won't be affected by the background cleanup.
            if self._local_provider is not None:
                self._cleanup_local()
            elif not os.environ.get("STT_FAKE"):
                snap = (self._kit, self._channel, self._session, self._transport)
                self._kit = None
                self._channel = None
                self._session = None
                self._provider = None
                self._transport = None
                asyncio.ensure_future(self._cleanup_snapshot(*snap))

    async def _stop_local_recording(self) -> None:
        """Stop the LocalAudioBackend and wait for final transcriptions."""
        if self._local_backend and self._local_session:
            await self._local_backend.stop_listening(self._local_session)

            if self._batch_mode:
                # Batch mode: flush accumulated audio through offline STT
                try:
                    result = await asyncio.wait_for(
                        self._channel.flush_stt(self._local_session),
                        timeout=30.0,
                    )
                    if result and result.text and result.text.strip():
                        logger.info("Batch STT result: %s", result.text)
                        self._accumulated_text.append(result.text.strip())
                except TimeoutError:
                    logger.warning("Batch STT timed out")
            else:
                # Streaming mode: wait for final transcription from hook
                if self._local_flush_event is not None:
                    self._local_flush_event.clear()
                    try:
                        await asyncio.wait_for(self._local_flush_event.wait(), timeout=3.0)
                    except TimeoutError:
                        logger.info("No final transcription received within timeout")

    def _cleanup_local(self) -> None:
        """Snapshot and clear local STT state, schedule async cleanup."""
        snap = (self._kit, self._channel, self._local_backend, self._local_session)
        self._kit = None
        self._channel = None
        self._local_provider = None
        self._local_backend = None
        self._local_session = None
        self._local_flush_event = None
        self._batch_mode = False
        if any(snap):
            asyncio.ensure_future(self._cleanup_local_snapshot(*snap))

    async def _cleanup_local_snapshot(
        self, kit: Any, channel: Any, backend: Any, session: Any
    ) -> None:
        """Clean up local STT objects without touching self._."""
        try:
            if channel and session:
                try:
                    channel.unbind_session(session)
                except Exception:
                    pass
            if backend and session:
                try:
                    await backend.disconnect(session)
                except Exception:
                    pass
            if kit:
                try:
                    await kit.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("Error during local STT cleanup")

    async def _commit_and_wait(self) -> None:
        """Send input_audio_buffer.commit and wait for the transcription."""
        if self._provider is None or self._session is None:
            return

        self._transcription_event = asyncio.Event()
        # If we already have text from earlier VAD cycles, pre-set the event
        # so we don't block unnecessarily.
        if self._accumulated_text:
            self._transcription_event.set()

        try:
            await self._provider.send_event(self._session, {"type": "input_audio_buffer.commit"})
            logger.info("Sent input_audio_buffer.commit, waiting for transcription...")
        except Exception:
            logger.exception("Error sending audio buffer commit")
            self._transcription_event = None
            return

        try:
            await asyncio.wait_for(self._transcription_event.wait(), timeout=5.0)
            logger.info("Transcription ready")
        except TimeoutError:
            logger.warning("Timed out waiting for transcription after commit")
        finally:
            self._transcription_event = None

    async def _cleanup_snapshot(
        self,
        kit: Any,
        channel: Any,
        session: Any,
        transport: Any,
    ) -> None:
        """Clean up a previous session's objects without touching self._."""
        try:
            if channel and session:
                try:
                    await channel.end_session(session)
                except Exception:
                    pass
            if kit:
                try:
                    await kit.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("Error during STT cleanup")

    async def _cleanup(self) -> None:
        """Cleanup using self._ — only used on start failure."""
        await self._cleanup_snapshot(
            self._kit,
            self._channel,
            self._session,
            self._transport,
        )
        self._kit = None
        self._channel = None
        self._session = None
        self._provider = None
        self._transport = None

    # -- paste -----------------------------------------------------------------

    def paste_text(self, text: str) -> None:
        """Copy *text* to clipboard and simulate Ctrl+V."""
        try:
            front = _get_frontmost_bundle()
            logger.info("Pasting text to %s: %s", front or "(self)", text[:80])
            _copy_to_clipboard(text)
            if not _simulate_paste():
                msg = (
                    "Accessibility permission required for auto-paste. "
                    "Text copied to clipboard — paste manually with ⌘V.\n"
                    "Grant access in System Settings → Privacy & Security → Accessibility."
                )
                logger.warning(msg)
                self.error_occurred.emit(msg)
                return
            logger.info("Paste succeeded")
        except FileNotFoundError as exc:
            msg = (
                f"Missing helper program: {exc.filename}. "
                "Install xclip+xdotool (X11) or wl-copy+wtype (Wayland)."
            )
            logger.error(msg)
            self.error_occurred.emit(msg)
        except subprocess.SubprocessError as exc:
            msg = f"Paste failed: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
