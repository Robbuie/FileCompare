"""Settings, with a default for every key and no raw key reads anywhere.

The same shape as File Manager's `core/config.py`, and the same deliberate
exception to the rule about the UI thread: `%APPDATA%` is local by definition,
the read happens once before the window exists and the write on close.
Nothing here is ever given a path somebody typed.

`get` raises on an unknown key rather than returning None: a typo that reads
as "off" is found months later by somebody wondering why a preference never
applied.
"""

from __future__ import annotations

import json
import os
from typing import Any

APP_FOLDER = "FileCompare"
FILE_NAME = "config.json"


def _home() -> str:
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "accent": "blue",
    "density": "normal",
    # Take theme, accent and density from File Manager's settings, so the
    # two change together. Read once at startup, never written.
    "look.follow_file_manager": True,

    "window.width": 1400,
    "window.height": 860,
    "window.maximized": False,

    # What counts as a difference (`core/rules.py`). These are the defaults a
    # new tab starts with; a tab's own toggles do not change them.
    "compare.whitespace": "none",
    "compare.case": False,
    "compare.blank_lines": False,
    "compare.comments": False,
    "compare.patterns": [],
    # "char" or "word": the granularity of the marks inside a changed line.
    "compare.intraline": "char",
    # 1.1: colour text by its language, found from the file's name.
    "view.syntax": True,

    # Seconds a side may take to load before it is shown as not answering.
    # Generous, because a large file on a slow share is not a dead one.
    "load.timeout": 20.0,
    # Megabytes past which a file is not read as text.
    "load.max_mb": 512,

    # Look for a new version once, a few seconds after the window opens.
    # The only network call the application makes (CLAUDE.md, Scope).
    "updates.check_on_launch": True,
    # A version the user said "skip" to; not offered again until a newer one.
    "updates.skip_version": "",

    # Explorer's "Select left side": the path waiting for "Compare to left side".
    "explorer.left": "",

    # Folder compare's names to include and leave out (`core/folders.Mask`).
    "folders.mask": "-.git;-__pycache__;-Thumbs.db;-desktop.ini",

    # 1.8: same-size files exactly an hour apart are a clock change, not an
    # edit; and whether every same-size pair is read after each walk.
    "folders.ignore_hour": True,
    "folders.by_content": False,
    # 1.9: list the files inside each .zip in folder compare.
    "folders.archives": True,
    # 1.15: the show filter a folder compare opens with, whether it opens
    # with the differing folders expanded (otherwise collapsed), and the
    # folders the path boxes have shown lately, newest first.
    "folders.show": "different",
    "folders.open_expanded": False,
    "folders.history": [],

    # Keep `name.ext.orig` beside a file the first time it is saved.
    "save.backup": False,

    # Pairs compared lately, newest first, as [left, right].
    "recent": [],

    # The last folder each side of the start page browsed from.
    "start.left_folder": "",
    "start.right_folder": "",
}


class Config:
    """A flat dotted-key store over `DEFAULTS`."""

    def __init__(self, values: dict[str, Any] | None = None, path: str | None = None):
        self._values = dict(values or {})
        self._path = path or self.default_path()

    @property
    def path(self) -> str:
        return self._path

    @staticmethod
    def default_path() -> str:
        base = os.environ.get("APPDATA") or os.path.join(_home(), ".config")
        return os.path.join(base, APP_FOLDER, FILE_NAME)

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        """Read the settings file, falling back to defaults on any problem.
        A corrupt settings file must not stop the application starting."""
        target = path or cls.default_path()
        try:
            with open(target, "r", encoding="utf-8") as handle:
                values = json.load(handle)
            if not isinstance(values, dict):
                values = {}
        except (OSError, ValueError):
            values = {}
        return cls({k: v for k, v in values.items() if k in DEFAULTS}, target)

    def get(self, key: str) -> Any:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting {key!r}; add it to config.DEFAULTS")
        return self._values.get(key, DEFAULTS[key])

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting {key!r}; add it to config.DEFAULTS")
        self._values[key] = value

    def save(self) -> bool:
        """Write the settings out. False rather than raising: failing to save
        a preference is not worth an error dialog on the way out."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2, sort_keys=True)
            return True
        except OSError:
            return False
