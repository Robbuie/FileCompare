"""Ladder rungs from Logix neutral text: parsed, laid out, and compared.

The Logix comparers (`formats/l5x.py`, `formats/l5k.py`) write each rung as
one line of neutral text, `Rung: XIC(Start)[XIO(Stop),XIC(Jog)]OTE(Motor);`,
which is what makes a moved or edited rung one difference. It is also how
Logix Designer exports it, and how nobody reads ladder. This module is what
lets the tab draw the same rungs as rungs (1.16):

* `parse` turns the neutral text into a tree: a `Series` of `Instr`s and
  `Branch`es, a branch being parallel `Series` legs.
* `layout` places that tree on a grid, in cell units, and says where every
  instruction, wire and branch rail goes. Top-level instructions wrap onto a
  new line when the rung is wider than it is allowed to be, as Logix
  Designer wraps them; a branch is never split.
* `mark` compares two rungs instruction by instruction, so the view can
  colour the contact that changed rather than the whole rung.
* `pairs` walks a text comparison's rows and picks out the rungs, left and
  right, with their comments, crumbs and whether they differ.

Pure, like the engine: strings in, data out. No Qt.

The parser is forgiving on purpose. Neutral text from an export is regular,
but a rung can hold an instruction this application has never heard of, an
expression in a CMP, an array index, or a `?` for an operand nobody filled
in. Anything with a name and parentheses is an instruction; anything else
left over is kept as a box of its own text, so a rung is never dropped and
never drawn as something it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence, Union

from app.core.diff import align

# ------------------------------------------------------------------ the tree

#: Drawn as contacts: a pair of upright bars, the tag above.
CONTACTS = frozenset({"XIC", "XIO"})
#: Drawn as coils: a pair of arcs, the tag above.
COILS = frozenset({"OTE", "OTL", "OTU"})
#: One-shots are small boxes in Logix Designer, but a single tag: drawn as a
#: contact with their name in it, which is how they read.
ONE_SHOTS = frozenset({"ONS"})


@dataclass(frozen=True)
class Instr:
    name: str
    operands: tuple[str, ...] = ()
    #: The text it was parsed from, for anything that was not an instruction.
    raw: str = ""

    @property
    def key(self) -> str:
        """What two instructions compare by."""
        if self.raw:
            return self.raw
        return f"{self.name}({','.join(self.operands)})"

    @property
    def shape(self) -> str:
        if self.name in CONTACTS:
            return "contact"
        if self.name in COILS:
            return "coil"
        if self.name in ONE_SHOTS and len(self.operands) == 1:
            return "contact"
        return "box"


@dataclass
class Series:
    items: list[Union[Instr, "Branch"]] = field(default_factory=list)


@dataclass
class Branch:
    legs: list[Series] = field(default_factory=list)


def parse(text: str) -> Series:
    """A rung's neutral text as a tree. Accepts the text with or without the
    `Rung:` prefix the comparers add and the `;` Logix ends it with."""
    body = rung_body(text)
    parser = _Parser(body)
    series = parser.series(top=True)
    return series


def rung_body(text: str) -> str:
    """`Rung (D): XIC(A)OTE(B);` -> `XIC(A)OTE(B)`."""
    text = text.strip()
    if text.startswith("Rung"):
        head, sep, rest = text.partition(":")
        if sep and len(head) <= 12:
            text = rest.strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    return text


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.at = 0

    def _peek(self) -> str:
        while self.at < len(self.text) and self.text[self.at] in " \t\r\n":
            self.at += 1
        return self.text[self.at] if self.at < len(self.text) else ""

    def series(self, top: bool = False) -> Series:
        out = Series()
        while True:
            ch = self._peek()
            if not ch:
                return out
            if ch in ",]" and not top:
                return out
            if ch == "[":
                self.at += 1
                out.items.append(self.branch())
                continue
            if ch in ",]":
                # A stray separator at the top: keep it visible, never lose it.
                out.items.append(Instr("?", raw=ch))
                self.at += 1
                continue
            out.items.append(self.instr())

    def branch(self) -> Branch:
        branch = Branch()
        while True:
            branch.legs.append(self.series())
            ch = self._peek()
            if ch == ",":
                self.at += 1
                continue
            if ch == "]":
                self.at += 1
            return branch

    def instr(self) -> Instr:
        start = self.at
        while self.at < len(self.text) and (self.text[self.at].isalnum()
                                            or self.text[self.at] in "_.:"):
            self.at += 1
        name = self.text[start:self.at]
        if not name or self._peek() != "(":
            # Not NAME(...): a word on its own is kept as a box of that word;
            # any other stray character as one of its own, so nothing in the
            # rung is lost and the next instruction still starts cleanly.
            if not name:
                self.at = start + 1
                name = self.text[start:self.at]
            return Instr(name, raw=name)
        self.at += 1  # the "("
        operands: list[str] = []
        depth = 0
        current = []
        while self.at < len(self.text):
            ch = self.text[self.at]
            self.at += 1
            if ch in "([":
                depth += 1
            elif ch in ")]":
                if depth == 0 and ch == ")":
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                operands.append("".join(current).strip())
                current = []
                continue
            current.append(ch)
        tail = "".join(current).strip()
        if tail or operands:
            operands.append(tail)
        return Instr(name.upper(), tuple(operands))


def instructions(node: Series | Branch) -> list[Instr]:
    """Every instruction in reading order: left to right, a branch's legs top
    to bottom."""
    out: list[Instr] = []

    def walk(item) -> None:
        if isinstance(item, Instr):
            out.append(item)
        elif isinstance(item, Series):
            for child in item.items:
                walk(child)
        else:
            for leg in item.legs:
                walk(leg)
    walk(node)
    return out


# ------------------------------------------------------------------ layout

#: Cells an instruction takes across. A box is two, for its name and operands.
BOX_WIDTH = 2
#: Lines of text a box row holds; a box with more operands is more rows.
BOX_LINES = 3
#: Space either side of a branch, in cells, for its rails.
BRANCH_PAD = 0.25


@dataclass(frozen=True)
class Placed:
    instr: Instr
    index: int          # position in `instructions()` order
    x: float
    y: int
    w: float
    h: int


@dataclass
class Layout:
    placed: list[Placed] = field(default_factory=list)
    #: Horizontal wires on a row: (x1, x2, row).
    wires: list[tuple[float, float, int]] = field(default_factory=list)
    #: Branch rails: (x, first row, last row).
    rails: list[tuple[float, int, int]] = field(default_factory=list)
    #: Where each wrapped line of the rung starts, in rows; the first is 0.
    lines: list[int] = field(default_factory=lambda: [0])
    width: float = 0.0
    height: int = 1


def _box_rows(instr: Instr) -> int:
    lines = 1 + len(instr.operands)
    return max(1, -(-lines // BOX_LINES))


def _measure(item) -> tuple[float, int]:
    if isinstance(item, Instr):
        if item.shape == "box":
            return float(BOX_WIDTH), _box_rows(item)
        return 1.0, 1
    if isinstance(item, Series):
        w, h = 0.0, 1
        for child in item.items:
            cw, ch = _measure(child)
            w += cw
            h = max(h, ch)
        return w, h
    widths = [_measure(leg) for leg in item.legs] or [(0.0, 1)]
    return max(w for w, _h in widths) + 2 * BRANCH_PAD, sum(h for _w, h in widths)


def layout(series: Series, max_width: float = 0.0) -> Layout:
    """Place a rung. `max_width` (cells, 0 for none) wraps the top level."""
    out = Layout()
    counter = [0]

    def place(item, x: float, y: int) -> tuple[float, int]:
        if isinstance(item, Instr):
            w, h = _measure(item)
            out.placed.append(Placed(item, counter[0], x, y, w, h))
            counter[0] += 1
            return w, h
        if isinstance(item, Series):
            cx, h = x, 1
            for child in item.items:
                cw, ch = place(child, cx, y)
                cx += cw
                h = max(h, ch)
            return cx - x, h
        total_w, _total_h = _measure(item)
        left, right = x + BRANCH_PAD, x + total_w - BRANCH_PAD
        row = y
        last = y
        for leg in item.legs or [Series()]:
            lw, lh = place(leg, left, row)
            # A short leg's wire runs on to the closing rail.
            out.wires.append((left + lw, right, row))
            last = row
            row += lh
        # The top leg carries the rung's wire on through the pad.
        out.wires.append((x, left, y))
        out.wires.append((right, x + total_w, y))
        out.rails.append((left, y, last))
        out.rails.append((right, y, last))
        return total_w, row - y

    x, y, line_h = 0.0, 0, 1
    for item in series.items:
        w, h = _measure(item)
        if max_width and x > 0 and x + w > max_width:
            y += line_h
            out.lines.append(y)
            x, line_h = 0.0, 1
        place(item, x, y)
        x += w
        line_h = max(line_h, h)
        out.width = max(out.width, x)
    out.height = y + line_h
    return out


# ------------------------------------------------------------------ compare

#: What `mark` says about one instruction.
SAME, CHANGED, ONLY = 0, 1, 2


def mark(left: Series | None, right: Series | None) -> tuple[list[int], list[int]]:
    """Per instruction, in `instructions()` order on each side: SAME, CHANGED
    (it has a counterpart that differs), or ONLY (nothing opposite it)."""
    a = instructions(left) if left is not None else []
    b = instructions(right) if right is not None else []
    marks_a = [ONLY] * len(a)
    marks_b = [ONLY] * len(b)
    matcher = SequenceMatcher(None, [i.key for i in a], [i.key for i in b], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                marks_a[i1 + k] = SAME
                marks_b[j1 + k] = SAME
        elif op == "replace":
            # Side by side, one for one, as far as both go: an edited contact
            # opposite the one it was. The rest have nothing opposite.
            for k in range(min(i2 - i1, j2 - j1)):
                marks_a[i1 + k] = CHANGED
                marks_b[j1 + k] = CHANGED
    return marks_a, marks_b


# ------------------------------------------------------------------ the rungs

@dataclass
class Rung:
    text: str               # the canonical line, "Rung: ...;"
    crumb: str
    comments: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """"Rung 12" from the crumb, or "Rung" when there is none."""
        tail = self.crumb.rsplit(" / ", 1)[-1] if self.crumb else ""
        return tail if tail.startswith("Rung") else "Rung"

    @property
    def where(self) -> str:
        """The crumb without the rung: "Program Main / MainRoutine"."""
        if " / " in self.crumb and self.crumb.rsplit(" / ", 1)[-1].startswith("Rung"):
            return self.crumb.rsplit(" / ", 1)[0]
        return self.crumb

    @property
    def kind(self) -> str:
        """"N", or the edit-zone letter Logix gives a pending rung (I, R, D...)."""
        head = self.text.strip().partition(":")[0]
        if "(" in head and head.endswith(")"):
            return head[head.index("(") + 1:-1]
        return "N"


@dataclass
class RungPair:
    left: Rung | None
    right: Rung | None
    differs: bool
    #: The first comparison row of this pair, to go to it in the text view.
    row: int = 0


def is_rung(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.startswith("Rung"):
        return False
    head, sep, _rest = stripped.partition(":")
    return bool(sep) and (head == "Rung" or (head.startswith("Rung (") and head.endswith(")")))


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("//")


def pairs(rows: Sequence[align.Row], left: Sequence[str], right: Sequence[str],
          left_crumbs: Sequence[str] = (), right_crumbs: Sequence[str] = ()) -> list[RungPair]:
    """The rungs of a Logix comparison, opposite each other as the text
    comparison put them. A rung removed and another added in the same place
    are one pair: that is how a person reads an edit, whatever the
    similarity threshold made of it."""
    out: list[RungPair] = []
    current: RungPair | None = None
    last_row = -2

    def crumb(crumbs: Sequence[str], index: int) -> str:
        return crumbs[index] if 0 <= index < len(crumbs) else ""

    for number, (li, ri, kind) in enumerate(rows):
        lline = left[li] if li >= 0 else None
        rline = right[ri] if ri >= 0 else None
        differs = kind not in (align.EQUAL, align.IGNORED)
        lrung = lline is not None and is_rung(lline)
        rrung = rline is not None and is_rung(rline)
        if lrung or rrung:
            lr = Rung(lline.strip(), crumb(left_crumbs, li)) if lrung else None
            rr = Rung(rline.strip(), crumb(right_crumbs, ri)) if rrung else None
            if (current is not None and number == last_row + 1 and current.differs
                    and differs and ((lr is None and current.right is None and current.left)
                                     or (rr is None and current.left is None
                                         and current.right))):
                # The other half of a removed-then-added rung.
                if lr is not None:
                    current.left = lr
                else:
                    current.right = rr
            else:
                current = RungPair(lr, rr, differs, number)
                out.append(current)
            last_row = number
            continue
        lcomment = lline is not None and _is_comment(lline)
        rcomment = rline is not None and _is_comment(rline)
        if current is not None and (lcomment or rcomment) and (lline is None or lcomment) \
                and (rline is None or rcomment):
            if lcomment and current.left is not None:
                current.left.comments.append(lline.strip()[2:].strip())
            if rcomment and current.right is not None:
                current.right.comments.append(rline.strip()[2:].strip())
            if differs:
                current.differs = True
            last_row = number
            continue
        current = None
    return out
