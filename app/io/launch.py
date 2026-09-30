"""Starting another program, for the handoff to a sibling application.

Off the UI thread like every other filesystem call: finding the program is a
look at the disk, and a candidate on a network drive can take as long to
answer as any other file there. Started detached, so closing this window does
not close what it started.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def locate(candidates: tuple[str, ...] | list[str]) -> str:
    for candidate in candidates:
        expanded = os.path.expandvars(candidate)
        if os.path.isabs(expanded):
            if os.path.isfile(expanded):
                return expanded
            continue
        found = shutil.which(expanded)
        if found:
            return found
    return ""


def start_each(candidates: tuple[str, ...] | list[str], files: list[str]) -> str:
    """Start the first program found once per file. Returns its path; raises
    `FileNotFoundError` naming the places looked in when there is none."""
    program = locate(candidates)
    if not program:
        raise FileNotFoundError("Not installed here; looked for "
                                + ", ".join(os.path.expandvars(c) for c in candidates))
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for path in files:
        if path:
            subprocess.Popen([program, path], creationflags=flags, close_fds=True)  # noqa: S603
    return program
