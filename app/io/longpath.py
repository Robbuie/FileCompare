r"""The `\\?\` prefix, where Windows is listening for it.

Ported from File Manager 0.38.0 (`app/io/paths.py`, `extended` and `api`),
the two functions of that module this application needs so far. The rule is
the same and so is the reason it is load-bearing both ways:

  * without the prefix, a file call on a path past 260 characters fails with
    "The system cannot find the path specified", a length disguised as a
    missing file;
  * with it in the wrong place, the shell calls fail or come back empty.

So `api` is applied at file calls -- stat, open, the rename of a save -- and
nowhere else: never on anything the window draws, never on the way to the
shell. It is idempotent.
"""

from __future__ import annotations

import os
import sys

#: Whether the prefix is applied at all. Off Windows it would be a path that
#: does not exist; the tests switch it on to check the arithmetic.
EXTENDED_PATHS = sys.platform == "win32"


def extended(path: str) -> str:
    r"""`C:\x` -> `\\?\C:\x`, `\\server\share\x` -> `\\?\UNC\server\share\x`."""
    if not path or path.startswith("\\\\?\\"):
        return path
    path = os.path.abspath(path) if sys.platform == "win32" else path
    path = path.replace("/", "\\")
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    if len(path) >= 2 and path[1] == ":":
        return "\\\\?\\" + path
    return path


def api(path: str) -> str:
    """What to hand a Win32 file call."""
    return extended(path) if EXTENDED_PATHS else path


def display(path: str) -> str:
    r"""The form a person reads: the prefix taken back off."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path
