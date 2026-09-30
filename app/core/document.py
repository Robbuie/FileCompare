"""One side's text as it is being edited: lines, their endings, undo and redo.

The reader (`io/load.py`) returns what was on disk; this is what the side
holds from then on. Every change is one **splice** -- lines `start:end`
replaced by some other lines -- because every edit the compare view offers is
one: copying a block across, editing a run of lines in place, deleting them.
An undo entry is the splice and what it replaced, so undo is the same splice
backwards and costs the size of the edit rather than a copy of the file.

**Endings travel with their lines.** A line keeps the ending it was read with;
a line that arrives from anywhere else -- the other side, the block editor --
gets this file's own ending, so copying one CRLF line into an LF file does not
make the file mixed. The last line keeps "no ending" if the file had none,
which is the difference between a save that changes one line and a save that
also appends a newline nobody asked for.

Pure Python. No Qt, no files: the tests prove it alone.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

#: Undo steps kept per side. Each costs only the lines it touched.
UNDO_LIMIT = 500

ENDINGS = {"CRLF": "\r\n", "LF": "\n", "CR": "\r"}


@dataclass
class Splice:
    start: int
    old_lines: list[str]
    old_endings: list[str]
    new_lines: list[str]
    new_endings: list[str]


@dataclass
class Document:
    lines: list[str] = field(default_factory=list)
    endings: list[str] = field(default_factory=list)
    #: The ending new lines get: the file's own, or its most common one when it
    #: is mixed, or CRLF for a file that had none (it is Windows).
    newline: str = "\r\n"
    _undo: list[Splice] = field(default_factory=list)
    _redo: list[Splice] = field(default_factory=list)
    #: Where in the undo history the file on disk is. Dirty means "not here".
    _saved_at: int = 0
    #: Bumped on every change, so a view can tell its copy is stale.
    revision: int = 0

    @classmethod
    def from_lines(cls, lines: Sequence[str], endings: Sequence[str]) -> "Document":
        doc = cls(list(lines), list(endings))
        doc.newline = dominant(endings)
        return doc

    # ------------------------------------------------------------ the state

    @property
    def dirty(self) -> bool:
        return self._saved_at != len(self._undo)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def mark_saved(self) -> None:
        self._saved_at = len(self._undo)

    def text(self) -> str:
        return "".join(line + ending for line, ending in zip(self.lines, self.endings))

    # -------------------------------------------------------------- editing

    def replace(self, start: int, end: int, new_lines: Sequence[str],
                new_endings: Sequence[str] | None = None) -> bool:
        """Lines `start:end` become `new_lines`. False if nothing changed.

        Lines inherit the endings of the lines they replace, position by
        position, and any extra ones get the file's own newline. The end of
        the file is kept as it was: a file without a final newline does not
        grow one, and one with it does not lose it. Keeping that sometimes
        means changing the ending of the line just before the splice -- when
        appending after a last line that had none, or deleting the tail --
        and then the splice is widened by that one line, so that undo puts
        it back too.
        """
        count = len(self.lines)
        start = max(0, min(start, count))
        end = max(start, min(end, count))
        new_lines = list(new_lines)
        explicit = new_endings is not None
        if not explicit:
            old = self.endings[start:end]
            new_endings = [old[k] if k < len(old) and old[k] else self.newline
                           for k in range(len(new_lines))]
        else:
            new_endings = list(new_endings)
        if end == count and count and not explicit:
            tail = self.endings[-1]
            if start == end and new_lines and not tail:
                # Appending after a last line with no ending: it needs one now.
                start -= 1
                new_lines.insert(0, self.lines[start])
                new_endings.insert(0, self.newline)
            elif not new_lines and start > 0 and self.endings[start - 1] != tail:
                # Deleting the tail: the line that becomes last takes its
                # ending, which is usually none.
                start -= 1
                new_lines = [self.lines[start]]
                new_endings = [self.endings[start]]
            if new_lines:
                new_endings[-1] = tail
        for k in range(len(new_lines) - 1):
            if not new_endings[k]:
                new_endings[k] = self.newline
        if self.lines[start:end] == new_lines and self.endings[start:end] == new_endings:
            return False
        splice = Splice(start, self.lines[start:end], self.endings[start:end],
                        new_lines, new_endings)
        self._apply(splice)
        self._undo.append(splice)
        if self._saved_at > len(self._undo) - 1:
            # Saved in a state that was undone past: that state is gone.
            self._saved_at = -1
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
            self._saved_at = self._saved_at - 1 if self._saved_at > 0 else -1
        self._redo.clear()
        return True

    def insert(self, at: int, new_lines: Sequence[str]) -> bool:
        return self.replace(at, at, new_lines)

    def delete(self, start: int, end: int) -> bool:
        return self.replace(start, end, [])

    def undo(self) -> Splice | None:
        if not self._undo:
            return None
        splice = self._undo.pop()
        self._apply(_inverse(splice))
        self._redo.append(splice)
        return splice

    def redo(self) -> Splice | None:
        if not self._redo:
            return None
        splice = self._redo.pop()
        self._apply(splice)
        self._undo.append(splice)
        return splice

    def _apply(self, splice: Splice) -> None:
        end = splice.start + len(splice.old_lines)
        self.lines[splice.start:end] = splice.new_lines
        self.endings[splice.start:end] = splice.new_endings
        self.revision += 1


def _inverse(splice: Splice) -> Splice:
    return Splice(splice.start, splice.new_lines, splice.new_endings,
                  splice.old_lines, splice.old_endings)


def dominant(endings: Sequence[str]) -> str:
    counts = Counter(e for e in endings if e)
    if not counts:
        return "\r\n"
    return counts.most_common(1)[0][0]
