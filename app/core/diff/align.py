"""The row model: two files laid out side by side, one row at a time.

Everything in the text view hangs off the list this builds. A row is
`(left, right, kind)`, where `left` and `right` are line numbers (0-based) or
`NONE` for the filler opposite a line that exists on one side only. Because
both panes draw the same rows, they scroll together by construction and can
never drift; the overview map, the gutter, next and previous difference and
the counts are all reads of the same list.

Inside a changed region the lines are **paired by similarity first**, then
by position. Given three lines removed and two added, the two added ones are
put opposite the removed lines they most resemble, and the third removed line
gets a filler opposite it. Pairing by position alone puts an edited line
opposite whatever happened to be at the same offset, and every intraline mark
after that is nonsense; what is left between two similar pairs is paired by
position, because a line replaced by something unrecognisable is still that
line, edited.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

from app.core.diff import lines as line_diff
from app.core.rules import Rules, is_blank, normaliser

NONE = -1

#: Row kinds. Small integers because a large file is a million of these.
EQUAL = 0
CHANGED = 1     # on both sides, and they differ
DELETED = 2     # on the left only
INSERTED = 3    # on the right only
IGNORED = 4     # differs, but only in what the rules look past

KIND_NAMES = {EQUAL: "equal", CHANGED: "changed", DELETED: "deleted",
              INSERTED: "inserted", IGNORED: "ignored"}

#: Similarity two lines need to be put opposite each other in a changed
#: region. Below it they are a removal and an addition, not an edit.
PAIR_THRESHOLD = 0.5

#: Pairing by similarity is quadratic in the region; past this many line pairs
#: a region is paired by position instead. A 60-line rewrite is 3,600 pairs.
PAIR_LIMIT = 3600

Row = tuple[int, int, int]


@dataclass(frozen=True)
class Block:
    """A run of consecutive rows that are not equal: one difference.

    `significant` is False for a block made only of ignored rows. Those are
    drawn, but next and previous step over them and they are not counted.
    """

    start: int      # first row
    end: int        # one past the last row
    kind: int       # CHANGED if mixed or on both sides, else the one kind
    significant: bool


@dataclass
class Comparison:
    rows: list[Row] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    left_count: int = 0
    right_count: int = 0
    elapsed: float = 0.0

    @property
    def differences(self) -> list[Block]:
        return [block for block in self.blocks if block.significant]

    @property
    def identical(self) -> bool:
        """No difference that counts. Ignored ones may still be shown."""
        return not any(block.significant for block in self.blocks)

    @property
    def exact(self) -> bool:
        """Not a character different, rules or no rules."""
        return not self.blocks

    def counts(self) -> dict[str, int]:
        """Line counts by kind, for the status bar."""
        totals = {name: 0 for name in KIND_NAMES.values()}
        for _l, _r, kind in self.rows:
            totals[KIND_NAMES[kind]] += 1
        return totals

    def block_at(self, row: int) -> int | None:
        """Index into `blocks` of the block containing `row`, or None."""
        lo, hi = 0, len(self.blocks)
        while lo < hi:
            mid = (lo + hi) // 2
            block = self.blocks[mid]
            if row < block.start:
                hi = mid
            elif row >= block.end:
                lo = mid + 1
            else:
                return mid
        return None

    def next_difference(self, row: int) -> int | None:
        """Index of the first significant block starting after `row`."""
        for index, block in enumerate(self.blocks):
            if block.significant and block.start > row:
                return index
        return None

    def previous_difference(self, row: int) -> int | None:
        """Index of the last significant block ending before `row`'s block."""
        for index in range(len(self.blocks) - 1, -1, -1):
            block = self.blocks[index]
            if block.significant and block.start < row:
                if block.start <= row < block.end:
                    continue
                return index
        return None


def compare(left: Sequence[str], right: Sequence[str],
            rules: Rules | None = None) -> Comparison:
    """Compare two files given as lists of lines without their endings."""
    began = time.perf_counter()
    rules = (rules or Rules()).active()
    key = normaliser(rules)

    # One table for both sides, so equal keys are equal integers.
    table: dict[str, int] = {}
    left_keys = [table.setdefault(key(line), len(table)) for line in left]
    right_keys = [table.setdefault(key(line), len(table)) for line in right]

    if rules.blank_lines:
        left_kept = [i for i, line in enumerate(left) if not is_blank(line)]
        right_kept = [j for j, line in enumerate(right) if not is_blank(line)]
    else:
        left_kept = list(range(len(left)))
        right_kept = list(range(len(right)))

    runs = line_diff.matches([left_keys[i] for i in left_kept],
                             [right_keys[j] for j in right_kept])

    rows: list[Row] = []
    a = b = 0
    for fi, fj, n in runs:
        for k in range(n):
            i = left_kept[fi + k]
            j = right_kept[fj + k]
            _gap(rows, left, right, a, i, b, j, rules)
            kind = EQUAL if left[i] == right[j] else IGNORED
            rows.append((i, j, kind))
            a, b = i + 1, j + 1
    _gap(rows, left, right, a, len(left), b, len(right), rules)

    result = Comparison(rows=rows, blocks=_blocks(rows),
                        left_count=len(left), right_count=len(right))
    result.elapsed = time.perf_counter() - began
    return result


def _gap(rows: list[Row], left: Sequence[str], right: Sequence[str],
         a0: int, a1: int, b0: int, b1: int, rules: Rules) -> None:
    """Lay out the lines between two matched pairs."""
    if a0 >= a1 and b0 >= b1:
        return
    if rules.blank_lines and all(is_blank(left[i]) for i in range(a0, a1)) \
            and all(is_blank(right[j]) for j in range(b0, b1)):
        # Only blank lines, which the rules say do not count. Paired off
        # where both sides have one, so a blank line added and another
        # removed do not show as two rows.
        for k in range(max(a1 - a0, b1 - b0)):
            i = a0 + k if a0 + k < a1 else NONE
            j = b0 + k if b0 + k < b1 else NONE
            rows.append((i, j, IGNORED))
        return
    if a0 >= a1:
        rows.extend((NONE, j, INSERTED) for j in range(b0, b1))
        return
    if b0 >= b1:
        rows.extend((i, NONE, DELETED) for i in range(a0, a1))
        return
    for i, j in _pair(left, right, a0, a1, b0, b1):
        if i == NONE:
            rows.append((NONE, j, INSERTED))
        elif j == NONE:
            rows.append((i, NONE, DELETED))
        else:
            rows.append((i, j, CHANGED))


def similarity(x: str, y: str) -> float:
    """How alike two lines are, 0 to 1, cheaply.

    `quick_ratio` is a bound from the characters alone and ignores their
    order, which is wrong for text in general and right enough for deciding
    which removed line an added one was edited from. It is also what keeps
    pairing affordable.
    """
    if x == y:
        return 1.0
    x, y = x.strip(), y.strip()
    if not x or not y:
        return 1.0 if x == y else 0.0
    return SequenceMatcher(None, x, y, autojunk=False).quick_ratio()


def _pair(left: Sequence[str], right: Sequence[str],
          a0: int, a1: int, b0: int, b1: int) -> list[tuple[int, int]]:
    """Order-preserving pairing of a changed region's lines by similarity.

    The best monotone matching by total similarity, over pairs that clear the
    threshold -- the LCS recurrence with weights. Past `PAIR_LIMIT` it pairs by
    position, which is what every tool does and is at least predictable.
    """
    n, m = a1 - a0, b1 - b0
    if n * m > PAIR_LIMIT:
        out = []
        for k in range(max(n, m)):
            out.append((a0 + k if k < n else NONE, b0 + k if k < m else NONE))
        return out

    sims = [[similarity(left[a0 + i], right[b0 + j]) for j in range(m)] for i in range(n)]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        row, above = score[i], score[i - 1]
        for j in range(1, m + 1):
            best = max(above[j], row[j - 1])
            s = sims[i - 1][j - 1]
            if s >= PAIR_THRESHOLD:
                best = max(best, above[j - 1] + s)
            row[j] = best

    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        s = sims[i - 1][j - 1]
        if s >= PAIR_THRESHOLD and abs(score[i][j] - (score[i - 1][j - 1] + s)) < 1e-9:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif score[i - 1][j] >= score[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()

    # Between two similarity pairs, whatever is left on both sides is paired
    # by position: a one-line replacement that shares no characters with the
    # original is still an edit of that line, and every other tool shows it as
    # one. Only the surplus on the longer side becomes removed or added lines,
    # removed above added, as in a unified diff.
    out: list[tuple[int, int]] = []
    ci = cj = 0
    for pi, pj in pairs + [(n, m)]:
        left_gap = pi - ci
        right_gap = pj - cj
        both = min(left_gap, right_gap)
        out.extend((a0 + ci + k, b0 + cj + k) for k in range(both))
        out.extend((a0 + k, NONE) for k in range(ci + both, pi))
        out.extend((NONE, b0 + k) for k in range(cj + both, pj))
        if pi < n and pj < m:
            out.append((a0 + pi, b0 + pj))
        ci, cj = pi + 1, pj + 1
    return out


def _blocks(rows: list[Row]) -> list[Block]:
    blocks: list[Block] = []
    start = None
    kinds: set[int] = set()
    for index, (_l, _r, kind) in enumerate(rows + [(0, 0, EQUAL)]):
        if kind != EQUAL:
            if start is None:
                start = index
                kinds = set()
            kinds.add(kind)
            continue
        if start is not None:
            real = kinds - {IGNORED}
            if not real:
                summary = IGNORED
            elif len(real) == 1:
                summary = next(iter(real))
            else:
                summary = CHANGED
            blocks.append(Block(start, index, summary, bool(real)))
            start = None
    return blocks
