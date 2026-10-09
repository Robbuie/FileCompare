"""Where each line is in its file, and a one-line summary of each difference (1.19).

The differences list and the location bar say "def copy_job(name)" or
"[Network]" rather than "line 98", because that is how a person remembers a
file. This module works that out from the text alone, per language family:

- **indented** (Python, YAML): a header owns every deeper-indented line under it;
- **braces** (C, C#, Java, JavaScript, Go, Rust and the rest): a function,
  class or namespace header owns the lines until its braces close;
- **begin / end** (VB.NET, VBScript, Structured Text, L5K): `Sub` owns the
  lines until `End Sub`, `FUNCTION_BLOCK` until `END_FUNCTION_BLOCK`;
- **flat** (INI, TOML, Markdown, batch labels): a header owns the lines until
  the next header -- Markdown by level.

It is a reading aid, not a parser: a header it misses leaves its lines under
the enclosing section, and a file it knows nothing about gets no sections,
in which case the list groups by line instead. A format comparer's crumbs
(L5X, L5K by structure) are better than anything here and are used instead.

Pure: no Qt, no files.
"""

from __future__ import annotations

import re

from app.core.diff import align

#: Characters past which a file is not outlined; matches syntax colour's limit.
LIMIT = 8_000_000
SEP = " › "
DEPTH = 3

INDENTED = {
    "python": re.compile(r"^\s*(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)\s*(\([^)]*\)?)?"),
    "yaml": re.compile(r"^(\s*)([A-Za-z_][\w\- ]*):\s*(?:#.*)?$"),
}

BRACES = frozenset({"c", "cpp", "csharp", "java", "javascript", "typescript", "go", "rust",
                    "kotlin", "swift", "php", "css", "scss", "less", "groovy", "dart",
                    "scala", "objective-c", "js", "ts", "c++", "cs"})
_CONTROL = frozenset({"if", "for", "while", "switch", "catch", "foreach", "using", "lock",
                      "return", "else", "do", "try", "fixed", "sizeof", "typeof", "new",
                      "await", "throw", "case", "when", "match", "loop", "unsafe"})
_TYPE = re.compile(r"\b(class|struct|interface|enum|namespace|record|impl|trait|module|object)"
                   r"\s+([A-Za-z_][\w.:<>]*)")
_FUNC = re.compile(r"(?:\bfunction\s+|\bfn\s+|\bfunc\s+(?:\([^)]*\)\s*)?)?([A-Za-z_~][\w:~]*)"
                   r"\s*(?:<[^<>()]*>)?\s*\(([^;{}()]*)\)[^;]*$")
_CSS_RULE = re.compile(r"^\s*([^{};/]+?)\s*\{\s*$")

BEGIN_END = {
    "vb.net": (re.compile(r"^\s*(?:(?:Public|Private|Protected|Friend|Shared|Overrides|"
                          r"Overridable|Overloads|MustOverride|NotOverridable|Partial|Static|"
                          r"Async|Iterator|Default|ReadOnly|WriteOnly|Shadows|MustInherit|"
                          r"NotInheritable|Widening|Narrowing)\s+)*"
                          r"(Sub|Function|Property|Class|Module|Structure|Interface|Namespace|"
                          r"Enum|Operator|Event)\s+([A-Za-z_][\w]*)", re.IGNORECASE),
               re.compile(r"^\s*End\s+(Sub|Function|Property|Class|Module|Structure|Interface|"
                          r"Namespace|Enum|Operator|Event)\b", re.IGNORECASE)),
    "iec-st": (re.compile(r"^\s*(FUNCTION_BLOCK|FUNCTION|PROGRAM|METHOD|ACTION|TYPE|"
                          r"INTERFACE|PROPERTY)\s+([A-Za-z_][\w.]*)", re.IGNORECASE),
               re.compile(r"^\s*END_(FUNCTION_BLOCK|FUNCTION|PROGRAM|METHOD|ACTION|TYPE|"
                          r"INTERFACE|PROPERTY)\b", re.IGNORECASE)),
    "l5k": (re.compile(r"^\s*(CONTROLLER|PROGRAM|ROUTINE|MODULE|DATATYPE|ADD_ON_INSTRUCTION_"
                       r"DEFINITION|TASK)\s+([A-Za-z_][\w.:]*)", re.IGNORECASE),
            re.compile(r"^\s*END_(CONTROLLER|PROGRAM|ROUTINE|MODULE|DATATYPE|ADD_ON_INSTRUCTION_"
                       r"DEFINITION|TASK)\b", re.IGNORECASE)),
}
BEGIN_END["vbscript"] = BEGIN_END["vb.net"]
BEGIN_END["vb"] = BEGIN_END["vb.net"]
BEGIN_END["st"] = BEGIN_END["iec-st"]

FLAT = {
    "ini": re.compile(r"^\s*(\[[^\]]+\])\s*(?:[;#].*)?$"),
    "toml": re.compile(r"^\s*(\[\[?[^\]]+\]\]?)\s*(?:#.*)?$"),
    "bat": re.compile(r"^\s*(:[A-Za-z_][\w\-]*)\s*$"),
    "powershell": re.compile(r"^\s*(?:function|filter|workflow)\s+([\w\-]+)", re.IGNORECASE),
    "bash": re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w\-]*)\s*\(\)\s*\{?\s*$"),
    "sql": re.compile(r"^\s*(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|PROC|FUNCTION|"
                      r"VIEW|TABLE|TRIGGER)\s+([\w.\[\]\"]+)", re.IGNORECASE),
}
FLAT["dosbatch"] = FLAT["bat"]
FLAT["cfg"] = FLAT["ini"]
FLAT["sh"] = FLAT["bash"]
FLAT["pwsh"] = FLAT["powershell"]
_MARKDOWN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _indent(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())


def _join(names: list[str]) -> str:
    return SEP.join(names[-DEPTH:])


def _indented(lines: list[str], key: str) -> list[str]:
    pattern = INDENTED[key]
    stack: list[tuple[int, str]] = []
    out = []
    for line in lines:
        if not line.strip():
            out.append(_join([n for _i, n in stack]))
            continue
        level = _indent(line)
        while stack and level <= stack[-1][0]:
            stack.pop()
        match = pattern.match(line)
        if match:
            if key == "python":
                name = f"{match.group(1)} {match.group(2)}" + (
                    f"({match.group(3).strip('()')})" if match.group(1) == "def" and
                    match.group(3) is not None else "")
            else:
                name = match.group(2).strip()
            stack.append((level, name))
        out.append(_join([n for _i, n in stack]))
    return out


def _strip_strings(line: str) -> str:
    """A line with its string and character literals and // comments taken
    out, so their braces are not counted."""
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(?:\\.|[^'\\])*'", "''", line)
    return line.split("//", 1)[0]


def _braces(lines: list[str], key: str) -> list[str]:
    stack: list[tuple[int, str]] = []
    depth = 0
    pending = ""          # a header whose { is on a following line
    out = []
    in_block_comment = False
    for line in lines:
        code = line
        if in_block_comment:
            end = code.find("*/")
            if end < 0:
                out.append(_join([n for _d, n in stack]))
                continue
            code = code[end + 2:]
            in_block_comment = False
        start = code.find("/*")
        if start >= 0 and code.find("*/", start) < 0:
            code = code[:start]
            in_block_comment = True
        code = _strip_strings(code)
        stripped = code.strip()
        header = ""
        if stripped and not stripped.startswith(("#", "@", "*")):
            typed = _TYPE.search(stripped)
            if typed and not stripped.endswith(";"):
                header = f"{typed.group(1)} {typed.group(2)}"
            elif key in ("css", "scss", "less"):
                rule = _CSS_RULE.match(code)
                if rule:
                    header = rule.group(1).strip()
            else:
                func = _FUNC.search(stripped)
                if func and func.group(1).split("::")[-1].lower() not in _CONTROL \
                        and "=" not in stripped.split("(", 1)[0] \
                        and not stripped.endswith(";"):
                    name = func.group(1)
                    args = (func.group(2) or "").strip()
                    if len(args) > 24:
                        args = args[:22] + "..."
                    header = f"{name}({args})"
        if header:
            pending = header
        opened = code.count("{")
        closed = code.count("}")
        if pending and opened:
            stack.append((depth, pending))
            pending = ""
        elif pending and stripped.endswith(";"):
            pending = ""
        depth += opened - closed
        # Named before anything closes, so a closing brace belongs to what
        # it closes.
        out.append(_join([n for _d, n in stack]))
        while stack and depth <= stack[-1][0]:
            stack.pop()
    return out


def _begin_end(lines: list[str], key: str) -> list[str]:
    begin, end = BEGIN_END[key]
    stack: list[str] = []
    out = []
    for line in lines:
        match = begin.match(line)
        if match and not (key.startswith("vb") and re.search(r"\bDeclare\b", line, re.I)):
            stack.append(f"{match.group(1).capitalize() if key.startswith('vb') else match.group(1).upper()} "
                         f"{match.group(2)}")
            out.append(_join(stack))
            continue
        out.append(_join(stack))
        if end.match(line) and stack:
            stack.pop()
    return out


def _flat(lines: list[str], key: str) -> list[str]:
    pattern = FLAT[key]
    current = ""
    out = []
    for line in lines:
        match = pattern.match(line)
        if match:
            current = match.group(1).strip()
            if key in ("powershell", "pwsh"):
                current = f"function {current}"
            elif key in ("bash", "sh"):
                current = f"{current}()"
        out.append(current)
    return out


def _markdown(lines: list[str]) -> list[str]:
    stack: list[tuple[int, str]] = []
    out = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else _MARKDOWN.match(line)
        if match:
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2)))
        out.append(_join([n for _l, n in stack]))
    return out


def knows(key: str) -> bool:
    return (key in INDENTED or key in BRACES or key in BEGIN_END or key in FLAT
            or key in ("markdown", "md"))


def sections(lines: list[str], key: str) -> list[str] | None:
    """Per line, the section it is in ("" for none), or None when this
    language has no outline here or the file is too big to bother."""
    if not knows(key) or sum(len(line) for line in lines) > LIMIT:
        return None
    if key in INDENTED:
        return _indented(lines, key)
    if key in BRACES:
        return _braces(lines, key)
    if key in BEGIN_END:
        return _begin_end(lines, key)
    if key in ("markdown", "md"):
        return _markdown(lines)
    return _flat(lines, key)


# ------------------------------------------------------- difference summaries

def _words(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 40 else text[:38] + "..."


def summary(comparison: align.Comparison, index: int, left: list[str],
            right: list[str]) -> tuple[str, str]:
    """(title, detail) for one difference: where it is by line number, and
    what it is in a few words -- "copy to copy2", "Only on the left: ..."."""
    from app.core.diff import intraline

    block = comparison.blocks[index]
    rows = comparison.rows[block.start:block.end]
    lefts = [r[0] for r in rows if r[0] != align.NONE]
    rights = [r[1] for r in rows if r[1] != align.NONE]
    if rights:
        title = f"Line {rights[0] + 1}" if len(rights) == 1 else \
            f"Lines {rights[0] + 1}-{rights[-1] + 1}"
    else:
        title = f"Left {lefts[0] + 1}" if len(lefts) == 1 else \
            f"Left {lefts[0] + 1}-{lefts[-1] + 1}"
    if block.move >= 0:
        return title, "Moved: " + _words(left[lefts[0]] if lefts else right[rights[0]])
    if not lefts:
        n = len(rights)
        return title, ("Only on the right: " + _words(right[rights[0]]) if n == 1
                       else f"{n} lines only on the right")
    if not rights:
        n = len(lefts)
        return title, ("Only on the left: " + _words(left[lefts[0]]) if n == 1
                       else f"{n} lines only on the left")
    if len(lefts) == len(rights):
        # Line for line: say what changed on the first, and how many more.
        a, b = left[lefts[0]].expandtabs(4), right[rights[0]].expandtabs(4)
        more = f"  (+{len(lefts) - 1} more)" if len(lefts) > 1 else ""
        spans = intraline.spans(a, b, "word")
        old = " ".join(a[s:e] for s, e in spans[0]).strip()
        new = " ".join(b[s:e] for s, e in spans[1]).strip()
        if not old and not new:
            return title, "Whitespace differs" + more
        if not old:
            return title, "Added " + _words(new) + more
        if not new:
            return title, "Removed " + _words(old) + more
        return title, f"{_words(old)}  to  {_words(new)}" + more
    lines = max(len(lefts), len(rights))
    return title, f"{lines} lines changed"


def section_of(block_rows, sections_pair) -> str:
    """The section a difference is in: its first right line's, or its first
    left line's when it has none on the right."""
    for side in (1, 0):
        names = sections_pair[side]
        if not names:
            continue
        for row in block_rows:
            index = row[side]
            if index != align.NONE and index < len(names):
                return names[index]
    return ""
