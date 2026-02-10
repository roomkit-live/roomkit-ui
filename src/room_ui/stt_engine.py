"""STT engine — records speech via a roomkit STT room and pastes transcribed text."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from typing import Any

from PySide6.QtCore import QObject, Signal

from room_ui.settings import load_settings

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
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowclassname"],
            capture_output=True, text=True, timeout=3,
        )
        wm_class = result.stdout.strip().lower()
        terminal_classes = (
            "terminal", "konsole", "alacritty", "kitty", "xterm",
            "urxvt", "tilix", "terminator", "gnome-terminal",
            "xfce4-terminal", "mate-terminal", "sakura", "st",
            "wezterm", "foot", "claude",
        )
        return any(t in wm_class for t in terminal_classes)
    except Exception:
        return False


def _simulate_paste() -> None:
    """Simulate paste keystroke into the focused window.

    Terminals typically use Ctrl+Shift+V, while other apps use Ctrl+V.
    """
    if sys.platform == "darwin":
        import Quartz

        # Cmd+V via CGEvent — works when Accessibility permission is granted
        # (same permission the CGEventTap hotkey listener already requires).
        v_keycode = 0x09  # macOS virtual keycode for 'v'
        cmd_flag = Quartz.kCGEventFlagMaskCommand

        down = Quartz.CGEventCreateKeyboardEvent(None, v_keycode, True)
        Quartz.CGEventSetFlags(down, cmd_flag)
        Quartz.CGEventPost(Quartz.kCGAnnotatedSessionEventTap, down)

        up = Quartz.CGEventCreateKeyboardEvent(None, v_keycode, False)
        Quartz.CGEventSetFlags(up, cmd_flag)
        Quartz.CGEventPost(Quartz.kCGAnnotatedSessionEventTap, up)
    elif _is_wayland():
        subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], check=True, timeout=5)
    elif _is_terminal_focused():
        subprocess.run(["xdotool", "key", "ctrl+shift+v"], check=True, timeout=5)
    else:
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True, timeout=5)


def _get_frontmost_bundle() -> str | None:
    """Return the bundle ID of the frontmost app (macOS only)."""
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        return front.bundleIdentifier() if front else None
    except Exception:
        return None


def _activate_bundle(bundle_id: str) -> None:
    """Bring an app to the front by bundle ID (macOS only)."""
    if sys.platform != "darwin" or not bundle_id:
        return
    try:
        from AppKit import NSRunningApplication, NSWorkspace
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps:
            apps[0].activateWithOptions_(0)
    except Exception:
        pass


class STTEngine(QObject):
    """Records speech via an OpenAI Realtime STT room and pastes the result.

    Uses a dedicated roomkit room (``stt-room``) with
    ``create_response=False`` so the provider only transcribes — no AI
    response is generated.
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

    def _on_transcription(
        self, _session: Any, text: str, role: str, is_final: bool
    ) -> None:
        if role == "user" and is_final and text.strip():
            logger.info("STT transcription (final): %s", text)
            self._accumulated_text.append(text.strip())
            if self._transcription_event is not None:
                self._transcription_event.set()

    # -- lifecycle -------------------------------------------------------------

    async def _start_recording(self) -> None:
        if self._recording or self._busy:
            logger.warning("_start_recording skipped: recording=%s busy=%s", self._recording, self._busy)
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
                import json
                ws = self._provider._connections.get(self._session.id)
                if ws:
                    await ws.send(json.dumps({
                        "type": "session.update",
                        "session": {
                            "input_audio_transcription": {
                                "model": "gpt-4o-transcribe",
                                "language": stt_language,
                            },
                        },
                    }))
                    logger.info("Set STT language: %s", stt_language)

            logger.info("STT session started")

        except Exception as exc:
            logger.exception("Failed to start STT session")
            self._recording = False
            self.recording_changed.emit(False)
            self.error_occurred.emit(str(exc))
            await self._cleanup()
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
            if not os.environ.get("STT_FAKE"):
                snap = (self._kit, self._channel, self._session, self._transport)
                self._kit = None
                self._channel = None
                self._session = None
                self._provider = None
                self._transport = None
                asyncio.ensure_future(self._cleanup_snapshot(*snap))

    async def _commit_and_wait(self) -> None:
        """Send input_audio_buffer.commit and wait for the transcription."""
        import json

        if self._provider is None or self._session is None:
            return

        ws = self._provider._connections.get(self._session.id)
        if ws is None:
            return

        self._transcription_event = asyncio.Event()
        # If we already have text from earlier VAD cycles, pre-set the event
        # so we don't block unnecessarily.
        if self._accumulated_text:
            self._transcription_event.set()

        try:
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            logger.info("Sent input_audio_buffer.commit, waiting for transcription...")
        except Exception:
            logger.exception("Error sending audio buffer commit")
            self._transcription_event = None
            return

        try:
            await asyncio.wait_for(self._transcription_event.wait(), timeout=5.0)
            logger.info("Transcription ready")
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for transcription after commit")
        finally:
            self._transcription_event = None

    async def _cleanup_snapshot(
        self, kit: Any, channel: Any, session: Any, transport: Any,
    ) -> None:
        """Clean up a previous session's objects without touching self._."""
        try:
            if channel and session:
                try:
                    await channel.end_session(session)
                except Exception:
                    pass
            if transport is not None:
                try:
                    for stream in transport._input_streams.values():
                        if stream.active:
                            stream.stop()
                except Exception:
                    pass
                try:
                    for stream in transport._output_streams.values():
                        if stream.active:
                            stream.stop()
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
            self._kit, self._channel, self._session, self._transport,
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
            logger.info("Pasting text: %s", text[:80])
            _copy_to_clipboard(text)
            _simulate_paste()
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
