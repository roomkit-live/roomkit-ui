"""The three PyInstaller invocations must bundle the same modules and binaries.

``scripts/build_app.sh`` (local builds) and the Unix and Windows steps of
``.github/workflows/build.yml`` (released builds) each list their own flags.
They drifted once: the releases lost ``--collect-binaries=aec_audio_processing``
and shipped a Linux bundle without the WebRTC AEC library, which the package
loads by path through ctypes, out of PyInstaller's sight.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_KINDS = "hidden-import|collect-submodules|collect-binaries|collect-data|collect-all|copy-metadata"
_FLAGS = rf"--(?:{_KINDS})=[\w.\-]+"
# One flag per line ending in a backslash: build_app.sh and the Unix step.
_SHELL_FLAG = re.compile(rf"^\s*({_FLAGS})\s*\\$", re.MULTILINE)
# One quoted flag per array item: the Windows (PowerShell) step.
_PWSH_FLAG = re.compile(rf'^\s*"({_FLAGS})",?$', re.MULTILINE)


def _flags(pattern: re.Pattern[str], path: Path) -> set[str]:
    found = pattern.findall(path.read_text())
    assert found, f"no PyInstaller flags found in {path.name} — did its layout change?"
    assert len(found) == len(set(found)), f"duplicate flags in {path.name}"
    return set(found)


def test_release_builds_bundle_what_the_local_build_bundles():
    local = _flags(_SHELL_FLAG, ROOT / "scripts" / "build_app.sh")
    workflow = ROOT / ".github" / "workflows" / "build.yml"
    assert _flags(_SHELL_FLAG, workflow) == local, "build.yml Unix step drifted"
    assert _flags(_PWSH_FLAG, workflow) == local, "build.yml Windows step drifted"
