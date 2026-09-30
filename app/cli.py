"""The command line, which is the contract with File Manager.

Shaped like Beyond Compare's and WinMerge's on purpose: File Manager's
`compare` and `compare-files` command rows already pass `%C` -- two full paths
-- to whichever of those tools is installed, and this application takes the
same arguments, so putting it first in those rows is a change to the table and
not to code.

    FileCompare.exe <left> <right>
    FileCompare.exe <left> <right> --left-title T --right-title T
    FileCompare.exe <left> <right> --readonly left|right|both
    FileCompare.exe <left> <right> --mode text
    FileCompare.exe --merge <mine> <theirs> <base> -o <output>

Parsing is pure: it turns a list of strings into a `Request` and never looks
at the disk. Whether a path is a file or a folder is decided later, off the
UI thread (`app/io/kind.py`). A malformed command line is a `Request` with an
`error`, which the window shows -- a tool launched from another program has no
console to print to.
"""

from __future__ import annotations

import argparse
import ntpath
import posixpath
import sys
from dataclasses import dataclass, field

MODES = ("auto", "text", "folder", "hex", "image", "table")


@dataclass
class Request:
    paths: list[str] = field(default_factory=list)
    left_title: str = ""
    right_title: str = ""
    readonly: set[str] = field(default_factory=set)
    mode: str = "auto"
    merge: bool = False
    output: str = ""
    error: str = ""

    @property
    def empty(self) -> bool:
        return not self.paths and not self.error


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ValueError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="FileCompare", add_help=False)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--left-title", default="")
    parser.add_argument("--right-title", default="")
    parser.add_argument("--readonly", choices=("left", "right", "both"), action="append",
                        default=[])
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("-o", "--output", default="")
    return parser


def parse(argv: list[str], cwd: str = "") -> Request:
    """`argv` without the program name. `cwd` resolves relative paths --
    passed in rather than read, because a second instance hands its arguments
    to the first, and the first has a different working directory."""
    try:
        args = _parser().parse_args(argv)
    except ValueError as exc:
        return Request(error=f"Could not read the command line: {exc}")
    request = Request(
        paths=[resolve(p, cwd) for p in args.paths],
        left_title=args.left_title,
        right_title=args.right_title,
        mode=args.mode,
        merge=args.merge,
        output=resolve(args.output, cwd) if args.output else "",
    )
    for side in args.readonly:
        request.readonly.update(("left", "right") if side == "both" else (side,))
    if request.merge:
        if len(request.paths) != 3:
            request.error = "--merge takes three files: mine, theirs and base"
    elif len(request.paths) > 2:
        request.error = f"Two paths to compare, not {len(request.paths)}"
    return request


def resolve(path: str, cwd: str) -> str:
    """A path made absolute against `cwd`, as strings only -- no disk."""
    path = path.strip().strip('"')
    if not path:
        return path
    if sys.platform != "win32" and (path.startswith("/") or cwd.startswith("/")):
        # Off Windows -- the tests, and the preview tool -- a POSIX path stays
        # one. `ntpath` would turn its slashes round and it would not exist.
        return posixpath.normpath(posixpath.join(cwd, path) if cwd else path)
    if cwd and not ntpath.isabs(path) and not path.startswith("\\\\"):
        path = ntpath.join(cwd, path)
    if path.startswith("\\\\"):
        return "\\\\" + ntpath.normpath(path[2:])
    return ntpath.normpath(path) if ntpath.isabs(path) else path
