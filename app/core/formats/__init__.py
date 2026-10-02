"""Format-aware comparers: turn a file into text that compares by meaning.

A line diff of some files is noise. A Logix export rewrites its export date
and can reorder its tags on every save; an XML file can have the same
attributes in a different order; a JSON or INI file can have the same keys in
a different order. Each comparer here turns the file's text into a canonical
text -- sorted where order does not matter, stripped of what changes on every
save -- and the ordinary line engine compares that.

Every comparer returns a `Formatted`: the canonical lines, a **crumb** per
line saying where in the file's structure it is ("MainProgram / MainRoutine /
Rung 12"), and a sentence saying what was ignored. The crumb is what lets a
difference be named by program, routine and rung rather than by line number,
and the sentence is the rule from `core/rules.py` again: a comparer never
hides anything without saying so.

A formatted side is read-only. The canonical text is not the file, and saving
it would write something the file never was; the tab's "Plain text" switch is
the way back to editing.

Pure: text in, lines out. Runs in the loader with the diff.
"""

from __future__ import annotations

import ntpath
import posixpath
from dataclasses import dataclass, field

PLAIN = "text"

#: Comparers that start switched on. An L5X or L5K is never read as text on
#: purpose; an XML, JSON or INI file usually is, and is edited, so for those
#: the Structure switch is offered and left off.
DEFAULT_ON = frozenset({"l5x", "l5k"})


@dataclass
class Formatted:
    lines: list[str] = field(default_factory=list)
    crumbs: list[str] = field(default_factory=list)
    #: What the comparer looked past, for the status line.
    ignored: str = ""
    #: Set when the text could not be read as the format; the plain text is
    #: then compared instead, and this says why.
    problem: str = ""


def names() -> dict[str, str]:
    """Format id -> the label the tab's switch shows."""
    return {"l5x": "Logix structure", "l5k": "Logix structure", "xml": "XML structure",
            "json": "JSON structure", "ini": "INI structure"}


def detect(*paths: str) -> str:
    """The comparer both sides agree on by extension, or PLAIN."""
    found = {_by_extension(p) for p in paths if p}
    if len(found) == 1:
        return found.pop() or PLAIN
    return PLAIN


def _by_extension(path: str) -> str:
    base = ntpath.basename(path) if "\\" in path else posixpath.basename(path)
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if ext == "l5x":
        return "l5x"
    if ext == "l5k":
        return "l5k"
    if ext in ("xml", "config", "csproj", "vbproj", "resx", "xaml", "svg", "manifest",
               "props", "targets", "xsd", "wsdl", "plist"):
        return "xml"
    if ext in ("json", "geojson", "jsonc"):
        return "json"
    if ext in ("ini", "cfg", "inf"):
        return "ini"
    return ""


def normalise(kind: str, lines: list[str]) -> Formatted:
    """Canonical lines for one side. Falls back to the lines as they are, with
    a problem noted, when the text is not the format it claims to be."""
    text = "\n".join(lines)
    try:
        if kind == "l5x":
            from app.core.formats import l5x
            return l5x.normalise(text)
        if kind == "l5k":
            from app.core.formats import l5k
            return l5k.normalise(text)
        if kind == "xml":
            from app.core.formats import xmlfmt
            return xmlfmt.normalise(text)
        if kind == "json":
            from app.core.formats import jsonfmt
            return jsonfmt.normalise(text)
        if kind == "ini":
            from app.core.formats import inifmt
            return inifmt.normalise(lines)
    except Exception as exc:  # noqa: BLE001 - a bad file is compared as text
        return Formatted(list(lines), [""] * len(lines),
                         problem=f"Not read as {names().get(kind, kind)}: {exc}")
    return Formatted(list(lines), [""] * len(lines))
