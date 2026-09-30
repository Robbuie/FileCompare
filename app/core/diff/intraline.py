"""What differs inside a pair of lines that were put opposite each other.

Asked for lazily, for the rows on screen, and cached by the view: a file of
two hundred thousand edited lines costs nothing here until somebody scrolls to
them.

Two granularities, a setting: **character**, which is what shows a changed
digit in a tag address, and **word**, which reads better for prose and for a
renamed identifier. Both return spans as `(start, end)` character offsets into
each line, ready to paint.

A pair that shares almost nothing is marked whole rather than as confetti.
Two unrelated lines diffed by character agree on a scatter of letters, and
twenty tiny marks across the row say less than one mark over all of it.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

Span = tuple[int, int]

_WORDS = re.compile(r"\w+|\s+|[^\w\s]")

#: Past this length a line is marked whole: character diff is quadratic in
#: the worst case and a 20,000-character line is a minified file, not a line.
LONG_LINE = 4000

#: Below this share of matching text the pair is marked whole.
CONFETTI = 0.3


def spans(a: str, b: str, mode: str = "char") -> tuple[list[Span], list[Span]]:
    """The differing ranges of `a` and of `b`."""
    if a == b:
        return [], []
    if not a or not b or len(a) > LONG_LINE or len(b) > LONG_LINE:
        return _whole(a), _whole(b)

    if mode == "word":
        ta = _WORDS.findall(a)
        tb = _WORDS.findall(b)
    else:
        ta, tb = list(a), list(b)
    matcher = SequenceMatcher(None, ta, tb, autojunk=False)
    blocks = matcher.get_matching_blocks()
    shared = sum(len("".join(ta[i:i + n])) for i, _j, n in blocks)
    if shared < CONFETTI * max(len(a), len(b)):
        return _whole(a), _whole(b)

    offsets_a = _offsets(ta)
    offsets_b = _offsets(tb)
    out_a: list[Span] = []
    out_b: list[Span] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            _add(out_a, offsets_a[i1], offsets_a[i2])
        if j2 > j1:
            _add(out_b, offsets_b[j1], offsets_b[j2])
    return out_a, out_b


def _offsets(tokens: list[str]) -> list[int]:
    out = [0]
    for token in tokens:
        out.append(out[-1] + len(token))
    return out


def _add(out: list[Span], start: int, end: int) -> None:
    """Append a span, joining it to the last one across a gap of one
    character -- a mark either side of a single matching letter reads as one
    change, and is one."""
    if end <= start:
        return
    if out and start - out[-1][1] <= 1:
        out[-1] = (out[-1][0], end)
    else:
        out.append((start, end))


def _whole(text: str) -> list[Span]:
    return [(0, len(text))] if text else []
