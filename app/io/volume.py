"""Which volume a path is on, for the worker pool (1.4).

`local` for a local disk, which stays on the loader's threads; otherwise a key
per server, so two shares on one server -- which hang together -- share one
worker, and a hung server takes only its own worker with it.

A UNC path is keyed by its server. A drive letter is asked about once,
through `GetDriveType`, which reads this session's own table of drives and
does not go near the server; a mapped letter is keyed by the letter (two
letters mapped to one server get two workers, which costs a process and
nothing else). Off Windows everything is local, unless the tests say
otherwise.
"""

from __future__ import annotations

import os

LOCAL = "local"
DRIVE_REMOTE = 4

_letters: dict[str, bool] = {}

#: The tests set this to send every path through the pool.
FORCE_REMOTE = False


def _remote_letter(letter: str) -> bool:
    letter = letter.upper()
    known = _letters.get(letter)
    if known is not None:
        return known
    remote = False
    if os.name == "nt":
        try:
            import ctypes

            remote = ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") == DRIVE_REMOTE
        except Exception:  # noqa: BLE001 - unknown is local
            remote = False
    _letters[letter] = remote
    return remote


def key(path: str) -> str:
    if not path:
        return LOCAL
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    if path.startswith("\\\\"):
        server = path[2:].split("\\", 1)[0].lower()
        return f"\\\\{server}" if server else LOCAL
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        if _remote_letter(path[0]):
            return f"{path[0].upper()}:"
        return "test" if FORCE_REMOTE else LOCAL
    return "test" if FORCE_REMOTE else LOCAL
