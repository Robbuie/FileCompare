"""Hex compare: two byte strings side by side, aligned by offset.

Aligned by offset, not by content, on purpose. The binary files this is for
-- firmware images, PLC and HMI exports, recipe blocks -- are fixed layouts
where byte 0x1F4 means the same thing in both; an insertion-aware alignment
would pair bytes that mean different things and call it a match. A file that
grew shows as extra rows on the longer side.

Fast where it matters: the files are compared in 64 KB chunks first, and only
a chunk that differs is looked at row by row, so two 60 MB images that differ
in one block cost two memory compares per chunk and nothing else.

Pure: bytes in, rows out. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WIDTH = 16
CHUNK = 64 * 1024


@dataclass
class HexResult:
    left_size: int
    right_size: int
    width: int = WIDTH
    #: Rows (offset // width) where anything differs, ascending.
    rows: list[int] = field(default_factory=list)
    #: Runs of consecutive differing rows, as (first, stop).
    blocks: list[tuple[int, int]] = field(default_factory=list)
    #: Bytes that differ where both sides have one.
    changed: int = 0

    @property
    def total_rows(self) -> int:
        return (max(self.left_size, self.right_size) + self.width - 1) // self.width

    @property
    def identical(self) -> bool:
        return not self.rows and self.left_size == self.right_size


def compare(a: bytes, b: bytes, width: int = WIDTH) -> HexResult:
    out = HexResult(len(a), len(b), width)
    common = min(len(a), len(b))
    step = CHUNK - CHUNK % width
    rows: list[int] = []
    for start in range(0, common, step):
        stop = min(start + step, common)
        if a[start:stop] == b[start:stop]:
            continue
        for offset in range(start, stop, width):
            end = min(offset + width, stop)
            x, y = a[offset:end], b[offset:end]
            if x != y:
                rows.append(offset // width)
                out.changed += sum(1 for p, q in zip(x, y) if p != q)
    longer = max(len(a), len(b))
    if longer > common:
        first = common // width
        if rows and rows[-1] == first:
            first += 1
        rows.extend(range(first, (longer + width - 1) // width))
    out.rows = rows
    out.blocks = _runs(rows)
    return out


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    for row in rows:
        if blocks and blocks[-1][1] == row:
            blocks[-1] = (blocks[-1][0], row + 1)
        else:
            blocks.append((row, row + 1))
    return blocks


def differing(a: bytes, b: bytes, row: int, width: int = WIDTH) -> list[bool]:
    """Which columns of one row differ (or exist on one side only)."""
    base = row * width
    out = []
    for column in range(width):
        i = base + column
        in_a, in_b = i < len(a), i < len(b)
        out.append(in_a != in_b or (in_a and a[i] != b[i]))
    return out
