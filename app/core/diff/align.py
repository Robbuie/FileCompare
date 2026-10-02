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

**Moved blocks (1.5).** A run of lines removed in one place and the same run
added in another is a move, and is reported as one: each end becomes its own
block whose `move` names the entry in `Comparison.moves` that pairs it with
the other end. The rows keep their kinds -- the left end is still lines only
on the left, and copying it across still inserts them -- so everything that
reads kinds keeps working, and only what draws or counts a block asks whether
it moved. See `_moves` for what is and is not called a move.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence

from app.core.diff import lines as line_diff
from app.core.rules import Rules, is_blank, normaliser, only_comment

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

#: A move has to carry at least this much text, counted without the
#: whitespace at either end of each line. One line is enough when it is long
#: enough -- a rung of a normalised L5X export is one line, and a rung that
#: moved is the commonest move there is -- but a lone `end;` or `}` that
#: happens to appear removed in one place and added in another is coincidence.
MOVE_MIN_CHARS = 16

#: Right-side positions tried per removed line when looking for where it went.
#: A line repeated a thousand times is not going to locate a move anyway.
MOVE_CANDIDATES = 64

#: Line comparisons spent looking for moves before giving up on the rest, so a
#: pathological file costs a bounded fraction of a second and not minutes.
MOVE_BUDGET = 2_000_000

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
    move: int = -1  # index into `Comparison.moves` when this is one end of a move


@dataclass(frozen=True)
class Move:
    """A run of lines removed in one place and added unchanged in another.

    Line ranges are `(first, stop)` on each side; the blocks are the indexes
    of the two ends in `Comparison.blocks`.
    """

    left: tuple[int, int]
    right: tuple[int, int]
    left_block: int
    right_block: int

    @property
    def size(self) -> int:
        return self.left[1] - self.left[0]


@dataclass
class Comparison:
    rows: list[Row] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    left_count: int = 0
    right_count: int = 0
    elapsed: float = 0.0
    moves: list[Move] = field(default_factory=list)

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
        """Line counts by kind, for the status bar.

        A moved line is counted once, as moved, and not also as a line only
        on the left and another only on the right."""
        totals = {name: 0 for name in KIND_NAMES.values()}
        for _l, _r, kind in self.rows:
            totals[KIND_NAMES[kind]] += 1
        moved = sum(move.size for move in self.moves)
        totals["deleted"] -= moved
        totals["inserted"] -= moved
        totals["moved"] = moved
        return totals

    def moved_rows(self) -> set[int]:
        """Every row that is one end of a move."""
        out: set[int] = set()
        for block in self.blocks:
            if block.move >= 0:
                out.update(range(block.start, block.end))
        return out

    def partner(self, block_index: int) -> int | None:
        """The block at the other end of the move `block_index` is one end
        of, or None when it is not part of a move."""
        if not 0 <= block_index < len(self.blocks):
            return None
        move_index = self.blocks[block_index].move
        if move_index < 0:
            return None
        move = self.moves[move_index]
        return move.right_block if block_index == move.left_block else move.left_block

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

    skippable = _skippable(rules)
    if skippable is not None:
        left_kept = [i for i, line in enumerate(left) if not skippable(line)]
        right_kept = [j for j, line in enumerate(right) if not skippable(line)]
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

    found = _moves(rows, left_keys, right_keys, left, right)
    blocks, moves = _blocks_with_moves(rows, found)
    result = Comparison(rows=rows, blocks=blocks, moves=moves,
                        left_count=len(left), right_count=len(right))
    result.elapsed = time.perf_counter() - began
    return result


def _gap(rows: list[Row], left: Sequence[str], right: Sequence[str],
         a0: int, a1: int, b0: int, b1: int, rules: Rules) -> None:
    """Lay out the lines between two matched pairs."""
    if a0 >= a1 and b0 >= b1:
        return
    skippable = _skippable(rules)
    if skippable is not None and all(skippable(left[i]) for i in range(a0, a1)) \
            and all(skippable(right[j]) for j in range(b0, b1)):
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


def _skippable(rules: Rules):
    """The test for a line the rules say to look past entirely -- a blank
    line, a comment-only line -- or None when there is no such rule."""
    blank = rules.blank_lines
    markers = rules.markers if rules.comments else ()
    if not blank and not markers:
        return None
    if blank and markers:
        return lambda line: is_blank(line) or only_comment(line, markers)
    if blank:
        return is_blank
    return lambda line: only_comment(line, markers)


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


def _moves(rows: list[Row], left_keys: Sequence[int], right_keys: Sequence[int],
           left: Sequence[str], right: Sequence[str]) -> list[tuple[int, int, int]]:
    """Runs of removed lines that turn up, in the same order, among the added
    ones: `(left first, right first, length)`.

    Only lines the diff left on one side are candidates. A line that was
    paired with an edit of itself stays an edit; a move is what is left over
    when nothing else explained a removal and an addition. Lines are compared
    by the same normalised keys the diff used, so a block that moved and was
    reindented is still a move when whitespace is being ignored.

    Greedy, longest first from each removed line, top to bottom. That is not
    the optimum over every way of cutting the runs up, and does not need to
    be: a move is a block somebody cut and pasted, and the greedy match finds
    the whole of it.
    """
    removed = {i for i, _j, kind in rows if kind == DELETED}
    added = {j for _i, j, kind in rows if kind == INSERTED}
    if not removed or not added:
        return []
    where: dict[int, list[int]] = {}
    for j in sorted(added):
        where.setdefault(right_keys[j], []).append(j)
    taken_left: set[int] = set()
    taken_right: set[int] = set()
    found: list[tuple[int, int, int]] = []
    budget = MOVE_BUDGET
    for i in sorted(removed):
        if i in taken_left:
            continue
        best_n, best_j = 0, -1
        for j in where.get(left_keys[i], ())[:MOVE_CANDIDATES]:
            if j in taken_right:
                continue
            n = 0
            while (i + n in removed and j + n in added and i + n not in taken_left
                   and j + n not in taken_right
                   and left_keys[i + n] == right_keys[j + n]):
                n += 1
            budget -= n + 1
            if n > best_n:
                best_n, best_j = n, j
        if budget <= 0:
            break
        if best_n == 0:
            continue
        weight = sum(len(left[k].strip()) for k in range(i, i + best_n))
        if weight < MOVE_MIN_CHARS:
            continue
        found.append((i, best_j, best_n))
        taken_left.update(range(i, i + best_n))
        taken_right.update(range(best_j, best_j + best_n))
    return found


def _blocks_with_moves(rows: list[Row], found: list[tuple[int, int, int]]
                       ) -> tuple[list[Block], list[Move]]:
    """The blocks, with each end of each move cut out as a block of its own,
    and the moves pointing at those blocks."""
    if not found:
        return _blocks(rows), []
    group: dict[int, int] = {}
    left_row = {i: r for r, (i, _j, kind) in enumerate(rows) if kind == DELETED}
    right_row = {j: r for r, (_i, j, kind) in enumerate(rows) if kind == INSERTED}
    for number, (i, j, n) in enumerate(found):
        for k in range(n):
            group[left_row[i + k]] = number
            group[right_row[j + k]] = number
    blocks = _blocks(rows, group)
    ends: dict[int, list[int]] = {}
    for index, block in enumerate(blocks):
        if block.move >= 0:
            ends.setdefault(block.move, []).append(index)
    moves: list[Move] = []
    renumber: dict[int, int] = {}
    for number, (i, j, n) in enumerate(found):
        pair = ends.get(number, [])
        # Each end is contiguous in the rows by construction; if that ever
        # stopped being true the move would be in pieces, and a move in
        # pieces is better shown as what it is underneath.
        if len(pair) != 2:
            continue
        left_block = next(b for b in pair if rows[blocks[b].start][2] == DELETED)
        right_block = next(b for b in pair if rows[blocks[b].start][2] == INSERTED)
        renumber[number] = len(moves)
        moves.append(Move((i, i + n), (j, j + n), left_block, right_block))
    out = []
    for block in blocks:
        if block.move >= 0:
            block = Block(block.start, block.end, block.kind, block.significant,
                          renumber.get(block.move, -1))
        out.append(block)
    return out, moves


def _blocks(rows: list[Row], group: dict[int, int] | None = None) -> list[Block]:
    """Runs of rows that are not equal. With `group`, a row's move number:
    a change of group ends one block and starts the next, so each end of a
    move is a block by itself."""
    group = group or {}
    blocks: list[Block] = []
    start = None
    current = -1
    kinds: set[int] = set()

    def close(stop: int) -> None:
        real = kinds - {IGNORED}
        if not real:
            summary = IGNORED
        elif len(real) == 1:
            summary = next(iter(real))
        else:
            summary = CHANGED
        blocks.append(Block(start, stop, summary, bool(real), current))

    for index, (_l, _r, kind) in enumerate(rows + [(0, 0, EQUAL)]):
        if kind != EQUAL:
            here = group.get(index, -1)
            if start is not None and here != current:
                close(index)
                start = None
            if start is None:
                start = index
                current = here
                kinds = set()
            kinds.add(kind)
            continue
        if start is not None:
            close(index)
            start = None
    return blocks


def side_range(rows: Sequence[Row], start: int, end: int, side: int) -> tuple[int, int]:
    """The lines of one side that rows `start:end` show, as `(first, stop)`.

    Rows only ever show a side's lines in order, so the lines a run of rows
    holds are contiguous. A run that holds none of that side's lines -- a
    block that exists only on the other side -- gives an empty range at the
    place those lines would go: just after the nearest line above it, which is
    where copying the block across has to insert it.
    """
    found = [rows[r][side] for r in range(start, end) if rows[r][side] != NONE]
    if found:
        return found[0], found[-1] + 1
    for r in range(start - 1, -1, -1):
        if rows[r][side] != NONE:
            return rows[r][side] + 1, rows[r][side] + 1
    return 0, 0
