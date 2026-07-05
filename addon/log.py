"""Lightweight logging that never crashes Anki.

Messages go to stderr (visible when Anki is launched from a terminal) prefixed
so they're easy to spot. We deliberately avoid raising from here.
"""

from __future__ import annotations

import sys

_PREFIX = "[discord-rich-presence]"


def log(message: str) -> None:
    try:
        sys.stderr.write("%s %s\n" % (_PREFIX, message))
        sys.stderr.flush()
    except Exception:
        pass
