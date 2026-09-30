"""Syntax colour for the text view (1.1), by Pygments and two lexers of our own.

Pygments knows about six hundred languages by file name -- C, C#, VB.NET,
PowerShell, batch, SQL, Python, XML, JSON, YAML, INI, G-code and the rest --
and is a dependency for exactly that. It does not know two that matter here,
so they are written below: **L5K** (Logix's ASCII export: controllers, tags,
routines, ladder rungs) and **IEC 61131-3 Structured Text** (`.st`, `.scl`).

What comes out is small on purpose: per line, `(start, stop, category)`
spans, in the columns the view draws -- tabs already expanded, the same
`expandtabs` the view uses -- with only a dozen categories. The view paints a
category in a colour from `theme/syntax.py`; everything uncoloured is the
ordinary ink. A difference is still the loudest thing on a row: the colour
is on the text, the washes and marks behind it are unchanged.

The whole file is lexed at once, because a comment or a string can span
lines and lexing line by line would colour half a file as the inside of a
string. That is work on text, not on a file, but it is not free: a small file
is lexed on the spot, a large one in the loader, and past `LIMIT` characters
not at all -- a 200 MB log gains nothing from colour.

Pure apart from Pygments. No Qt, no files.
"""

from __future__ import annotations

import ntpath
import posixpath
import re

from pygments import lexers as _lexers
from pygments.lexer import RegexLexer, bygroups, words
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Token,
    Whitespace,
)
from pygments.util import ClassNotFound

TAB = 4
#: Characters past which a file is not coloured at all.
LIMIT = 8_000_000
#: Characters under which a file is lexed on the UI thread rather than queued.
SYNC_LIMIT = 250_000

# Categories. Indexes into CATEGORIES; 0 is "ink", never stored.
CATEGORIES = ("ink", "keyword", "type", "function", "string", "number", "comment",
              "constant", "preproc", "tag", "attribute", "builtin", "label")
_INDEX = {name: i for i, name in enumerate(CATEGORIES)}


# ------------------------------------------------------------ our own lexers

class StructuredTextLexer(RegexLexer):
    """IEC 61131-3 Structured Text: Logix routines exported as text, Siemens
    SCL, Codesys. Case does not matter in the language, so none here."""

    name = "Structured Text"
    aliases = ["iec-st", "structured-text", "st", "scl"]
    filenames = ["*.st", "*.scl", "*.stx", "*.iecst"]
    flags = re.IGNORECASE | re.MULTILINE

    tokens = {
        "root": [
            (r"\s+", Whitespace),
            (r"\(\*", Comment.Multiline, "comment"),
            (r"/\*", Comment.Multiline, "ccomment"),
            (r"//.*?$", Comment.Single),
            (r"'(?:\$.|[^'$])*'", String.Single),
            (r'"(?:\$.|[^"$])*"', String.Double),
            (r"\b(?:T|TIME|LT|D|DATE|TOD|TIME_OF_DAY|DT|DATE_AND_TIME)#[\w:.\-]+",
             Number.Other),
            (r"\b\d+#[0-9a-f_]+\b", Number.Hex),
            (r"\b\d[\d_]*\.\d[\d_]*(?:e[+-]?\d+)?\b", Number.Float),
            (r"\b\d[\d_]*\b", Number.Integer),
            (words((
                "IF", "THEN", "ELSIF", "ELSE", "END_IF", "CASE", "OF", "END_CASE",
                "FOR", "TO", "BY", "DO", "END_FOR", "WHILE", "END_WHILE", "REPEAT",
                "UNTIL", "END_REPEAT", "EXIT", "RETURN", "CONTINUE", "JMP",
                "VAR", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_GLOBAL",
                "VAR_EXTERNAL", "VAR_TEMP", "VAR_STAT", "END_VAR", "CONSTANT",
                "RETAIN", "PERSISTENT", "AT", "FUNCTION", "END_FUNCTION",
                "FUNCTION_BLOCK", "END_FUNCTION_BLOCK", "PROGRAM", "END_PROGRAM",
                "METHOD", "END_METHOD", "PROPERTY", "END_PROPERTY", "INTERFACE",
                "END_INTERFACE", "TYPE", "END_TYPE", "STRUCT", "END_STRUCT",
                "ACTION", "END_ACTION", "EXTENDS", "IMPLEMENTS", "BEGIN",
                "ORGANIZATION_BLOCK", "END_ORGANIZATION_BLOCK", "DATA_BLOCK",
                "END_DATA_BLOCK", "REGION", "END_REGION"), suffix=r"\b"), Keyword),
            (words(("AND", "OR", "XOR", "NOT", "MOD", "AND_THEN", "OR_ELSE"),
                   suffix=r"\b"), Operator.Word),
            (words(("TRUE", "FALSE", "NULL"), suffix=r"\b"), Keyword.Constant),
            (words((
                "BOOL", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT",
                "USINT", "UINT", "UDINT", "ULINT", "REAL", "LREAL", "TIME", "LTIME",
                "DATE", "TOD", "DT", "STRING", "WSTRING", "CHAR", "WCHAR", "ARRAY",
                "POINTER", "REFERENCE", "TIMER", "COUNTER", "CONTROL", "ANY"),
                suffix=r"\b"), Keyword.Type),
            (r"\b[a-z_]\w*(?=\s*\()", Name.Function),
            (r"\b[a-z_]\w*\b", Name),
            (r":=|=>|<>|<=|>=|\*\*|[-+*/=<>&]", Operator),
            (r"[;:,.()\[\]^#]", Punctuation),
        ],
        "comment": [
            (r"[^*]+", Comment.Multiline),
            (r"\*\)", Comment.Multiline, "#pop"),
            (r"\*", Comment.Multiline),
        ],
        "ccomment": [
            (r"[^*]+", Comment.Multiline),
            (r"\*/", Comment.Multiline, "#pop"),
            (r"\*", Comment.Multiline),
        ],
    }


#: Ladder instructions, as they appear in an L5K rung (and in L5X rung text).
LADDER = (
    "XIC", "XIO", "OTE", "OTL", "OTU", "ONS", "OSR", "OSF", "TON", "TOF", "RTO",
    "TONR", "TOFR", "RTOR", "CTU", "CTD", "CTUD", "RES", "MOV", "MVM", "COP",
    "CPS", "FLL", "CLR", "ADD", "SUB", "MUL", "DIV", "MOD", "SQR", "NEG", "ABS",
    "CPT", "EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM", "MEQ", "CMP", "AND",
    "OR", "XOR", "NOT", "BTD", "SWPB", "JSR", "SBR", "RET", "JMP", "LBL", "MCR",
    "AFI", "NOP", "TND", "UID", "UIE", "EVENT", "GSV", "SSV", "MSG", "IOT",
    "PID", "PIDE", "SCL", "SCP", "BSL", "BSR", "FFL", "FFU", "LFL", "LFU", "SQO",
    "SQI", "SQL", "FAL", "FSC", "FOR", "BRK", "SIZE", "AVE", "SRT", "STD",
    "DDT", "FBC", "DTR", "TOD", "FRD", "DEG", "RAD", "SIN", "COS", "TAN", "ASN",
    "ACS", "ATN", "LN", "LOG", "XPY", "TRN", "CONCAT", "DELETE", "FIND",
    "INSERT", "MID", "STOD", "STOR", "DTOS", "RTOS", "UPPER", "LOWER", "MAM",
    "MAS", "MAJ", "MAH", "MSO", "MSF", "MASD", "MASR", "MCD", "MRP", "MCCP",
    "MCS", "MCSD", "MCT", "MCTP", "MAPC", "MAAT", "MGS", "MGSD", "MGSR", "MGSP",
    "ALMD", "ALMA", "SFR", "SFP", "SATT", "COP")


class L5KLexer(RegexLexer):
    """Logix's ASCII export: the blocks (CONTROLLER ... END_CONTROLLER), their
    attributes in parentheses, tag values, and ladder rungs by instruction."""

    name = "L5K"
    aliases = ["l5k"]
    filenames = ["*.L5K", "*.l5k"]
    flags = re.MULTILINE

    tokens = {
        "root": [
            (r"\s+", Whitespace),
            (r"\(\*", Comment.Multiline, "comment"),
            (r"//.*?$", Comment.Single),
            (r'"(?:\$.|[^"$])*"', String.Double),
            (r"'(?:\$.|[^'$])*'", String.Single),
            (r"^(\s*)(IE_VER)(\s*)(:=)", bygroups(Whitespace, Comment.Preproc, Whitespace,
                                                 Operator)),
            (r"\b(?:RC|RUNG|N|RUNG_COMMENT)(?=:)", Keyword),
            (r"\b(?:END_)?(?:CONTROLLER|DATATYPE|MODULE|ADD_ON_INSTRUCTION_DEFINITION|"
             r"ADD_ON_INSTRUCTION|TAG|PROGRAM|ROUTINE|FBD_ROUTINE|SFC_ROUTINE|"
             r"ST_ROUTINE|TASK|CONFIG|PARAMETERS|LOCAL_TAGS|CONNECTION|TREND|"
             r"QUICK_WATCH|ENCODED_DATA|PRIMITIVE|SHEET|LOGIC|CHILD_PROGRAMS)\b",
             Keyword),
            (r"\b(?:COMMENT|ALIAS FOR|OF)\b", Keyword),
            (words(LADDER, prefix=r"\b", suffix=r"(?=\()"), Name.Builtin),
            (r"\b\d+#[0-9A-Fa-f_]+\b", Number.Hex),
            (r"\b-?\d+\.\d+(?:[eE][+-]?\d+)?\b", Number.Float),
            (r"\b-?\d+\b", Number.Integer),
            (r"\b(?:BOOL|SINT|INT|DINT|LINT|REAL|LREAL|STRING|TIMER|COUNTER|CONTROL|"
             r"MESSAGE|PID|MOTION_INSTRUCTION|AXIS_CIP_DRIVE|ALARM_DIGITAL|"
             r"ALARM_ANALOG)\b", Keyword.Type),
            (r"\b[A-Za-z_]\w*(?=\s*:=)", Name.Attribute),
            (r"\b[A-Za-z_][\w.:\[\]]*", Name),
            (r":=|[<>=]+|[-+*/]", Operator),
            (r"[;:,.()\[\]{}]", Punctuation),
        ],
        "comment": [
            (r"[^*]+", Comment.Multiline),
            (r"\*\)", Comment.Multiline, "#pop"),
            (r"\*", Comment.Multiline),
        ],
    }


OURS = {"iec-st": StructuredTextLexer, "l5k": L5KLexer}
_OUR_EXTENSIONS = {"st": "iec-st", "scl": "iec-st", "stx": "iec-st", "iecst": "iec-st",
                   "l5k": "l5k",
                   # Pygments' own answers that are wrong on a plant's machines:
                   # a .nc is a CNC program, not nesC, and the Logix and
                   # FactoryTalk exports are XML under their own names.
                   "nc": "gcode", "ngc": "gcode", "tap": "gcode", "cnc": "gcode",
                   "eia": "gcode", "l5x": "xml", "aml": "xml",
                   "xaml": "xml", "resx": "xml", "csproj": "xml", "vbproj": "xml",
                   "config": "xml"}

#: Extensions that are text with nothing to colour; Pygments has a lexer for
#: some of them (a "text" lexer that colours nothing) or guesses wrong.
PLAIN = {"txt", "log", "csv", "tsv", "dat", "out", "lst", "prn", ""}

#: What the language menu lists, in its order. Everything Pygments knows is
#: still found by file name; this is the list somebody picks from when the
#: name does not say.
MENU = (
    ("bat", "Batch"), ("c", "C"), ("cpp", "C++"), ("csharp", "C#"),
    ("cmake", "CMake"), ("css", "CSS"), ("diff", "Diff / patch"),
    ("docker", "Dockerfile"), ("gcode", "G-code"), ("go", "Go"), ("html", "HTML"),
    ("ini", "INI"), ("java", "Java"), ("javascript", "JavaScript"), ("json", "JSON"),
    ("kotlin", "Kotlin"), ("l5k", "L5K (Logix)"), ("lua", "Lua"), ("make", "Makefile"),
    ("markdown", "Markdown"), ("matlab", "MATLAB"), ("delphi", "Pascal / Delphi"),
    ("perl", "Perl"), ("php", "PHP"), ("powershell", "PowerShell"),
    ("python", "Python"), ("r", "R"), ("ruby", "Ruby"), ("rust", "Rust"),
    ("bash", "Shell"), ("sql", "SQL"), ("iec-st", "Structured Text"),
    ("swift", "Swift"), ("tex", "TeX"), ("toml", "TOML"),
    ("typescript", "TypeScript"), ("vb.net", "VB.NET"), ("vbscript", "VBScript"),
    ("xml", "XML"), ("yaml", "YAML"),
)


def _ext(path: str) -> str:
    base = ntpath.basename(path) if "\\" in path else posixpath.basename(path)
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def _base(path: str) -> str:
    return ntpath.basename(path) if "\\" in path else posixpath.basename(path)


def lexer(key: str):
    """A lexer for a language key, or None. Options that keep line numbers
    true: nothing stripped from either end, tabs left alone."""
    options = {"stripnl": False, "stripall": False, "ensurenl": False, "tabsize": 0}
    if key in OURS:
        return OURS[key](**options)
    try:
        return _lexers.get_lexer_by_name(key, **options)
    except ClassNotFound:
        return None


def detect(path: str, first_line: str = "") -> str:
    """The language key for a file, "" when it is plain text or unknown.

    By name first -- our two, then Pygments' table. A file with no extension
    gets one look at its first line, for a `#!` or an XML declaration;
    Pygments' content guesser is not used, because on plain text it answers
    something and colours a log as if it were a program.
    """
    ext = _ext(path)
    if ext in _OUR_EXTENSIONS:
        return _OUR_EXTENSIONS[ext]
    if ext in PLAIN and ext:
        return ""
    name = _base(path)
    if name and ext not in PLAIN:
        try:
            found = _lexers.get_lexer_for_filename(name)
        except ClassNotFound:
            found = None
        if found is not None and found.aliases and found.name not in ("Text only",):
            return found.aliases[0]
    if not ext:
        if name.lower() in ("makefile", "gnumakefile"):
            return "make"
        if name.lower() == "dockerfile":
            return "docker"
    line = first_line.lstrip("﻿").strip()
    if line.startswith("#!"):
        for word, key in (("python", "python"), ("pwsh", "powershell"),
                          ("powershell", "powershell"), ("bash", "bash"), ("sh", "bash"),
                          ("perl", "perl"), ("ruby", "ruby"), ("node", "javascript")):
            if word in line:
                return key
    if line.startswith("<?xml"):
        return "xml"
    return ""


def name_of(key: str) -> str:
    for known, label in MENU:
        if known == key:
            return label
    found = lexer(key)
    return found.name if found is not None else key


# ------------------------------------------------------------ the lexing

def category(ttype) -> int:
    """A Pygments token type to one of our dozen categories (0 is ink)."""
    while ttype is not Token and ttype is not None:
        found = _CATEGORY_OF.get(ttype)
        if found is not None:
            return found
        ttype = ttype.parent
    return 0


_CATEGORY_OF = {
    Comment.Preproc: _INDEX["preproc"],
    Comment.PreprocFile: _INDEX["preproc"],
    Comment: _INDEX["comment"],
    Keyword.Type: _INDEX["type"],
    Keyword.Constant: _INDEX["constant"],
    Keyword.Namespace: _INDEX["keyword"],
    Keyword: _INDEX["keyword"],
    Operator.Word: _INDEX["keyword"],
    Name.Function: _INDEX["function"],
    Name.Function.Magic: _INDEX["function"],
    Name.Class: _INDEX["type"],
    Name.Namespace: _INDEX["type"],
    Name.Builtin.Pseudo: _INDEX["constant"],
    Name.Builtin: _INDEX["builtin"],
    Name.Decorator: _INDEX["preproc"],
    Name.Constant: _INDEX["constant"],
    Name.Label: _INDEX["label"],
    Name.Tag: _INDEX["tag"],
    Name.Attribute: _INDEX["attribute"],
    Name.Entity: _INDEX["constant"],
    Name.Exception: _INDEX["type"],
    Name.Variable.Magic: _INDEX["constant"],
    String.Doc: _INDEX["comment"],
    String: _INDEX["string"],
    Number: _INDEX["number"],
    Token.Generic.Heading: _INDEX["keyword"],
    Token.Generic.Subheading: _INDEX["keyword"],
    Token.Generic.Deleted: _INDEX["tag"],
    Token.Generic.Inserted: _INDEX["string"],
    Token.Literal.Date: _INDEX["number"],
}

Spans = list[tuple[int, int, int]]


def highlight(lines: list[str], key: str) -> list[Spans] | None:
    """Per line, the coloured spans in display columns. None when there is
    no lexer, or the text is past `LIMIT`."""
    if not key or not lines:
        return None
    found = lexer(key)
    if found is None:
        return None
    shown = [line.expandtabs(TAB) for line in lines]
    if sum(len(line) + 1 for line in shown) > LIMIT:
        return None
    out: list[Spans] = [[] for _ in shown]
    row = col = 0
    last = len(shown) - 1
    for ttype, value in found.get_tokens("\n".join(shown)):
        cat = category(ttype)
        pieces = value.split("\n")
        for number, piece in enumerate(pieces):
            if number:
                row += 1
                col = 0
                if row > last:
                    return out
            if piece:
                stop = col + len(piece)
                if cat:
                    spans = out[row]
                    if spans and spans[-1][2] == cat and spans[-1][1] == col:
                        spans[-1] = (spans[-1][0], stop, cat)
                    else:
                        spans.append((col, stop, cat))
                col = stop
    return out


def size(lines: list[str]) -> int:
    return sum(len(line) + 1 for line in lines)


__all__ = ["CATEGORIES", "MENU", "detect", "highlight", "lexer", "name_of", "category",
           "Text"]
