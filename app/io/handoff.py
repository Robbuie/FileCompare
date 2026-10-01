"""Handing a folder sync to File Manager's queue (1.0).

The request is a small JSON file (`core/syncplan.request` makes it) under
`%LOCALAPPDATA%\\FileCompare\\handoff`, and File Manager is started with
`--queue <file>`. A running File Manager gets the path over its
single-instance pipe; none running, one starts and takes it. When every job
has ended File Manager writes `<name>.result.json` beside the request, and
`result` here is what the folder view polls to know when to walk again.

Every function here touches the disk or starts a process, so all of them run
in the loader, never on the UI thread.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
import uuid

from app.io import launch

#: Where File Manager's installer puts it (Inno Setup, per user, `{autopf}`),
#: then a machine-wide install, then PATH.
FILE_MANAGER = (
    r"%LOCALAPPDATA%\Programs\FileManager\FileManager.exe",
    r"%ProgramFiles%\FileManager\FileManager.exe",
    "FileManager.exe",
)

#: Requests and results older than this are removed when the next is written.
KEEP_SECONDS = 7 * 24 * 3600


def folder() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"),
                                                          ".local", "share")
    return os.path.join(base, "FileCompare", "handoff")


def _tidy(where: str) -> None:
    now = time.time()
    try:
        names = os.listdir(where)
    except OSError:
        return
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(where, name)
        try:
            if now - os.path.getmtime(path) > KEEP_SECONDS:
                os.remove(path)
        except OSError:
            pass


def send(request: dict, *, program: str = "", where: str = "") -> tuple[str, str]:
    """Write the request and start File Manager on it.

    Returns `(request path, program started)`. Raises `FileNotFoundError`
    when File Manager is not installed, having written nothing.
    """
    found = program or launch.locate(FILE_MANAGER)
    if not found:
        raise FileNotFoundError("File Manager is not installed here; looked for "
                                + ", ".join(os.path.expandvars(c) for c in FILE_MANAGER))
    where = where or folder()
    os.makedirs(where, exist_ok=True)
    _tidy(where)
    name = f"sync-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(where, name)
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as handle:
        json.dump(request, handle)
    os.replace(partial, path)
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([found, "--queue", path], creationflags=flags,  # noqa: S603
                     close_fds=True)
    return path, found


WAITING = "waiting"      # nothing from File Manager yet
TAKEN = "taken"          # File Manager queued it (`<name>.taken.json`)
DONE = "done"            # the result is in


def result_path(request_path: str) -> str:
    root, _ext = os.path.splitext(request_path)
    return root + ".result.json"


def taken_path(request_path: str) -> str:
    root, _ext = os.path.splitext(request_path)
    return root + ".taken.json"


def result(request_path: str) -> tuple[str, dict | None]:
    """`(state, outcome)`: what File Manager has said about a request. The
    outcome is what it wrote when the jobs ended -- or when it refused the
    request -- and once it has been read the request's files are removed."""
    path = result_path(request_path)
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
    except FileNotFoundError:
        return (TAKEN if os.path.exists(taken_path(request_path)) else WAITING), None
    except (OSError, ValueError):
        return WAITING, None
    for leftover in (path, taken_path(request_path), request_path):
        try:
            os.remove(leftover)
        except OSError:
            pass
    return DONE, (found if isinstance(found, dict) else {})


def drive_is_remote(path: str) -> bool:
    """Whether removing from here skips the Recycle Bin, as Windows does on a
    network folder: a UNC path, or a letter mapped to a share. `GetDriveType`
    reads the session's own table and does not go near the server."""
    if path.startswith("\\\\"):
        return True
    if os.name != "nt" or len(path) < 2 or path[1] != ":":
        return False
    try:
        kind = ctypes.windll.kernel32.GetDriveTypeW(path[:2] + "\\")
    except Exception:  # noqa: BLE001 - unknown is not remote
        return False
    return kind == 4          # DRIVE_REMOTE


def remote_sides(left: str, right: str) -> tuple[bool, bool]:
    return drive_is_remote(left), drive_is_remote(right)
