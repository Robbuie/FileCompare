"""Is a path a file, a folder, or not there: decided off the UI thread.

The command line hands over two paths and says nothing about what they are,
and neither does File Manager's `%C` -- asking is a filesystem call, and the
window is not allowed to make one. So the question comes here, runs in the
loader's thread with the same deadline as a read, and the answer picks the
kind of comparison.
"""

from __future__ import annotations

import os

from app.io import longpath

FILE = "file"
FOLDER = "folder"
MISSING = "missing"


def kind(path: str) -> str:
    target = longpath.api(path)
    try:
        if os.path.isdir(target):
            return FOLDER
        if os.path.exists(target):
            return FILE
    except OSError:
        pass
    return MISSING
