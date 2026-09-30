"""Three-way merge: mine, base and theirs, split into chunks, conflicts found.

The classic diff3 shape. Each side is diffed against the base with the same
engine as the text view (`lines.matches`, histogram and patience, so the
alignment is the one a person expects), and the base lines that both sides
kept unchanged are the **sync points**. Between two sync points each side
either left the base alone or changed it:

  * neither changed it            -> EQUAL
  * only mine changed it          -> MINE, taken automatically
  * only theirs changed it        -> THEIRS, taken automatically
  * both changed it the same way  -> BOTH, taken automatically
  * both changed it differently   -> CONFLICT, for a person to decide

A chunk's **resolution** is what the output holds for it. The automatic ones
start resolved; a conflict starts unresolved and the output shows it with
git's markers, so an output saved in a hurry is at least obviously not done.

Pure: lines in, chunks out. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.core.diff import lines as line_diff

EQUAL = "equal"
MINE = "mine"
THEIRS = "theirs"
BOTH = "both"
CONFLICT = "conflict"

# Resolutions a conflict can be given.
TAKE_MINE = "mine"
TAKE_THEIRS = "theirs"
MINE_THEN_THEIRS = "mine+theirs"
THEIRS_THEN_MINE = "theirs+mine"
TAKE_BASE = "base"
CUSTOM = "custom"
UNRESOLVED = ""

Range = tuple[int, int]


@dataclass
class Chunk:
    kind: str
    base: Range
    mine: Range
    theirs: Range
    resolution: str = UNRESOLVED
    #: The lines chosen by hand (CUSTOM).
    custom: list[str] = field(default_factory=list)

    @property
    def conflict(self) -> bool:
        return self.kind == CONFLICT

    @property
    def resolved(self) -> bool:
        return self.kind != CONFLICT or self.resolution != UNRESOLVED


@dataclass
class Merge:
    base: list[str]
    mine: list[str]
    theirs: list[str]
    chunks: list[Chunk]

    @property
    def conflicts(self) -> list[int]:
        return [i for i, c in enumerate(self.chunks) if c.conflict]

    @property
    def unresolved(self) -> list[int]:
        return [i for i, c in enumerate(self.chunks) if not c.resolved]

    @property
    def changes(self) -> list[int]:
        return [i for i, c in enumerate(self.chunks) if c.kind != EQUAL]

    def lines_of(self, chunk: Chunk, which: str) -> list[str]:
        a, b = getattr(chunk, which)
        return getattr(self, which)[a:b]

    def chosen(self, chunk: Chunk) -> list[str] | None:
        """What the output holds for a chunk, or None while it is unresolved."""
        if chunk.kind == EQUAL:
            return self.lines_of(chunk, "base")
        if chunk.kind in (MINE, BOTH) and chunk.resolution in (UNRESOLVED, TAKE_MINE):
            return self.lines_of(chunk, "mine")
        if chunk.kind == THEIRS and chunk.resolution in (UNRESOLVED, TAKE_THEIRS):
            return self.lines_of(chunk, "theirs")
        resolution = chunk.resolution
        if resolution == TAKE_MINE:
            return self.lines_of(chunk, "mine")
        if resolution == TAKE_THEIRS:
            return self.lines_of(chunk, "theirs")
        if resolution == MINE_THEN_THEIRS:
            return self.lines_of(chunk, "mine") + self.lines_of(chunk, "theirs")
        if resolution == THEIRS_THEN_MINE:
            return self.lines_of(chunk, "theirs") + self.lines_of(chunk, "mine")
        if resolution == TAKE_BASE:
            return self.lines_of(chunk, "base")
        if resolution == CUSTOM:
            return list(chunk.custom)
        return None

    def output(self, *, labels: tuple[str, str, str] = ("mine", "base", "theirs")
               ) -> tuple[list[str], list[Range]]:
        """The merged lines, and where each chunk landed in them. An
        unresolved conflict is written with git's markers."""
        out: list[str] = []
        spans: list[Range] = []
        for chunk in self.chunks:
            start = len(out)
            chosen = self.chosen(chunk)
            if chosen is None:
                out.append(f"<<<<<<< {labels[0]}")
                out.extend(self.lines_of(chunk, "mine"))
                out.append(f"||||||| {labels[1]}")
                out.extend(self.lines_of(chunk, "base"))
                out.append("=======")
                out.extend(self.lines_of(chunk, "theirs"))
                out.append(f">>>>>>> {labels[2]}")
            else:
                out.extend(chosen)
            spans.append((start, len(out)))
        return out, spans


def merge(base: Sequence[str], mine: Sequence[str], theirs: Sequence[str]) -> Merge:
    table: dict[str, int] = {}
    key = lambda seq: [table.setdefault(line, len(table)) for line in seq]  # noqa: E731
    kb, km, kt = key(base), key(mine), key(theirs)
    to_mine = _map(line_diff.matches(kb, km))
    to_theirs = _map(line_diff.matches(kb, kt))

    # Base lines both sides kept: the sync points. Both maps are monotone
    # (the matches are in order), so the points are in order on all three.
    sync = [(b, to_mine[b], to_theirs[b]) for b in range(len(base))
            if b in to_mine and b in to_theirs]
    chunks: list[Chunk] = []
    prev = (0, 0, 0)
    for b, m, t in sync + [(len(base), len(mine), len(theirs))]:
        _gap(chunks, base, mine, theirs, (prev[0], b), (prev[1], m), (prev[2], t))
        if b < len(base):
            _append(chunks, Chunk(EQUAL, (b, b + 1), (m, m + 1), (t, t + 1)))
        prev = (b + 1, m + 1, t + 1)
    return Merge(list(base), list(mine), list(theirs), chunks)


def _map(runs) -> dict[int, int]:
    out = {}
    for a, b, length in runs:
        for k in range(length):
            out[a + k] = b + k
    return out


def _gap(chunks: list[Chunk], base, mine, theirs, b: Range, m: Range, t: Range) -> None:
    if b[0] == b[1] and m[0] == m[1] and t[0] == t[1]:
        return
    base_lines = list(base[b[0]:b[1]])
    mine_lines = list(mine[m[0]:m[1]])
    theirs_lines = list(theirs[t[0]:t[1]])
    if mine_lines == base_lines and theirs_lines == base_lines:
        kind = EQUAL
    elif mine_lines == base_lines:
        kind = THEIRS
    elif theirs_lines == base_lines:
        kind = MINE
    elif mine_lines == theirs_lines:
        kind = BOTH
    else:
        kind = CONFLICT
    _append(chunks, Chunk(kind, b, m, t))


def _append(chunks: list[Chunk], chunk: Chunk) -> None:
    if chunk.base[0] == chunk.base[1] and chunk.mine[0] == chunk.mine[1] \
            and chunk.theirs[0] == chunk.theirs[1]:
        return
    if chunks and chunk.kind == EQUAL and chunks[-1].kind == EQUAL:
        last = chunks[-1]
        chunks[-1] = Chunk(EQUAL, (last.base[0], chunk.base[1]), (last.mine[0], chunk.mine[1]),
                           (last.theirs[0], chunk.theirs[1]))
        return
    chunks.append(chunk)
