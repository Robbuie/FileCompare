"""Typing straight into a side (1.23): where the caret is, and what a key does.

Until 1.23 a side was changed through the line editor -- F2 opens a box over
the selected lines -- or by copying across. Beyond Compare lets you click into
either side and type, and so does this now, when Edit > Type in the panes is
on. The panes are still painted (CLAUDE.md, "The row model"), so there is no
text widget to hold a caret; this module is the caret.

A caret is a line of one side and a column in that line's own characters,
before tabs are expanded. The line is the side's line number, not a row:
rows move every time the diff runs again, and the diff runs again after every
key. On a filler row -- where the other side has lines and this one has none --
the caret is `fresh`: it sits *before* line `line`, on a line that does not
exist yet, and the first character typed makes it.

Every key here is turned into one splice -- lines `start:end` become some
other lines -- which is what `Document.replace` takes, plus where the caret
goes after it. Keys that only move the caret return no splice. Nothing here
knows about Qt, files or the view; the tests drive it alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

TAB = 4


@dataclass(frozen=True)
class Caret:
    side: int
    line: int
    col: int = 0
    #: Before line `line`, on a line not made yet (a filler row was clicked).
    fresh: bool = False


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    lines: tuple[str, ...]
    caret: Caret
    #: Typing that may be folded into the undo step before it: the same line,
    #: one character after another. "" starts a step of its own.
    group: str = ""


def clamp(caret: Caret, lines: Sequence[str]) -> Caret:
    """The caret moved back inside the text, after the text changed under it."""
    count = len(lines)
    if caret.fresh:
        return Caret(caret.side, max(0, min(caret.line, count)), 0, True)
    if not count:
        return Caret(caret.side, 0, 0, True)
    line = max(0, min(caret.line, count - 1))
    return Caret(caret.side, line, max(0, min(caret.col, len(lines[line]))))


def display_col(text: str, col: int) -> int:
    """The screen column of character `col`, tabs expanded as the panes do."""
    return len(text[:col].expandtabs(TAB))


def char_col(text: str, column: int) -> int:
    """The character nearest screen column `column`: the inverse of
    `display_col`, rounding a click inside a tab to its nearer edge."""
    if column <= 0:
        return 0
    at = 0
    for index, ch in enumerate(text):
        width = TAB - at % TAB if ch == "\t" else 1
        if column < at + width:
            return index + (1 if column - at > width / 2 else 0)
        at += width
    return len(text)


def _group(caret: Caret) -> str:
    return f"{caret.side}:{caret.line}"


def insert(lines: Sequence[str], caret: Caret, text: str) -> Edit | None:
    """Characters typed or pasted at the caret. A newline in `text` splits
    the line there, as typing it would."""
    if not text:
        return None
    caret = clamp(caret, lines)
    pieces = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if caret.fresh:
        before, after, start, end = "", "", caret.line, caret.line
    else:
        current = lines[caret.line]
        before, after = current[:caret.col], current[caret.col:]
        start, end = caret.line, caret.line + 1
    if len(pieces) == 1:
        new = (before + pieces[0] + after,)
        moved = Caret(caret.side, start, len(before) + len(pieces[0]))
        group = "" if caret.fresh else _group(moved)
        return Edit(start, end, new, moved, group)
    new = (before + pieces[0],) + tuple(pieces[1:-1]) + (pieces[-1] + after,)
    moved = Caret(caret.side, start + len(new) - 1, len(pieces[-1]))
    return Edit(start, end, new, moved)


def newline(lines: Sequence[str], caret: Caret, *, indent: bool = True) -> Edit | None:
    """Enter: the line split at the caret. The new line takes the old one's
    leading spaces and tabs, as every code editor does."""
    caret = clamp(caret, lines)
    if caret.fresh:
        return Edit(caret.line, caret.line, ("",), Caret(caret.side, caret.line, 0, True))
    current = lines[caret.line]
    lead = ""
    if indent:
        lead = current[:len(current) - len(current.lstrip(" \t"))][:caret.col]
    before, after = current[:caret.col], current[caret.col:]
    return Edit(caret.line, caret.line + 1, (before, lead + after),
                Caret(caret.side, caret.line + 1, len(lead)))


def backspace(lines: Sequence[str], caret: Caret) -> Edit | Caret | None:
    """The character before the caret; at the start of a line, the line
    break, joining it to the one above. On a fresh caret there is nothing to
    remove: it goes to the end of the line above instead."""
    caret = clamp(caret, lines)
    if caret.fresh:
        if caret.line == 0:
            return None
        above = caret.line - 1
        return Caret(caret.side, above, len(lines[above]))
    current = lines[caret.line]
    if caret.col > 0:
        moved = Caret(caret.side, caret.line, caret.col - 1)
        return Edit(caret.line, caret.line + 1,
                    (current[:caret.col - 1] + current[caret.col:],), moved, _group(moved))
    if caret.line == 0:
        return None
    above = lines[caret.line - 1]
    return Edit(caret.line - 1, caret.line + 1, (above + current,),
                Caret(caret.side, caret.line - 1, len(above)))


def delete(lines: Sequence[str], caret: Caret) -> Edit | None:
    """The character after the caret; at the end of a line, the line break,
    joining the next line onto this one."""
    caret = clamp(caret, lines)
    if caret.fresh:
        return None
    current = lines[caret.line]
    if caret.col < len(current):
        return Edit(caret.line, caret.line + 1,
                    (current[:caret.col] + current[caret.col + 1:],), caret, _group(caret))
    if caret.line + 1 >= len(lines):
        return None
    return Edit(caret.line, caret.line + 2, (current + lines[caret.line + 1],), caret)


def _word_left(text: str, col: int) -> int:
    while col > 0 and not (text[col - 1].isalnum() or text[col - 1] == "_"):
        col -= 1
    while col > 0 and (text[col - 1].isalnum() or text[col - 1] == "_"):
        col -= 1
    return col


def _word_right(text: str, col: int) -> int:
    n = len(text)
    while col < n and (text[col].isalnum() or text[col] == "_"):
        col += 1
    while col < n and not (text[col].isalnum() or text[col] == "_"):
        col += 1
    return col


def move(lines: Sequence[str], caret: Caret, how: str) -> Caret:
    """Left, right, home, end and their word forms, within the side's lines.
    Up and down are rows, which only the view knows; it moves those."""
    caret = clamp(caret, lines)
    if caret.fresh:
        if how in ("right", "end", "word-right") and caret.line < len(lines):
            return Caret(caret.side, caret.line, 0)
        if how in ("left", "word-left") and caret.line > 0:
            return Caret(caret.side, caret.line - 1, len(lines[caret.line - 1]))
        return caret
    text = lines[caret.line]
    col = caret.col
    if how == "left":
        if col > 0:
            return Caret(caret.side, caret.line, col - 1)
        if caret.line > 0:
            return Caret(caret.side, caret.line - 1, len(lines[caret.line - 1]))
        return caret
    if how == "right":
        if col < len(text):
            return Caret(caret.side, caret.line, col + 1)
        if caret.line + 1 < len(lines):
            return Caret(caret.side, caret.line + 1, 0)
        return caret
    if how == "home":
        # First the indentation's end, then the very start, as editors do.
        lead = len(text) - len(text.lstrip(" \t"))
        return Caret(caret.side, caret.line, 0 if col == lead else lead)
    if how == "end":
        return Caret(caret.side, caret.line, len(text))
    if how == "word-left":
        return Caret(caret.side, caret.line, _word_left(text, col))
    if how == "word-right":
        return Caret(caret.side, caret.line, _word_right(text, col))
    return caret
