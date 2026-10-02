"""Saved sessions (1.10): a comparison written to a small file and opened again.

Comparing the same two things every week -- this week's backup against last
week's, the plant's L5K against the office copy -- means setting the same
rules, the same name filter, the same pins each time. A session file keeps
them. Opening one (double-click it, drop it on the window, or "Open session"
on the start page) is the comparison as it was set up, read fresh from disk.

The file is JSON, `.fcsession`, and holds settings, never content: the two
paths, their titles, the rules, the view, the pins, and for a folder compare
its filter and switches. It is meant to be read by a person too, so it is
indented and its keys are words.

Pure: dicts and text in and out. Reading the file is `io/sessionfile.py`,
writing it is `io/save.py`, both in the loader like every other file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from app.core.rules import WHITESPACE, Rules

EXTENSION = ".fcsession"
FORMAT = "File Compare session"
VERSION = 1

#: The rules a session keeps: what a person set, not what the session worked
#: out from the files (the comment markers).
RULE_KEYS = ("whitespace", "case", "blank_lines", "patterns", "comments", "enabled")


@dataclass
class Saved:
    left: str = ""
    right: str = ""
    titles: tuple[str, str] = ("", "")
    readonly: tuple[str, ...] = ()
    #: The view: "auto", "text", "hex", "image" or "table".
    mode: str = "auto"
    rules: Rules = field(default_factory=Rules)
    intraline: str = "char"
    #: Whether the format comparer (L5X, L5K, XML...) is on.
    structure: bool = True
    pins: list[tuple[int, int]] = field(default_factory=list)
    #: Folder compare: the name filter, the show filter and the switches.
    folder_mask: str | None = None
    folder_show: str = ""
    folder_hour: bool | None = None
    folder_by_content: bool | None = None
    folder_archives: bool | None = None


def is_session(path: str) -> bool:
    return path.lower().endswith(EXTENSION)


def dumps(saved: Saved) -> str:
    rules = asdict(saved.rules)
    out = {
        "format": FORMAT,
        "version": VERSION,
        "left": saved.left,
        "right": saved.right,
        "titles": list(saved.titles),
        "readonly": sorted(saved.readonly),
        "view": saved.mode,
        "rules": {key: (list(rules[key]) if key == "patterns" else rules[key])
                  for key in RULE_KEYS},
        "intraline": saved.intraline,
        "structure": saved.structure,
        "pins": [list(pin) for pin in saved.pins],
    }
    folder = {key: value for key, value in (
        ("mask", saved.folder_mask), ("show", saved.folder_show or None),
        ("ignore_hour", saved.folder_hour), ("always_contents", saved.folder_by_content),
        ("inside_zips", saved.folder_archives)) if value is not None}
    if folder:
        out["folder"] = folder
    return json.dumps(out, indent=2) + "\n"


def loads(text: str) -> Saved:
    """A session from the file's text. Raises ValueError, saying what is
    wrong, for anything that is not a session this version can read; a key
    it does not know is ignored, so a newer version's file still opens."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a session file ({exc.msg} at line {exc.lineno})") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a File Compare session file")
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise ValueError("written by a newer File Compare; update this one to open it")
    left, right = _text(data.get("left")), _text(data.get("right"))
    if not left and not right:
        raise ValueError("the session names nothing to compare")
    titles = data.get("titles") or ["", ""]
    rules_in = data.get("rules") or {}
    if not isinstance(rules_in, dict):
        rules_in = {}
    whitespace = rules_in.get("whitespace", "none")
    rules = Rules(
        whitespace=whitespace if whitespace in WHITESPACE else "none",
        case=bool(rules_in.get("case", False)),
        blank_lines=bool(rules_in.get("blank_lines", False)),
        patterns=tuple(str(p) for p in rules_in.get("patterns") or () if str(p)),
        comments=bool(rules_in.get("comments", False)),
        enabled=bool(rules_in.get("enabled", True)),
    )
    pins = []
    for pin in data.get("pins") or ():
        if (isinstance(pin, list) and len(pin) == 2
                and all(isinstance(v, int) and v >= 0 for v in pin)):
            pins.append((pin[0], pin[1]))
    folder = data.get("folder") if isinstance(data.get("folder"), dict) else {}

    def flag(key: str) -> bool | None:
        return bool(folder[key]) if key in folder else None

    intraline = data.get("intraline")
    return Saved(
        left=left, right=right,
        titles=(_text(titles[0]) if len(titles) > 0 else "",
                _text(titles[1]) if len(titles) > 1 else ""),
        readonly=tuple(s for s in data.get("readonly") or () if s in ("left", "right")),
        mode=_text(data.get("view")) or "auto",
        rules=rules,
        intraline=intraline if intraline in ("char", "word") else "char",
        structure=bool(data.get("structure", True)),
        pins=pins,
        folder_mask=_text(folder["mask"]) if "mask" in folder else None,
        folder_show=_text(folder.get("show")),
        folder_hour=flag("ignore_hour"),
        folder_by_content=flag("always_contents"),
        folder_archives=flag("inside_zips"),
    )


def _text(value) -> str:
    return value if isinstance(value, str) else ""

