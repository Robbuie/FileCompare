"""Logix ASCII exports (.L5K) by structure, the same way as L5X (1.7).

An L5K is the older, text form of the same project an L5X holds, and a line
diff of two of them has the same trouble: the header comment carries the
export date, programs and routines can come out in a different order, a
module's configuration is a wall of numbers, and every attribute of a block
sits on one long line in parentheses, so changing one of them changes a line
nobody can read.

So the file is read into its blocks (`CONTROLLER ... END_CONTROLLER`,
`PROGRAM`, `ROUTINE`, `TAG` and the rest) and its statements (everything that
ends in a semicolon), and rewritten one line per thing a controls engineer
would name, in an order that does not depend on how the export listed it:

    Controller Line4
      ProcessorType = "1756-L83E"
    DataType UDT_Motor
      Member BOOL Run
    Tag Speed : REAL (RADIX := Float) = 1.5
    Program MainProgram
      MAIN = "MainRoutine"
      Tag Local : DINT = 0
      Routine MainRoutine
        Rung: XIC(Start)OTE(Motor);
          // Starts the motor
    Task MainTask

Each block's attributes are one line each, sorted by name, so a changed
attribute is a one-line difference that names itself. Data types, modules,
AOIs, programs, routines, tasks and tags are sorted by name; rungs, structured
text lines, members and parameters keep their order, because there the order
is the logic.

Rung numbers are in the crumb, not the line, for the reason `l5x.py` gives:
one rung inserted near the top would otherwise make every rung below it a
difference.

Ignored, and said so: the header comment (the export date and the software
that wrote it) and the created and edited dates and users on blocks.

The reader is deliberately forgiving. A block whose keyword it does not know
is kept as a block if the file closes it with the matching END_ line, and
its statements are shown in order; anything else is a statement. A file that
is not an L5K at all -- no CONTROLLER block -- is refused, and the plain text
is compared instead with the reason on the status line.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.core.formats import Formatted

#: Attributes that change on every export or edit without the logic changing.
NOISE = frozenset({
    "ExportDate", "ExportOptions", "LastModifiedDate", "LastModifiedBy",
    "EditedDate", "EditedBy", "CreatedDate", "CreatedBy", "ProjectCreationDate",
    "LastModified", "SignatureTimestamp",
})

IGNORED = ("the header comment (export date), created and edited dates and users; "
           "programs, routines, tags, modules and types sorted by name")

#: Blocks known to hold no `;` statements of their own in a way that matters
#: to this reader -- their lines are taken one at a time, in order.
RAW = frozenset({"ST_ROUTINE", "FBD_ROUTINE", "SFC_ROUTINE", "ENCODED_DATA"})

#: Keywords that open a block even where the file happens not to close them
#: (a truncated export still reads as far as it goes).
OPENERS = frozenset({
    "CONTROLLER", "DATATYPE", "MODULE", "ADD_ON_INSTRUCTION_DEFINITION", "TAG",
    "PROGRAM", "ROUTINE", "ST_ROUTINE", "FBD_ROUTINE", "SFC_ROUTINE", "TASK",
    "CONFIG", "PARAMETERS", "LOCAL_TAGS", "CONNECTION", "TREND", "QUICK_WATCH",
    "ENCODED_DATA", "PRIMITIVE", "CHILD_PROGRAMS", "LOGIC", "SHEET",
})

#: How a block is named in the canonical text and in crumbs.
LABELS = {
    "CONTROLLER": "Controller", "DATATYPE": "DataType", "MODULE": "Module",
    "ADD_ON_INSTRUCTION_DEFINITION": "AOI", "PROGRAM": "Program",
    "ROUTINE": "Routine", "ST_ROUTINE": "Routine (ST)", "FBD_ROUTINE": "Routine (FBD)",
    "SFC_ROUTINE": "Routine (SFC)", "TASK": "Task", "CONNECTION": "Connection",
    "TREND": "Trend", "CONFIG": "Config", "QUICK_WATCH": "Watch",
}

#: The order kinds of block come in under the controller; anything else
#: follows, in the order the file has it.
CONTROLLER_ORDER = ("DATATYPE", "MODULE", "ADD_ON_INSTRUCTION_DEFINITION", "TAG",
                    "PROGRAM", "TASK")

#: Statements longer than this inside a module are shown as a short hash: a
#: changed configuration is one line that says which module, not forty lines
#: of numbers that say nothing.
DIGEST_OVER = 160

#: A tag's value longer than this is put on lines of its own, this wide.
VALUE_WIDTH = 100

_WORD = re.compile(r"[A-Z][A-Z0-9_]*")
_RUNG = re.compile(r"^([A-Z]{1,2})\s*:\s*(.*?)\s*;?$", re.S)
_RC = re.compile(r'^RC\s*:\s*(.*?)\s*;?$', re.S)


@dataclass
class Block:
    kind: str
    header: str
    line: int
    items: list = field(default_factory=list)   # Block or Statement

    @property
    def name(self) -> str:
        head = self.header.split("(", 1)[0].strip()
        return head.split()[0] if head.split() else ""

    @property
    def attributes(self) -> list[tuple[str, str]]:
        start = self.header.find("(")
        if start < 0:
            return []
        stop = _closing(self.header, start)
        return _attributes(self.header[start + 1:stop])


@dataclass
class Statement:
    text: str
    line: int


# ------------------------------------------------------------------ reading

def parse(text: str) -> Block:
    """The file as a tree of blocks under a root whose kind is ''."""
    root = Block("", "", 0)
    stack = [root]
    ends = set(re.findall(r"^\s*END_([A-Z0-9_]+)", text, re.M))
    buf: list[str] = []
    buf_line = 0
    depth = 0
    in_string = ""
    in_comment = False

    def flush() -> None:
        nonlocal buf, depth
        joined = " ".join(piece for piece in buf if piece).strip()
        buf = []
        depth = 0
        if joined:
            stack[-1].items.append(Statement(_squash(joined), buf_line))

    for number, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if stack[-1].kind in RAW and not buf and not in_comment:
            if line.startswith("END_") and line[4:].rstrip(";").strip() == stack[-1].kind:
                stack.pop()
            elif line:
                # Whatever follows an ST line's quote, indentation included,
                # is kept; see _routine.
                stack[-1].items.append(Statement(line, number))
            continue
        if not buf and not in_string and not in_comment:
            word = _first_word(line)
            if word.startswith("END_"):
                _close(stack, word[4:])
                continue
        elif buf and not in_string and not in_comment and line.startswith("END_"):
            # A statement that never got its semicolon: it ends where the
            # block does, rather than swallowing the rest of the file.
            flush()
            _close(stack, _first_word(line)[4:])
            continue
        # Scan the line: strings, comments, nesting.
        kept = []
        i = 0
        while i < len(line):
            ch = line[i]
            if in_comment:
                end = line.find("*)", i)
                if end < 0:
                    i = len(line)
                    break
                in_comment = False
                i = end + 2
                continue
            if in_string:
                kept.append(ch)
                if ch == "$" and i + 1 < len(line):
                    kept.append(line[i + 1])
                    i += 2
                    continue
                if ch == in_string:
                    in_string = ""
                i += 1
                continue
            if line.startswith("(*", i):
                in_comment = True
                i += 2
                continue
            if ch in "\"'":
                in_string = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            kept.append(ch)
            i += 1
        piece = "".join(kept).strip()
        if not piece and not buf:
            continue
        if not buf:
            buf_line = number
        buf.append(piece)
        if in_string or in_comment or depth:
            continue
        joined = " ".join(p for p in buf if p).strip()
        if joined.endswith(";"):
            flush()
            continue
        word = _first_word(joined)
        follows = joined[len(word):].lstrip()[:1]
        if word and follows != ":" and (word in OPENERS or word in ends):
            block = Block(word, _squash(joined[len(word):].strip()), buf_line)
            stack[-1].items.append(block)
            stack.append(block)
            buf = []
            depth = 0
    flush()
    return root


def _first_word(line: str) -> str:
    match = _WORD.match(line)
    return match.group(0) if match else ""


def _close(stack: list[Block], kind: str) -> None:
    """END_X closes the innermost open X, and anything left open inside it."""
    for index in range(len(stack) - 1, 0, -1):
        if stack[index].kind == kind:
            del stack[index:]
            return


def _squash(text: str) -> str:
    """Runs of whitespace to one space, outside strings."""
    out = []
    quote = ""
    space = False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "$" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch.isspace():
            space = True
            i += 1
            continue
        if space and out:
            out.append(" ")
        space = False
        if ch in "\"'":
            quote = ch
        out.append(ch)
        i += 1
    return "".join(out)


def _closing(text: str, start: int) -> int:
    """Index of the bracket that closes the one at `start`, or the end."""
    depth = 0
    quote = ""
    i = start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "$":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def _split_top(text: str, sep: str = ",") -> list[str]:
    """`text` cut at `sep` where it is not inside a string or brackets."""
    parts, depth, quote, start, i = [], 0, "", 0, 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "$":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _attributes(inside: str) -> list[tuple[str, str]]:
    out = []
    for part in _split_top(inside):
        key, sep, value = part.partition(":=")
        out.append((key.strip(), value.strip()) if sep else (part, ""))
    return out


def _unquote(text: str) -> str:
    """An L5K string's text: quotes off, `$N` a line break, `$x` the x."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "$" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "NnLlRr" else "\t" if nxt in "Tt" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _digest(text: str) -> str:
    return hashlib.sha1("".join(text.split()).encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------- writing

def normalise(text: str) -> Formatted:
    root = parse(text)
    controllers = [b for b in root.items if isinstance(b, Block) and b.kind == "CONTROLLER"]
    if not controllers:
        raise ValueError("not a Logix export (no CONTROLLER block)")
    out = Formatted(ignored=IGNORED)
    for item in root.items:
        if isinstance(item, Statement):
            _line(out, 0, item.text, "Export")
        elif item.kind == "CONTROLLER":
            _controller(item, out)
        else:
            _generic(item, out, 0, "")
    return out


def _line(out: Formatted, depth: int, text: str, crumb: str) -> None:
    out.lines.append("  " * depth + text)
    out.crumbs.append(crumb)


def _head(block: Block, out: Formatted, depth: int, crumb: str) -> None:
    """The block's own line, then its attributes one per line, sorted."""
    label = LABELS.get(block.kind, block.kind.replace("_", " ").title())
    _line(out, depth, f"{label} {block.name}".rstrip(), crumb)
    attributes = [(k, v) for k, v in block.attributes if k not in NOISE]
    for key, value in sorted(attributes, key=lambda kv: kv[0].lower()):
        if key == "Description":
            text = " / ".join(l.strip() for l in _unquote(value).splitlines())
            _line(out, depth + 1, f"Description: {text}", crumb)
        else:
            _line(out, depth + 1, f"{key} = {value}" if value else key, crumb)


def _by_name(blocks: list[Block]) -> list[Block]:
    return sorted(blocks, key=lambda b: b.name.lower())


def _controller(block: Block, out: Formatted) -> None:
    crumb = f"Controller {block.name}".rstrip()
    _head(block, out, 0, crumb)
    groups: dict[str, list[Block]] = {}
    others: list = []
    for item in block.items:
        if isinstance(item, Block) and item.kind in CONTROLLER_ORDER:
            groups.setdefault(item.kind, []).append(item)
        else:
            others.append(item)
    for kind in CONTROLLER_ORDER:
        items = groups.get(kind, [])
        if kind == "TAG":
            _tags([s for b in items for s in b.items if isinstance(s, Statement)],
                  out, 0, "Controller tags")
            continue
        for item in _by_name(items):
            if kind == "PROGRAM":
                _program(item, out)
            elif kind == "ADD_ON_INSTRUCTION_DEFINITION":
                _aoi(item, out)
            elif kind == "DATATYPE":
                _datatype(item, out)
            elif kind == "MODULE":
                _module(item, out, 0)
            elif kind == "TASK":
                _task(item, out)
            else:
                _generic(item, out, 0, "")
    for item in others:
        if isinstance(item, Statement):
            _line(out, 1, item.text, crumb)
        else:
            _generic(item, out, 0, "")


def _generic(block: Block, out: Formatted, depth: int, parent: str) -> None:
    """A block this reader has no special knowledge of: its head, then its
    contents in the file's order."""
    label = LABELS.get(block.kind, block.kind.replace("_", " ").title())
    here = f"{label} {block.name}".strip()
    crumb = f"{parent} / {here}" if parent else here
    _head(block, out, depth, crumb)
    for item in block.items:
        if isinstance(item, Statement):
            _line(out, depth + 1, item.text, crumb)
        else:
            _generic(item, out, depth + 1, crumb)


def _task(block: Block, out: Formatted) -> None:
    crumb = f"Task {block.name}"
    _head(block, out, 0, crumb)
    for item in block.items:
        if isinstance(item, Statement):
            _line(out, 1, f"Runs {item.text.rstrip(';').strip()}", crumb)
        else:
            _generic(item, out, 1, crumb)


def _datatype(block: Block, out: Formatted) -> None:
    crumb = f"DataType {block.name}"
    _head(block, out, 0, crumb)
    for item in block.items:
        if isinstance(item, Statement):
            text = item.text.rstrip(";").strip()
            parts = text.split()
            member = parts[1].split("(")[0].split("[")[0] if len(parts) > 1 else ""
            _line(out, 1, f"Member {text}", f"{crumb} / {member}" if member else crumb)
        else:
            _generic(item, out, 1, crumb)


def _module(block: Block, out: Formatted, depth: int, parent: str = "") -> None:
    label = LABELS.get(block.kind, block.kind.title())
    here = f"{label} {block.name}".strip()
    crumb = f"{parent} / {here}" if parent else here
    _head(block, out, depth, crumb)
    for item in block.items:
        if isinstance(item, Statement):
            text = item.text
            if len(text) > DIGEST_OVER:
                key = text.split(":=", 1)[0].strip() if ":=" in text else text.split()[0]
                text = f"{key} {_digest(text)}"
            _line(out, depth + 1, text, crumb)
        else:
            _module(item, out, depth + 1, crumb)


def _tag_name(text: str) -> str:
    match = re.match(r"\s*([A-Za-z_][\w]*)", text)
    return match.group(1) if match else text


def _tags(statements: list[Statement], out: Formatted, depth: int, crumb: str) -> None:
    for item in sorted(statements, key=lambda s: _tag_name(s.text).lower()):
        name = _tag_name(item.text)
        here = f"{crumb} / {name}" if crumb else name
        text = item.text.rstrip(";").strip()
        parts = _split_top(text, ":")
        # `Name : TYPE (attrs) := value` cuts at top-level colons into the
        # name, the type and attributes, and `= value`.
        value = ""
        if len(parts) >= 3 and parts[-1].startswith("="):
            value = parts[-1][1:].strip()
            text = " : ".join(parts[:-1])
        if not value or len(value) <= VALUE_WIDTH + 20:
            _line(out, depth, f"Tag {text}" + (f" = {value}" if value else ""), here)
            continue
        _line(out, depth, f"Tag {text} =", here)
        for start in range(0, len(value), VALUE_WIDTH):
            _line(out, depth + 2, value[start:start + VALUE_WIDTH], here)


def _program(block: Block, out: Formatted) -> None:
    crumb = f"Program {block.name}"
    _head(block, out, 0, crumb)
    tags = [s for b in block.items if isinstance(b, Block) and b.kind == "TAG"
            for s in b.items if isinstance(s, Statement)]
    _tags(tags, out, 1, crumb)
    routines = [b for b in block.items if isinstance(b, Block) and b.kind.endswith("ROUTINE")]
    for routine in _by_name(routines):
        _routine(routine, out, 1, crumb)
    for item in block.items:
        if isinstance(item, Statement):
            _line(out, 1, item.text, crumb)
        elif item.kind != "TAG" and not item.kind.endswith("ROUTINE"):
            _generic(item, out, 1, crumb)


def _aoi(block: Block, out: Formatted) -> None:
    crumb = f"AOI {block.name}"
    _head(block, out, 0, crumb)
    for item in block.items:
        if isinstance(item, Statement):
            _line(out, 1, item.text, crumb)
        elif item.kind == "PARAMETERS":
            for statement in item.items:
                if isinstance(statement, Statement):
                    name = _tag_name(statement.text)
                    _line(out, 1, f"Parameter {statement.text.rstrip(';').strip()}",
                          f"{crumb} / {name}")
        elif item.kind == "LOCAL_TAGS":
            _tags([s for s in item.items if isinstance(s, Statement)], out, 1,
                  f"{crumb} / local")
        elif item.kind.endswith("ROUTINE"):
            pass
        else:
            _generic(item, out, 1, crumb)
    routines = [b for b in block.items if isinstance(b, Block) and b.kind.endswith("ROUTINE")]
    for routine in _by_name(routines):
        _routine(routine, out, 1, crumb)


def _routine(block: Block, out: Formatted, depth: int, parent: str) -> None:
    crumb = f"{parent} / {block.name}"
    _head(block, out, depth, crumb)
    if block.kind == "ST_ROUTINE":
        for number, item in enumerate(i for i in block.items if isinstance(i, Statement)):
            # The leading quote is how L5K marks a line of structured text;
            # the indentation after it is the author's and is kept, so the
            # whitespace rules decide whether it counts.
            body = item.text[1:] if item.text.startswith("'") else item.text
            _line(out, depth + 1, body.rstrip(), f"{crumb} / Line {number}")
        return
    if block.kind != "ROUTINE":
        for item in block.items:
            if isinstance(item, Statement):
                _line(out, depth + 1, item.text, crumb)
            else:
                _generic(item, out, depth + 1, crumb)
        return
    rung = 0
    comments: list[str] = []
    for item in block.items:
        if not isinstance(item, Statement):
            _generic(item, out, depth + 1, crumb)
            continue
        text = item.text
        match = _RC.match(text)
        if match:
            comments.extend(_unquote(match.group(1)).splitlines() or [""])
            continue
        match = _RUNG.match(text)
        if match:
            kind, body = match.groups()
            here = f"{crumb} / Rung {rung}"
            prefix = "Rung" if kind == "N" else f"Rung ({kind})"
            _line(out, depth + 1, f"{prefix}: {body};", here)
            for comment in comments:
                _line(out, depth + 2, f"// {comment.strip()}", here)
            comments = []
            rung += 1
            continue
        _line(out, depth + 1, text, crumb)
    for comment in comments:
        _line(out, depth + 1, f"// {comment.strip()}", crumb)


__all__ = ["normalise", "parse"]
