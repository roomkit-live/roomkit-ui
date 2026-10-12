"""Give the isolated camera process a macOS bundle.

Qt refuses a first camera permission request if the main executable's bundle has
no usage description. A private copy of the interpreter supplies that identity;
CPython's launcher variable keeps the original venv, executable and dependencies.
The main app keeps its original executable and Keychain identity. Only the camera
process uses this bundle, and it never reads application secrets.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from roomkit_ui.paths import data_dir

logger = logging.getLogger(__name__)
_RELAUNCH = "_ROOMKIT_MACOS_CAMERA_RELAUNCH"


def camera_usage_declared() -> bool:
    """Read the running process's declaration; never request permission here."""
    if sys.platform != "darwin":
        return True
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFBundleGetMainBundle.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32)
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFBundleGetValueForInfoDictionaryKey.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    cf.CFBundleGetValueForInfoDictionaryKey.restype = ctypes.c_void_p
    cf.CFRelease.argtypes = (ctypes.c_void_p,)
    key = cf.CFStringCreateWithCString(None, b"NSCameraUsageDescription", 0x08000100)
    try:
        return bool(cf.CFBundleGetValueForInfoDictionaryKey(cf.CFBundleGetMainBundle(), key))
    finally:
        cf.CFRelease(key)


def prepare_app(python: Path, bundle: Path) -> Path:
    """Cache a signed interpreter copy, refreshing it only when Python changes."""
    source = python.resolve()
    stat = source.stat()
    contents = bundle / "Contents"
    executable = contents / "MacOS" / "RoomKit UI"
    info_path = contents / "Info.plist"
    info = {
        "CFBundleExecutable": executable.name,
        "CFBundleName": "RoomKit UI",
        "CFBundleDisplayName": "RoomKit UI",
        "CFBundleIdentifier": "com.roomkit.ui.development",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        "NSCameraUsageDescription": (
            "RoomKit UI uses your camera to take a photo you can attach to a message."
        ),
        "NSMicrophoneUsageDescription": (
            "RoomKit UI needs microphone access for voice conversations."
        ),
        "RoomKitPythonPath": str(source),
        "RoomKitPythonMtime": stat.st_mtime_ns,
        "RoomKitPythonSize": stat.st_size,
    }
    manifest = plistlib.dumps(info)
    if executable.is_file() and info_path.is_file() and info_path.read_bytes() == manifest:
        return executable
    executable.parent.mkdir(parents=True, exist_ok=True)
    # A copy, never a hard link: signing must not modify the user's Python.
    temporary = executable.with_name(f".python-{os.getpid()}")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(executable)
    finally:
        temporary.unlink(missing_ok=True)
    info_path.write_bytes(manifest)
    try:
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        # Do not treat an incomplete build as a valid cache on the next start.
        info_path.unlink(missing_ok=True)
        raise
    return executable


def relaunch_camera_if_needed() -> None:
    """Used only by camera_capture, before its QApplication exists."""
    relaunched = os.environ.pop(_RELAUNCH, None)
    if sys.platform != "darwin" or getattr(sys, "frozen", False) or camera_usage_declared():
        return
    if relaunched:
        raise RuntimeError("The camera launcher is missing its macOS usage description.")
    python = Path(sys.executable).absolute()
    key = hashlib.sha256(os.fsencode(python)).hexdigest()[:12]
    bundle = data_dir() / "cache" / "macos-app" / key / "RoomKit UI.app"
    try:
        executable = prepare_app(python, bundle)
        env = dict(os.environ, __PYVENV_LAUNCHER__=str(python))
        # Validate relocation before replacing the running process (some Python
        # distributions use library paths relative to their original binary).
        subprocess.run(
            [
                str(executable),
                "-c",
                "import sys; assert sys.prefix == sys.argv[1]; "
                "assert sys.executable == sys.argv[2]",
                sys.prefix,
                str(python),
            ],
            env=env,
            check=True,
            capture_output=True,
            timeout=15,
        )
        env[_RELAUNCH] = "1"
        logger.info("Starting the isolated camera window with its macOS usage description")
        # Only our validated interpreter copy; argv is never interpreted by a shell.
        os.execve(  # nosec B606
            executable, [str(executable), "-m", "roomkit_ui.camera_capture", *sys.argv[1:]], env
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError(
            "Could not start the camera. Try again or use the packaged RoomKit UI app."
        ) from None
