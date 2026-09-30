"""Which theme, accent and density to use -- ours, or File Manager's.

This application is opened from File Manager more often than on its own, and
a compare window in a different theme from the window that opened it reads as
a different program. So by default the look is taken from File Manager's
settings file, read-only, once at startup.

Only the three named axes are taken. File Manager can also take its accent
from Windows or from the wallpaper (`accent.source`); when it does, its named
`accent` is still in the file as the fallback, and that is what is used here.
Following the Windows accent too is a later decision, not an accident of this
one.

Never written. If the file is missing, unreadable or from a version with names
this one does not know, our own settings apply -- `qss.build` falls back on an
unknown name anyway.
"""

from __future__ import annotations

import json
import os

from app.core.config import Config

FILE_MANAGER_FOLDER = "FileManager"
KEYS = ("theme", "accent", "density")


def file_manager_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(
        os.environ.get("USERPROFILE") or os.path.expanduser("~"), ".config")
    return os.path.join(base, FILE_MANAGER_FOLDER, "config.json")


def file_manager_look(path: str | None = None) -> dict[str, str] | None:
    """File Manager's theme, accent and density, or None if unavailable."""
    try:
        with open(path or file_manager_path(), "r", encoding="utf-8") as handle:
            values = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(values, dict):
        return None
    found = {key: values[key] for key in KEYS if isinstance(values.get(key), str)}
    return found or None


def resolve(config: Config, *, file_manager: dict[str, str] | None = None,
            probe: bool = True) -> tuple[dict[str, str], str]:
    """The look to apply, and where it came from, for the status line.

    File Manager only writes keys somebody changed, so a key missing from its
    file means its default -- which is the family default, the same as ours.
    """
    own = {key: config.get(key) for key in KEYS}
    if not config.get("look.follow_file_manager"):
        return own, "own"
    theirs = file_manager if file_manager is not None else (
        file_manager_look() if probe else None)
    if theirs is None:
        return own, "own"
    from app.theme.tokens import DEFAULTS

    return {key: theirs.get(key, DEFAULTS[key]) for key in KEYS}, "file manager"
