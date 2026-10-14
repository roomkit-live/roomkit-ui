"""A provider chosen before its key was entered — leaf."""

from __future__ import annotations


class MissingKeyError(ValueError):
    """The selected provider has no key (or no endpoint/region beside it) in Settings.

    The message is written for the user and says where to enter it.  Like a
    backend not installed, it is a state of the settings, not a fault: a
    session start that meets one says so in the chat and logs one line,
    without a traceback.  A ValueError still, for callers that catch one.
    """
