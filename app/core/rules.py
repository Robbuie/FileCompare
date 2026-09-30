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
    #: Master switch (Ctrl+I): off compares raw text whatever is set above,
    #: without forgetting what is set.
    enabled: bool = True

    def active(self) -> "Rules":
        """The rules actually in force."""
        return self if self.enabled else Rules(enabled=False)

    def toggled(self) -> "Rules":
        return replace(self, enabled=not self.enabled)

    @property
    def any(self) -> bool:
        """Whether any rule would change a comparison."""
        r = self.active()
        return (r.whitespace != "none" or r.case or r.blank_lines or bool(r.patterns))

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

    def key(line: str) -> str:
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

    if not compiled and whitespace == "none" and not fold:
        return lambda line: line
    return key


def is_blank(line: str) -> bool:
    return not line.strip()
