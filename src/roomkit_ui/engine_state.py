"""Engine session-state enum.

Lives in its own leaf module (not engine.py) so the engine mixins and
widgets can import it without creating a circular import with Engine.
StrEnum members compare and hash equal to their string values, so Qt
signals carrying ``str`` payloads interoperate transparently.
"""

from __future__ import annotations

from enum import StrEnum


class EngineState(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    ACTIVE = "active"
    STOPPING = "stopping"
    ERROR = "error"
