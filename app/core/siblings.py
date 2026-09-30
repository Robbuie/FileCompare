"""The family's other applications, for the pairs they compare better.

A PDF revision compared as text is the text layer of two drawings, which says
almost nothing about what moved on the sheet; Redline PDF's compare aligns the
pages and overlays them, which is the answer. A DWG compared as bytes says
only "different". So a pair of those opens a tab that says which sibling does
it properly and offers to start it on the two files, with the plain compare
one click away for when the bytes really are the question.

Where each one installs is its installer's business, recorded here from their
own packaging: Redline PDF's electron-builder NSIS per-user install, and DWG
Viewer's Inno Setup `{autopf}\\DWG Viewer`. Neither is on PATH. Neither takes
two files for a compare on its command line, so each file is passed in its own
launch -- Redline PDF opens the second as another tab of the same window, DWG
Viewer opens a window each.
"""

from __future__ import annotations

import ntpath
import posixpath
from dataclasses import dataclass


@dataclass(frozen=True)
class Sibling:
    name: str
    programs: tuple[str, ...]
    #: What the handoff page says the sibling does with the pair.
    does: str


REDLINE = Sibling(
    name="Redline PDF",
    programs=(
        r"%LOCALAPPDATA%\Programs\redline-pdf\Redline PDF.exe",
        r"%ProgramFiles%\Redline PDF\Redline PDF.exe",
        "Redline PDF.exe",
    ),
    does=("Redline PDF compares revisions of a drawing sheet by sheet: pages "
          "aligned, scale and scanner noise allowed for, changes clouded. "
          "Both files open there as tabs; its Compare panel does the rest."),
)

DWG_VIEWER = Sibling(
    name="DWG Viewer",
    programs=(
        r"%LOCALAPPDATA%\Programs\DWG Viewer\DWG Viewer.exe",
        r"%ProgramFiles%\DWG Viewer\DWG Viewer.exe",
        "DWG Viewer.exe",
    ),
    does=("DWG Viewer draws both drawings, each in its own window, "
          "so they can be put side by side."),
)

BY_EXTENSION = {
    "pdf": REDLINE,
    "dwg": DWG_VIEWER,
    "dxf": DWG_VIEWER,
    "dwf": DWG_VIEWER,
    "dwfx": DWG_VIEWER,
}


def for_pair(left: str, right: str) -> Sibling | None:
    """The sibling both files belong to, or None."""
    found = {BY_EXTENSION.get(_ext(p)) for p in (left, right) if p}
    if len(found) == 1:
        return found.pop()
    return None


def _ext(path: str) -> str:
    base = ntpath.basename(path) if "\\" in path else posixpath.basename(path)
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""
