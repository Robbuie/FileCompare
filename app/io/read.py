"""Opening one side of a comparison: what the path is, and its text if it is
a file. A job for the loader, and on a network volume for the worker pool
(`io/pool.py`) -- which is why it lives here and not beside the session: a
worker process imports the module a job comes from, and the session's module
would bring Qt into every worker with it.
"""

from __future__ import annotations

from app.io import kind as io_kind
from app.io import load as io_load


def open_side(path: str, max_bytes: int, encoding: str = "") -> tuple[str, io_load.Loaded | None]:
    """What the path is, and its text if it is a file."""
    what = io_kind.kind(path)
    if what != io_kind.FILE:
        return what, None
    return what, io_load.load(path, max_bytes=max_bytes, encoding=encoding)
