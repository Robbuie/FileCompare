"""Table compare: two CSV files matched row by row on a key column.

A line diff of a CSV is right about which lines changed and wrong about what
that means. Insert one row near the top of a schedule sorted differently from
last week's and every line after it moves; change one cell and the whole line
is "changed" with no word on which column. So here the rows are **matched on
a key** -- a tag name, a part number, an address -- wherever they are in the
file, and a matched pair is compared **cell by cell**, with columns matched by
their header name rather than their position.

The key is chosen for you when the files have one: the first column whose
values are present and unique on both sides. Without one, rows are matched by
position, which is what a line diff does anyway. The tab can pick another.

Reading follows what Excel writes: the delimiter is sniffed from comma,
semicolon, tab and bar; quoted fields may hold the delimiter and line breaks;
a byte order mark on the first header is dropped.

Pure Python. No Qt.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

SAME = "same"
CHANGED = "changed"
ONLY_LEFT = "only left"
ONLY_RIGHT = "only right"

#: Key value for "match rows by position".
POSITION = -1

EXTENSIONS = frozenset({"csv", "tsv", "tab"})


def is_table(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return "." in name and name.rsplit(".", 1)[-1].lower() in EXTENSIONS


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    delimiter: str = ","


@dataclass
class Column:
    name: str
    left: int | None       # index in the left file's columns, or None
    right: int | None


@dataclass
class Row:
    left: int | None       # index into the left table's rows
    right: int | None
    status: str
    #: Merged-column indices whose cells differ.
    cells: frozenset[int] = frozenset()


@dataclass
class TableResult:
    left: Table
    right: Table
    columns: list[Column]
    rows: list[Row]
    key: int                       # merged column used as the key, or POSITION
    key_problem: str = ""
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def differences(self) -> list[int]:
        return [i for i, row in enumerate(self.rows) if row.status != SAME]

    def cell(self, row: Row, column: int, side: int) -> str:
        col = self.columns[column]
        index = col.left if side == 0 else col.right
        table = self.left if side == 0 else self.right
        line = row.left if side == 0 else row.right
        if index is None or line is None:
            return ""
        values = table.rows[line]
        return values[index] if index < len(values) else ""


# --------------------------------------------------------------- reading

def parse(text: str, *, header: bool = True, delimiter: str | None = None) -> Table:
    text = text.lstrip("﻿")
    if delimiter is None:
        delimiter = sniff(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = [row for row in reader]
    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    if header and rows:
        head = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
        return Table(head, rows[1:], delimiter)
    return Table([f"Column {i + 1}" for i in range(width)], rows, delimiter)


def sniff(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    best, score = ",", -1
    for candidate in (",", ";", "\t", "|"):
        counts = [line.count(candidate) for line in sample.splitlines() if line.strip()]
        if not counts or not counts[0]:
            continue
        # Consistent per line beats frequent on one line.
        steady = sum(1 for c in counts if c == counts[0])
        if steady * 1000 + counts[0] > score:
            best, score = candidate, steady * 1000 + counts[0]
    return best


# ------------------------------------------------------------- comparing

@dataclass(frozen=True)
class Options:
    header: bool = True
    #: Merged column index to key on; None picks one; POSITION matches by row.
    key: int | None = None
    ignore_case: bool = False
    trim: bool = True
    #: "1.50" and "1.5" are the same number.
    numeric: bool = True


def columns_of(left: Table, right: Table) -> list[Column]:
    """Columns matched by header name, without case; left order first, then
    the right's own columns where they fall."""
    lookup = {}
    for index, name in enumerate(right.header):
        lookup.setdefault(name.strip().lower(), index)
    used: set[int] = set()
    out: list[Column] = []
    for index, name in enumerate(left.header):
        match = lookup.get(name.strip().lower())
        if match is not None and match not in used:
            used.add(match)
            out.append(Column(name, index, match))
        else:
            out.append(Column(name, index, None))
    for index, name in enumerate(right.header):
        if index not in used:
            out.append(Column(name, None, index))
    return out


def choose_key(left: Table, right: Table, columns: list[Column]) -> int:
    """The first column present on both sides whose values are unique and
    non-empty on both. POSITION when there is none."""
    for number, column in enumerate(columns):
        if column.left is None or column.right is None:
            continue
        if _unique(left, column.left) and _unique(right, column.right):
            return number
    return POSITION


def _unique(table: Table, index: int) -> bool:
    values = [row[index].strip() for row in table.rows]
    return bool(values) and all(values) and len(set(values)) == len(values)


def _norm(value: str, options: Options) -> str:
    if options.trim:
        value = value.strip()
    if options.ignore_case:
        value = value.casefold()
    if options.numeric and value:
        try:
            number = float(value.replace(",", "")) if value.count(",") and "." in value \
                else float(value)
        except ValueError:
            return value
        return repr(number)
    return value


def compare(left: Table, right: Table, options: Options | None = None) -> TableResult:
    options = options or Options()
    columns = columns_of(left, right)
    key = options.key if options.key is not None else choose_key(left, right, columns)
    problem = ""
    if key != POSITION:
        col = columns[key] if 0 <= key < len(columns) else None
        if col is None or col.left is None or col.right is None:
            key, problem = POSITION, "That column is not on both sides; matched by position"
        elif not (_unique(left, col.left) and _unique(right, col.right)):
            problem = (f"{col.name} is not unique on both sides; rows with a repeated "
                       "key are matched in order")

    pairs: list[tuple[int | None, int | None]]
    if key == POSITION:
        n = max(len(left.rows), len(right.rows))
        pairs = [(i if i < len(left.rows) else None, i if i < len(right.rows) else None)
                 for i in range(n)]
    else:
        pairs = _match(left, right, columns[key], options)

    rows: list[Row] = []
    counts = {SAME: 0, CHANGED: 0, ONLY_LEFT: 0, ONLY_RIGHT: 0}
    for li, ri in pairs:
        if li is None:
            status, cells = ONLY_RIGHT, frozenset()
        elif ri is None:
            status, cells = ONLY_LEFT, frozenset()
        else:
            differ = set()
            a, b = left.rows[li], right.rows[ri]
            for number, col in enumerate(columns):
                x = a[col.left] if col.left is not None and col.left < len(a) else None
                y = b[col.right] if col.right is not None and col.right < len(b) else None
                if x is None or y is None:
                    if (x or "").strip() or (y or "").strip():
                        differ.add(number)
                    continue
                if _norm(x, options) != _norm(y, options):
                    differ.add(number)
            cells = frozenset(differ)
            status = CHANGED if cells else SAME
        counts[status] += 1
        rows.append(Row(li, ri, status, cells))
    return TableResult(left, right, columns, rows, key, problem, counts)


def _match(left: Table, right: Table, column: Column,
           options: Options) -> list[tuple[int | None, int | None]]:
    """Pairs in left order, with right-only rows placed after the matched row
    that comes before them on the right -- so a row inserted on the right
    shows where it was inserted."""
    positions: dict[str, list[int]] = {}
    for index, row in enumerate(right.rows):
        positions.setdefault(_norm(row[column.right], options), []).append(index)
    taken: dict[int, int] = {}          # right index -> left index
    left_to_right: list[int | None] = []
    for index, row in enumerate(left.rows):
        candidates = positions.get(_norm(row[column.left], options))
        if candidates:
            right_index = candidates.pop(0)
            taken[right_index] = index
            left_to_right.append(right_index)
        else:
            left_to_right.append(None)
    # Right-only rows, grouped after the nearest matched right row above them.
    after: dict[int | None, list[int]] = {}
    last_matched: int | None = None
    for index in range(len(right.rows)):
        if index in taken:
            last_matched = taken[index]
        else:
            after.setdefault(last_matched, []).append(index)
    out: list[tuple[int | None, int | None]] = [(None, r) for r in after.get(None, [])]
    for index, right_index in enumerate(left_to_right):
        out.append((index, right_index))
        out.extend((None, r) for r in after.get(index, []))
    return out
