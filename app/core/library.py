"""The sessions kept on the Home page (1.21), in folders of the user's own.

A session file (`core/savedsession.py`) can live anywhere and is opened from
wherever it is. Home keeps its own copies -- the session's text, under a name
and in a folder ("Backups", "Projects") -- in the settings, so the comparisons
made every week are a double-click away, as Beyond Compare's Home keeps them.
Nothing here touches a file: an entry is a name, a folder and the text a
session file would hold.

Pure: lists of dicts in and out, in the shape the settings store them.
"""

from __future__ import annotations

from app.core import savedsession

#: Where an entry goes when no folder is given.
UNFILED = "Sessions"


def clean(entries) -> list[dict]:
    """The stored list with anything malformed dropped, so a hand-edited or
    older settings file never stops Home from opening."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name, folder, text = (entry.get(key) for key in ("name", "folder", "text"))
        if not isinstance(name, str) or not name.strip() or not isinstance(text, str):
            continue
        try:
            savedsession.loads(text)
        except ValueError:
            continue
        out.append({"name": name.strip(),
                    "folder": folder.strip() if isinstance(folder, str) and folder.strip()
                    else UNFILED,
                    "text": text})
    return out


def folders(entries: list[dict]) -> list[str]:
    """Folder names in the order they first appear."""
    seen: list[str] = []
    for entry in entries:
        if entry["folder"] not in seen:
            seen.append(entry["folder"])
    return seen


def add(entries: list[dict], name: str, folder: str, saved: savedsession.Saved) -> list[dict]:
    """A new entry, replacing one of the same name in the same folder."""
    name = name.strip() or "Session"
    folder = folder.strip() or UNFILED
    kept = [e for e in entries if not (e["name"].lower() == name.lower()
                                       and e["folder"].lower() == folder.lower())]
    return kept + [{"name": name, "folder": folder, "text": savedsession.dumps(saved)}]


def rename(entries: list[dict], index: int, name: str) -> list[dict]:
    out = [dict(e) for e in entries]
    if 0 <= index < len(out) and name.strip():
        out[index]["name"] = name.strip()
    return out


def move(entries: list[dict], index: int, folder: str) -> list[dict]:
    out = [dict(e) for e in entries]
    if 0 <= index < len(out):
        out[index]["folder"] = folder.strip() or UNFILED
    return out


def remove(entries: list[dict], index: int) -> list[dict]:
    return [e for i, e in enumerate(entries) if i != index]


def describe(entry: dict) -> str:
    """The two paths an entry compares, for its tooltip."""
    try:
        saved = savedsession.loads(entry["text"])
    except ValueError:
        return ""
    return f"{saved.left}\n{saved.right}"
