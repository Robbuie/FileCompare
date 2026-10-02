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
    FileCompare.exe <left> <right> --wait         stay until closed (git difftool)
    FileCompare.exe <left> <right> --report out.html   no window: write a report and
                                              exit 0 same, 1 different, 2 failed
    FileCompare.exe x.fcsession --report out.html      the same, from a session
    FileCompare.exe --select-left <path>      Explorer's "Select left side"
    FileCompare.exe --with-left <path>        Explorer's "Compare to left side"

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
    #: Stay in this process and exit when the window closes, rather than
    #: handing over to a window already open: git's difftool and mergetool
    #: wait for the program they started. `--merge` implies it.
    wait: bool = False
    #: Explorer's verbs: remember a left side, or compare against it.
    select_left: str = ""
    with_left: str = ""
    #: 1.11: write a report here and exit, without a window (`app/batch.py`).
    report: str = ""
    error: str = ""

    @property
    def empty(self) -> bool:
        return not self.paths and not self.error and not self.select_left \
            and not self.with_left


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
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--select-left", default="")
    parser.add_argument("--with-left", default="")
    parser.add_argument("--report", default="")
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
        wait=args.wait or args.merge,
        output=resolve(args.output, cwd) if args.output else "",
        select_left=resolve(args.select_left, cwd) if args.select_left else "",
        with_left=resolve(args.with_left, cwd) if args.with_left else "",
        report=resolve(args.report, cwd) if args.report else "",
    )
    for side in args.readonly:
        request.readonly.update(("left", "right") if side == "both" else (side,))
    if request.merge:
        if len(request.paths) != 3:
            request.error = "--merge takes three files: mine, theirs and base"
    elif len(request.paths) > 2:
        request.error = f"Two paths to compare, not {len(request.paths)}"
    elif request.report and not (len(request.paths) == 2 or (
            len(request.paths) == 1 and request.paths[0].lower().endswith(".fcsession"))):
        request.error = "--report needs two paths to compare, or one session file"
    return request


def resolve(path: str, cwd: str) -> str:
    """A path made absolute against `cwd`, as strings only -- no disk."""
    path = path.strip().strip('"')
    if not path:
        return path
    if len(path) == 2 and path[1] == ":" and path[0].isalpha():
        # `D:` alone means "wherever D: was last", and joined to a name it
        # makes `D:name`, which File Manager rightly refuses as not a full
        # path. A drive given on its own is its root.
        return path + "\\"
    if sys.platform != "win32" and (path.startswith("/") or cwd.startswith("/")):
        # Off Windows -- the tests, and the preview tool -- a POSIX path stays
        # one. `ntpath` would turn its slashes round and it would not exist.
        return posixpath.normpath(posixpath.join(cwd, path) if cwd else path)
    if cwd and not ntpath.isabs(path) and not path.startswith("\\\\"):
        path = ntpath.join(cwd, path)
    if path.startswith("\\\\"):
        return "\\\\" + ntpath.normpath(path[2:])
    return ntpath.normpath(path) if ntpath.isabs(path) else path
