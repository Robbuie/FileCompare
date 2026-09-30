"""Which lines of two sequences are the same lines: histogram diff.

The input is two sequences of integers -- one per line, equal integers meaning
equal lines after the rules have had their say (`core/rules.py`). The output is
the runs that match, as `(i, j, n)`: `a[i:i+n] == b[j:j+n]`. Everything else is
a difference, and deciding how to lay it out is `align.py`'s business.

Why histogram and not the textbook algorithm:

  * **Myers finds a shortest edit, not the one a person expects.** In code the
    two differ constantly: given a function inserted above another, Myers will
    happily pair the new function's closing brace with the old one's and report
    the middle of both as changed. The result is minimal and unreadable.
  * **Histogram anchors on rare lines.** A line that occurs once on each side
    is almost certainly the same line; `}` and blank lines are almost certainly
    not evidence of anything. So each region is split at the matching run whose
    rarest line is rarest, and the two halves are solved the same way. This is
    what git's `--histogram` does, and it is the behaviour Beyond Compare and
    WinMerge users are used to.
  * **Unique lines first, all at once.** Before histogram looks for its one
    best anchor, every line that occurs exactly once on each side is taken,
    and the longest chain of them that is in order on both sides (patience
    diff's rule) splits the region at every one of them in a single pass.
    Histogram alone splits a region in two per pass, and with a few hundred
    scattered edits in a large file that is a few hundred passes over most of
    the file: seven seconds on 200,000 lines, against a fraction of one.
  * **It degrades by region, not by file.** Common prefix and suffix are
    trimmed first -- which for two versions of a log is nearly all of it -- and
    the expensive fallback only ever sees the small region histogram could not
    split.

`difflib.SequenceMatcher` is used only as that fallback, on small regions, and
always with `autojunk=False`. With autojunk on (its default), any sequence of
200 or more lines treats a line that makes up more than 1% of it as junk --
blank lines and closing braces, in practice -- and the alignment comes out
wrong in ways that look like a bug in the view.

Iterative rather than recursive: a pathological file splits into regions many
thousands deep, and Python's recursion limit is a thousand.
"""

from __future__ import annotations

from bisect import bisect_left
from difflib import SequenceMatcher
from typing import Sequence

#: A line occurring more often than this in a region is not used as an anchor.
#: git uses 64; past it, the line says nothing about where the other side's
#: copy of it went.
MAX_CHAIN = 64

#: The fallback is quadratic, so it is refused past this many line pairs. What
#: it refuses is reported as one changed region, which is correct if coarse --
#: and only happens when a region has no anchor at all and is huge.
FALLBACK_LIMIT = 4_000_000

Run = tuple[int, int, int]


def matches(a: Sequence[int], b: Sequence[int]) -> list[Run]:
    """The matching runs of `a` and `b`, in order, adjacent runs merged."""
    found: list[Run] = []
    stack = [(0, len(a), 0, len(b))]
    while stack:
        a_lo, a_hi, b_lo, b_hi = stack.pop()

        # Common prefix and suffix: free, and usually most of the file.
        start = 0
        while a_lo + start < a_hi and b_lo + start < b_hi and a[a_lo + start] == b[b_lo + start]:
            start += 1
        if start:
            found.append((a_lo, b_lo, start))
            a_lo += start
            b_lo += start
        end = 0
        while a_hi - end > a_lo and b_hi - end > b_lo and a[a_hi - end - 1] == b[b_hi - end - 1]:
            end += 1
        if end:
            found.append((a_hi - end, b_hi - end, end))
            a_hi -= end
            b_hi -= end
        if a_lo >= a_hi or b_lo >= b_hi:
            continue

        seeds = _unique(a, b, a_lo, a_hi, b_lo, b_hi)
        if seeds:
            # Each seed is a one-line match; the regions between them are
            # solved on their own, and their prefix and suffix trimming grows
            # each seed into the full run around it.
            prev_i, prev_j = a_lo, b_lo
            for i, j in seeds:
                found.append((i, j, 1))
                stack.append((prev_i, i, prev_j, j))
                prev_i, prev_j = i + 1, j + 1
            stack.append((prev_i, a_hi, prev_j, b_hi))
            continue

        anchor = _anchor(a, b, a_lo, a_hi, b_lo, b_hi)
        if anchor is None:
            found.extend(_fallback(a, b, a_lo, a_hi, b_lo, b_hi))
            continue
        i, j, n = anchor
        found.append((i, j, n))
        stack.append((i + n, a_hi, j + n, b_hi))
        stack.append((a_lo, i, b_lo, j))

    return _merge(found)


def _unique(a: Sequence[int], b: Sequence[int],
            a_lo: int, a_hi: int, b_lo: int, b_hi: int) -> list[tuple[int, int]]:
    """Lines occurring once on each side, longest in-order chain of them.

    Patience diff's step: pair up the unique lines, then keep the longest
    subsequence that increases on both sides (the pairs are already in `a`
    order, so that is the longest increasing run of `b` positions, found by
    patience sorting). A unique line moved out of order is left out of the
    chain and turns up as a difference, which is what it is.
    """
    seen_a: dict[int, int] = {}
    for i in range(a_lo, a_hi):
        key = a[i]
        seen_a[key] = -1 if key in seen_a else i
    seen_b: dict[int, int] = {}
    for j in range(b_lo, b_hi):
        key = b[j]
        if key in seen_a:
            seen_b[key] = -1 if key in seen_b else j
    pairs = [(i, seen_b[key]) for key, i in seen_a.items()
             if i >= 0 and seen_b.get(key, -1) >= 0]
    if not pairs:
        return []
    pairs.sort()

    tails: list[int] = []        # smallest b position ending a chain of each length
    tail_at: list[int] = []      # index into pairs of that chain's last pair
    back: list[int] = [-1] * len(pairs)
    for index, (_i, j) in enumerate(pairs):
        k = bisect_left(tails, j)
        if k == len(tails):
            tails.append(j)
            tail_at.append(index)
        else:
            tails[k] = j
            tail_at[k] = index
        back[index] = tail_at[k - 1] if k else -1
    chain: list[tuple[int, int]] = []
    index = tail_at[-1]
    while index >= 0:
        chain.append(pairs[index])
        index = back[index]
    chain.reverse()
    return chain


def _anchor(a: Sequence[int], b: Sequence[int],
            a_lo: int, a_hi: int, b_lo: int, b_hi: int) -> Run | None:
    """The matching run in this region whose rarest line is rarest.

    Ties go to the longer run. Returns None when no line of `b` occurs in `a`
    fewer than `MAX_CHAIN` times -- either nothing is shared, or everything
    shared is too common to trust, and the caller decides which.
    """
    where: dict[int, list[int]] = {}
    for i in range(a_lo, a_hi):
        where.setdefault(a[i], []).append(i)
    count = {key: len(spots) for key, spots in where.items()}

    best: Run | None = None
    best_rare = MAX_CHAIN + 1
    j = b_lo
    while j < b_hi:
        spots = where.get(b[j])
        if spots is None or len(spots) > MAX_CHAIN or len(spots) > best_rare:
            j += 1
            continue
        next_j = j + 1
        for i in spots:
            # Grow the run around (i, j) in both directions.
            s_i, s_j = i, j
            while s_i > a_lo and s_j > b_lo and a[s_i - 1] == b[s_j - 1]:
                s_i -= 1
                s_j -= 1
            e_i, e_j = i + 1, j + 1
            while e_i < a_hi and e_j < b_hi and a[e_i] == b[e_j]:
                e_i += 1
                e_j += 1
            n = e_i - s_i
            rare = min(count[a[k]] for k in range(s_i, e_i))
            if rare < best_rare or (rare == best_rare and best is not None and n > best[2]):
                best = (s_i, s_j, n)
                best_rare = rare
            next_j = max(next_j, e_j)
        j = next_j
    return best


def _fallback(a: Sequence[int], b: Sequence[int],
              a_lo: int, a_hi: int, b_lo: int, b_hi: int) -> list[Run]:
    """A region histogram could not split: nothing shared, or only lines too
    common to anchor on. Solved exactly when it is small enough, and reported
    as one change otherwise."""
    left = a[a_lo:a_hi]
    right = b[b_lo:b_hi]
    if not set(left).intersection(right):
        return []
    if len(left) * len(right) > FALLBACK_LIMIT:
        return []
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    return [(a_lo + i, b_lo + j, n) for i, j, n in matcher.get_matching_blocks() if n]


def _merge(runs: list[Run]) -> list[Run]:
    runs.sort()
    out: list[Run] = []
    for i, j, n in runs:
        if n <= 0:
            continue
        if out:
            pi, pj, pn = out[-1]
            if pi + pn == i and pj + pn == j:
                out[-1] = (pi, pj, pn + n)
                continue
        out.append((i, j, n))
    return out
