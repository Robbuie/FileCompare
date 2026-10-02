"""Reading a saved session file (1.10), in the loader."""

from __future__ import annotations

from app.core.savedsession import Saved, loads
from app.io import longpath

#: A session file is a few hundred bytes. Anything past this is not one.
LIMIT = 1 << 20


def read(path: str) -> Saved:
    with open(longpath.api(path), "r", encoding="utf-8-sig") as handle:
        text = handle.read(LIMIT)
    return loads(text)
