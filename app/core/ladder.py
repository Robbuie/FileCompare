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
#: Drawn as coils: a pair of arcs, the tag above. RES, JMP and RET are
#: coils in Logix Designer too, with their name between the arcs.
COILS = frozenset({"OTE", "OTL", "OTU", "RES", "JMP", "RET"})
#: One-shots are small boxes in Logix Designer, but a single tag: drawn as a
#: contact with their name in it, which is how they read.
ONE_SHOTS = frozenset({"ONS"})


@dataclass(frozen=True)
class Spec:
    """How Logix Designer draws a box instruction (1.24): the title under its
    name, a label for each operand, and the status bits it shows on its right
    edge. Operands past the labels are shown unlabelled."""

    title: str
    labels: tuple[str, ...] = ()
    pins: tuple[str, ...] = ()


_TIMER = ("Timer", "Preset", "Accum")
_COUNTER = ("Counter", "Preset", "Accum")
_MATH = ("Source A", "Source B", "Dest")
_ONE = ("Source", "Dest")
_CMP = ("Source A", "Source B")

#: The box instructions people meet most, as Logix Designer labels them. An
#: instruction not listed here -- an AOI, a rarer one -- is still drawn, with
#: its operands unlabelled.
SPECS: dict[str, Spec] = {
    "TON": Spec("Timer On Delay", _TIMER, ("EN", "DN")),
    "TOF": Spec("Timer Off Delay", _TIMER, ("EN", "DN")),
    "RTO": Spec("Retentive Timer On", _TIMER, ("EN", "DN")),
    "CTU": Spec("Count Up", _COUNTER, ("CU", "DN")),
    "CTD": Spec("Count Down", _COUNTER, ("CD", "DN")),
    "MOV": Spec("Move", _ONE),
    "MVM": Spec("Masked Move", ("Source", "Mask", "Dest")),
    "COP": Spec("Copy File", ("Source", "Dest", "Length")),
    "CPS": Spec("Synchronous Copy File", ("Source", "Dest", "Length")),
    "FLL": Spec("File Fill", ("Source", "Dest", "Length")),
    "CLR": Spec("Clear", ("Dest",)),
    "BTD": Spec("Bit Field Distribute", ("Source", "Source Bit", "Dest", "Dest Bit", "Length")),
    "SWPB": Spec("Swap Byte", ("Source", "Order Mode", "Dest")),
    "ADD": Spec("Add", _MATH),
    "SUB": Spec("Subtract", _MATH),
    "MUL": Spec("Multiply", _MATH),
    "DIV": Spec("Divide", _MATH),
    "MOD": Spec("Modulo", _MATH),
    "AND": Spec("Bitwise And", _MATH),
    "OR": Spec("Bitwise Inclusive Or", _MATH),
    "XOR": Spec("Bitwise Exclusive Or", _MATH),
    "NOT": Spec("Bitwise Not", _ONE),
    "SQR": Spec("Square Root", _ONE),
    "ABS": Spec("Absolute Value", _ONE),
    "NEG": Spec("Negate", _ONE),
    "TOD": Spec("To BCD", _ONE),
    "FRD": Spec("From BCD", _ONE),
    "CPT": Spec("Compute", ("Dest", "Expression")),
    "CMP": Spec("Compare", ("Expression",)),
    "EQU": Spec("Equal", _CMP),
    "NEQ": Spec("Not Equal", _CMP),
    "LES": Spec("Less Than (A<B)", _CMP),
    "LEQ": Spec("Less Than or Equal (A<=B)", _CMP),
    "GRT": Spec("Greater Than (A>B)", _CMP),
    "GEQ": Spec("Greater Than or Equal (A>=B)", _CMP),
    "LIM": Spec("Limit Test", ("Low Limit", "Test", "High Limit")),
    "MEQ": Spec("Masked Equal", ("Source", "Mask", "Compare")),
    "OSR": Spec("One Shot Rising", ("Storage Bit", "Output Bit")),
    "OSF": Spec("One Shot Falling", ("Storage Bit", "Output Bit")),
    "JSR": Spec("Jump To Subroutine", ("Routine Name", "Input Par count")),
    "SBR": Spec("Subroutine", ("Input Par",)),
    "LBL": Spec("Label", ("Label",)),
    "MSG": Spec("Message", ("Message Control",), ("EN", "DN", "ER")),
    "GSV": Spec("Get System Value", ("Class Name", "Instance Name", "Attribute Name", "Dest")),
    "SSV": Spec("Set System Value", ("Class Name", "Instance Name", "Attribute Name",
                                     "Source")),
    "BSL": Spec("Bit Shift Left", ("Array", "Control", "Source Bit", "Length"),
                ("EN", "DN", "ER")),
    "BSR": Spec("Bit Shift Right", ("Array", "Control", "Source Bit", "Length"),
                ("EN", "DN", "ER")),
    "FFL": Spec("FIFO Load", ("Source", "FIFO", "Control", "Length", "Position"),
                ("EN", "DN", "EM")),
    "FFU": Spec("FIFO Unload", ("FIFO", "Dest", "Control", "Length", "Position"),
                ("EU", "DN", "EM")),
    "LFL": Spec("LIFO Load", ("Source", "LIFO", "Control", "Length", "Position"),
                ("EN", "DN", "EM")),
    "LFU": Spec("LIFO Unload", ("LIFO", "Dest", "Control", "Length", "Position"),
                ("EU", "DN", "EM")),
    "SQO": Spec("Sequencer Output", ("Array", "Mask", "Dest", "Control", "Length", "Position"),
                ("EN", "DN", "ER")),
    "SQI": Spec("Sequencer Input", ("Array", "Mask", "Source", "Control", "Length",
                                    "Position")),
    "FAL": Spec("File Arith/Logical", ("Control", "Length", "Position", "Mode", "Dest",
                                       "Expression"), ("EN", "DN", "ER")),
    "FSC": Spec("File Search/Compare", ("Control", "Length", "Position", "Mode",
                                        "Expression"), ("EN", "DN", "ER", "IN")),
    "SIZE": Spec("Size In Elements", ("Source", "Dim. To Vary", "Size")),
    "CONCAT": Spec("String Concatenate", ("Source A", "Source B", "Dest")),
    "MID": Spec("Middle String", ("Source", "Qty", "Start", "Dest")),
    "FIND": Spec("Find String", ("Source", "Search", "Start", "Result")),
    "DTOS": Spec("DINT to String", _ONE),
    "STOD": Spec("String to DINT", _ONE),
    "RTOS": Spec("Real to String", _ONE),
    "STOR": Spec("String to Real", _ONE),
    "PID": Spec("Proportional Integral Derivative",
                ("PID", "Process Variable", "Tieback", "Control Variable", "PID Master Loop",
                 "Inhold Bit", "Inhold Value", "Setpoint", "Process Variable", "Output %"),
                ("EN", "DN", "ER")),
}


def spec(name: str) -> Spec | None:
    return SPECS.get(name.upper())


def box_lines(instr: "Instr") -> list[tuple[str, str]]:
    """A box's operands as Logix Designer lists them: (label, value), the
    label empty for an operand past the ones it names."""
    if instr.raw:
        return []
    known = spec(instr.name)
    labels = known.labels if known is not None else ()
    return [(labels[n] if n < len(labels) else "", value)
            for n, value in enumerate(instr.operands)]


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
BOX_WIDTH = 2.5
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
    known = spec(instr.name)
    # Status bits down the right edge want a line of space between them.
    pins = 2 * len(known.pins) if known is not None and not instr.raw else 0
    return max(1, -(-max(lines, pins) // BOX_LINES))


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


def counterparts(left: Series | None, right: Series | None) -> tuple[dict[int, Instr],
                                                                     dict[int, Instr]]:
    """For each instruction `mark` calls CHANGED, the one opposite it, so a
    box whose preset changed can colour the preset and not the whole box."""
    a = instructions(left) if left is not None else []
    b = instructions(right) if right is not None else []
    out_a: dict[int, Instr] = {}
    out_b: dict[int, Instr] = {}
    matcher = SequenceMatcher(None, [i.key for i in a], [i.key for i in b], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            for k in range(min(i2 - i1, j2 - j1)):
                out_a[i1 + k] = b[j1 + k]
                out_b[j1 + k] = a[i1 + k]
    return out_a, out_b


def changed_operands(instr: Instr, other: Instr | None) -> set[int]:
    """Which operands of `instr` differ from `other`'s, when both are the
    same instruction; None of them can be singled out otherwise."""
    if other is None or instr.raw or other.raw or instr.name != other.name \
            or len(instr.operands) != len(other.operands):
        return set()
    return {n for n, (x, y) in enumerate(zip(instr.operands, other.operands)) if x != y}


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


def routine_of(pair: RungPair) -> str:
    """The program and routine a pair is in, "Program Main / MainRoutine":
    the left side's, or the right's when the rung is only on the right."""
    rung = pair.left if pair.left is not None else pair.right
    return rung.where if rung is not None else ""


def other_differences(rows: Sequence[align.Row], blocks: Sequence[align.Block],
                      left: Sequence[str], right: Sequence[str]) -> int:
    """How many of a comparison's differences have no rung in them -- a tag,
    a module, a data type -- which the rung view does not draw and must say
    so rather than look like the whole answer."""
    count = 0
    for block in blocks:
        rungs = False
        for li, ri, _kind in rows[block.start:block.end]:
            for lines, index in ((left, li), (right, ri)):
                if 0 <= index < len(lines) and (is_rung(lines[index])
                                                or _is_comment(lines[index])):
                    rungs = True
        if not rungs:
            count += 1
    return count


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
