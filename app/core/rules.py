"""What counts as a difference.

A rule never hides anything. It decides whether two lines count as the same
line for alignment and for the difference count; the view still shows what the
rule looked past, in grey, as an *ignored* difference. A compare that reports
"identical" while forty whitespace changes sit unseen is the one outcome worse
than reporting all forty.

Every rule is a transformation of one line into its comparison key, applied
before hashing. That keeps the diff engine ignorant of rules altogether: it
compares integers, and two lines that normalise to the same text get the same
integer.

Line endings are not a rule here because lines are compared without them. What
line endings a file uses is detected on load and shown in the side's header,
and a file whose endings differ from the other side's says so there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable

#: How whitespace is treated, in increasing order of forgiveness.
WHITESPACE = ("none", "trailing", "change", "all")
WHITESPACE_LABELS = {
    "none": "Whitespace counts",
    "trailing": "Ignore trailing whitespace",
    "change": "Ignore changes in whitespace",
    "all": "Ignore all whitespace",
}

_RUNS = re.compile(r"[ \t\f\v]+")
_ANY = re.compile(r"\s+")


@dataclass(frozen=True)
class Rules:
    whitespace: str = "none"
    case: bool = False           # True: ignore case
    blank_lines: bool = False    # True: blank lines do not count
    #: Regular expressions for text that does not matter, removed from a line
    #: before it is compared -- an export timestamp, a revision stamp.
    patterns: tuple[str, ...] = field(default_factory=tuple)
    #: True: text after a line comment marker does not count, and a line that
    #: is only a comment is looked past like a blank line.
    comments: bool = False
    #: The line comment markers for the files being compared, from their
    #: extension (`comment_markers`). Set by the session, not the user.
    markers: tuple[str, ...] = field(default_factory=tuple)
    #: Master switch (Ctrl+I): off compares raw text whatever is set above,
    #: without forgetting what is set.
    enabled: bool = True

    def active(self) -> "Rules":
        """The rules actually in force."""
        return self if self.enabled else Rules(enabled=False, markers=self.markers)

    def toggled(self) -> "Rules":
        return replace(self, enabled=not self.enabled)

    @property
    def any(self) -> bool:
        """Whether any rule would change a comparison."""
        r = self.active()
        return (r.whitespace != "none" or r.case or r.blank_lines or bool(r.patterns)
                or (r.comments and bool(r.markers)))

    def describe(self) -> str:
        """One line for the status bar: what is being looked past."""
        r = self.active()
        if not r.enabled:
            return "Rules off"
        parts = []
        if r.whitespace != "none":
            parts.append(WHITESPACE_LABELS[r.whitespace].lower().replace("ignore ", ""))
        if r.case:
            parts.append("case")
        if r.blank_lines:
            parts.append("blank lines")
        if r.comments and r.markers:
            parts.append("comments")
        if r.patterns:
            parts.append(f"{len(r.patterns)} pattern{'s' if len(r.patterns) != 1 else ''}")
        return "Ignoring " + ", ".join(parts) if parts else "Exact"


def compile_patterns(patterns: tuple[str, ...]) -> tuple[list[re.Pattern], list[str]]:
    """The patterns that compile, and a message for each that does not.

    A bad pattern is reported and skipped rather than raised: one typo in a
    setting should not stop every comparison.
    """
    good: list[re.Pattern] = []
    bad: list[str] = []
    for text in patterns:
        try:
            good.append(re.compile(text))
        except re.error as exc:
            bad.append(f"{text!r}: {exc}")
    return good, bad


def normaliser(rules: Rules) -> Callable[[str], str]:
    """The function that turns a line into its comparison key."""
    r = rules.active()
    compiled, _bad = compile_patterns(r.patterns)
    whitespace = r.whitespace
    fold = r.case
    markers = r.markers if r.comments else ()

    def key(line: str) -> str:
        if markers:
            line = strip_comment(line, markers)
        for pattern in compiled:
            line = pattern.sub("", line)
        if whitespace == "trailing":
            line = line.rstrip()
        elif whitespace == "change":
            line = _RUNS.sub(" ", line).strip()
        elif whitespace == "all":
            line = _ANY.sub("", line)
        if fold:
            line = line.casefold()
        return line

    if not compiled and whitespace == "none" and not fold and not markers:
        return lambda line: line
    return key


def is_blank(line: str) -> bool:
    return not line.strip()


def strip_comment(line: str, markers: tuple[str, ...]) -> str:
    """The line without its trailing comment. Naive on purpose -- a marker
    inside a string is taken as a comment too -- because what it strips is
    shown in grey as ignored, never hidden, and a language parser per
    extension is a great deal of machinery for a rule that is off by default.
    """
    cut = len(line)
    for marker in markers:
        at = line.find(marker)
        if at != -1 and at < cut:
            if marker.isalpha() and at > 0 and line[at - 1].isalnum():
                continue
            cut = at
    return line[:cut].rstrip() if cut < len(line) else line


def only_comment(line: str, markers: tuple[str, ...]) -> bool:
    return bool(line.strip()) and not strip_comment(line, markers).strip()


#: Line comment markers by extension. Block comments are not covered.
_MARKERS = {
    ("py", "pyw", "sh", "bash", "ps1", "psm1", "yaml", "yml", "toml", "r", "pl", "rb",
     "conf", "cmake", "mk", "dockerfile", "gitignore", "properties"): ("#",),
    ("ini", "cfg", "inf", "reg"): (";", "#"),
    ("c", "h", "cpp", "hpp", "cc", "cs", "java", "js", "ts", "jsx", "tsx", "go", "rs", "swift",
     "kt", "scala", "php", "st", "scl", "css", "scss", "less", "jsonc", "l5k"): ("//",),
    ("vb", "vbs", "bas", "cls", "frm", "vba"): ("'", "REM "),
    ("bat", "cmd"): ("REM ", "rem ", "::"),
    ("sql", "lua", "hs", "ada", "vhd", "vhdl"): ("--",),
    ("asm", "s", "lisp", "el", "clj", "scm"): (";",),
    ("m", "tex", "sty", "erl"): ("%",),
}


def comment_markers(path: str) -> tuple[str, ...]:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else name
    for extensions, markers in _MARKERS.items():
        if ext in extensions:
            return markers
    return ()


def from_config(config) -> Rules:
    """The rules the settings file holds (`core/config.Config`), for a new
    comparison: what Options last set, read by the window and by the
    command-line report alike."""
    whitespace = config.get("compare.whitespace")
    patterns = config.get("compare.patterns")
    return Rules(
        whitespace=whitespace if whitespace in WHITESPACE else "none",
        case=bool(config.get("compare.case")),
        blank_lines=bool(config.get("compare.blank_lines")),
        comments=bool(config.get("compare.comments")),
        patterns=tuple(p for p in patterns if isinstance(p, str))
        if isinstance(patterns, list) else (),
    )
