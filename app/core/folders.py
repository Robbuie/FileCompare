"""Folder compare: two trees, merged into one, every entry given a verdict.

File Manager's `core/compare.py` answers "which of these differ" for the one
folder each pane shows, from the listing it already has, and deliberately does
not walk into subfolders or open a file. This is the other half: both trees
all the way down, and -- when asked -- the bytes of every pair whose size and
time cannot settle it. The verdicts and the two tolerances are File Manager's,
so the two applications never disagree about the same pair of files:

  * **Names match case-insensitively**, because Windows does.
  * **Timestamps match within two seconds**, because FAT and SMB round, and an
    exact comparison calls half the files on a share newer every time.

One thing here File Manager does not do (1.8), behind a switch that is on by
default: a pair the same size whose times are **exactly an hour apart**, to
within the same two seconds, is `HOUR_APART` -- shown, not counted. That is a
clock change, not an edit: a FAT or exFAT drive, or a share on a server that
stores local time, moves every timestamp by an hour when daylight saving
starts or ends, and without this every file copied before the change reads
as newer on one side. A content compare still reads such a pair and says
whether the bytes agree.

Pure Python: entries in, a tree of `Node`s out. The walking is `io/walk.py`,
the reading for a content compare is `io/walk.py` too, and the tests prove
everything here without a disk.
"""

from __future__ import annotations

import fnmatch
import ntpath
import posixpath
from dataclasses import dataclass, field
from typing import Iterable

#: Seconds two timestamps may differ by and still be the same moment.
TOLERANCE = 2.0

#: A daylight saving change, in seconds.
HOUR = 3600.0

# Verdicts. A file pair gets one from size and time, and may get a better one
# from its content later.
SAME = "same"                 # same size, same time
NEWER_LEFT = "newer left"     # both sides; the left one written later
NEWER_RIGHT = "newer right"   # both sides; the right one written later
DIFFERENT = "different"       # same time, different size: one of them is wrong
ONLY_LEFT = "only left"
ONLY_RIGHT = "only right"
CLASH = "clash"               # a folder on one side, a file on the other
CONTENT_SAME = "content same"  # times differ, bytes do not
HOUR_APART = "hour apart"     # same size, times exactly an hour apart (1.8)
CONTENT_DIFF = "content differs"
ERROR = "error"               # a side could not be read

#: What counts as a difference. `CONTENT_SAME` does not: the files are the
#: same, and only the clock disagrees -- shown, but not counted.
DIFFERENT_KINDS = frozenset({NEWER_LEFT, NEWER_RIGHT, DIFFERENT, ONLY_LEFT, ONLY_RIGHT,
                             CLASH, CONTENT_DIFF, ERROR})

LABELS = {
    SAME: "same",
    NEWER_LEFT: "newer on the left",
    NEWER_RIGHT: "newer on the right",
    DIFFERENT: "same time, different size",
    ONLY_LEFT: "only on the left",
    ONLY_RIGHT: "only on the right",
    CLASH: "a folder on one side, a file on the other",
    CONTENT_SAME: "same content, different time",
    HOUR_APART: "same size, an hour apart",
    CONTENT_DIFF: "content differs",
    ERROR: "could not be read",
}


@dataclass(frozen=True)
class Entry:
    """One thing a walk found. Plain data: it crosses a thread boundary."""

    rel: str            # path from the walked root, with backslashes
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    error: str = ""     # a folder that could not be listed
    #: 1.0: a junction or symbolic link. Listed, never walked -- and never
    #: copied or removed by a sync, which would act on what it points at.
    is_link: bool = False
    #: 1.9: for a member of a zip, the zip's own `rel`; its CRC-32 from the
    #: zip's directory, which settles its content without reading it.
    archive: str = ""
    crc: int = -1


@dataclass
class Node:
    name: str
    rel: str
    left: Entry | None = None
    right: Entry | None = None
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)
    status: str = SAME
    #: For folders: how many files below differ, and how many there are.
    differing: int = 0
    files: int = 0
    #: 1.4.1: per side, whether the name mask left something out somewhere
    #: under this folder. A sync never copies or removes such a folder whole:
    #: what the mask hid would go with it.
    masked: tuple[bool, bool] = (False, False)

    @property
    def is_dir(self) -> bool:
        side = self.left or self.right
        return bool(side and side.is_dir) and not (self.left and self.right
                                                   and self.left.is_dir != self.right.is_dir)

    @property
    def differs(self) -> bool:
        return self.status in DIFFERENT_KINDS

    @property
    def pair(self) -> bool:
        """A file on both sides: something a content compare can look at."""
        return (self.left is not None and self.right is not None
                and not self.left.is_dir and not self.right.is_dir)

    @property
    def member(self) -> bool:
        """Inside a zip (1.9): shown and compared, never read as a file on
        disk, synced, or counted with the folder's own files."""
        side = self.left or self.right
        return bool(side and side.archive)

    def walk(self) -> Iterable["Node"]:
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))


# ------------------------------------------------------------------ masks

@dataclass(frozen=True)
class Mask:
    """Which names take part: `*.L5X;*.ini` includes, `-.git;-*.bak` excludes.

    Includes apply to files only -- a folder has to be walked to find the
    files inside it that match. Excludes apply to both, so `-.git` keeps a
    whole repository's internals out. Matching ignores case, as Windows does.
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Mask":
        include: list[str] = []
        exclude: list[str] = []
        for part in text.replace(",", ";").split(";"):
            part = part.strip()
            if not part:
                continue
            if part.startswith("-") or part.startswith("!"):
                if part[1:].strip():
                    exclude.append(part[1:].strip().lower())
            else:
                include.append(part.lower())
        return cls(tuple(include), tuple(exclude))

    def text(self) -> str:
        return ";".join(list(self.include) + ["-" + e for e in self.exclude])

    def keeps(self, name: str, is_dir: bool) -> bool:
        lowered = name.lower()
        if any(fnmatch.fnmatchcase(lowered, pattern) for pattern in self.exclude):
            return False
        if is_dir or not self.include:
            return True
        return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in self.include)


# ------------------------------------------------------------------ the tree

def build(left: Iterable[Entry], right: Iterable[Entry], *, mask: Mask | None = None,
          tolerance: float = TOLERANCE, hour: bool = False) -> Node:
    """Merge two walks into one tree and give every node its verdict."""
    mask = mask or Mask()
    root = Node(name="", rel="")
    index: dict[str, Node] = {"": root}

    def node_for(rel: str) -> Node:
        key = rel.lower()
        found = index.get(key)
        if found is not None:
            return found
        parent_rel, _, name = rel.rpartition("\\")
        parent = node_for(parent_rel)
        found = Node(name=name, rel=rel, parent=parent)
        parent.children.append(found)
        index[key] = found
        return found

    excluded: set[str] = set()

    def kept(entry: Entry) -> bool:
        parent_rel, _, name = entry.rel.rpartition("\\")
        if parent_rel.lower() in excluded:
            excluded.add(entry.rel.lower())
            return False
        if not mask.keeps(name, entry.is_dir):
            # A file too: a zip left out takes its members with it (1.9).
            excluded.add(entry.rel.lower())
            return False
        return True

    hidden: dict[str, set[str]] = {"left": set(), "right": set()}
    for side, entries in (("left", left), ("right", right)):
        excluded.clear()
        # Parents before children, whatever order the walk produced.
        for entry in sorted(entries, key=lambda e: e.rel.lower().count("\\")):
            if not entry.rel:
                continue
            if not kept(entry):
                parent_rel = entry.rel.rpartition("\\")[0]
                # A member the mask hid is not on disk; it cannot make the
                # folder unsafe to sync whole.
                if parent_rel and not entry.archive:
                    hidden[side].add(parent_rel.lower())
                continue
            node = node_for(entry.rel)
            setattr(node, side, entry)
    for number, side in enumerate(("left", "right")):
        for rel in hidden[side]:
            # Every folder above the one that held the hidden entry, as far as
            # the tree has it: a folder the mask left out whole is not there.
            parts = rel.split("\\")
            for depth in range(len(parts), 0, -1):
                found = index.get("\\".join(parts[:depth]))
                if found is not None:
                    marks = list(found.masked)
                    marks[number] = True
                    found.masked = (marks[0], marks[1])

    _judge(root, tolerance, hour)
    _sort(root)
    if mask.include:
        _prune_empty(root)
    return root


def verdict(left: Entry | None, right: Entry | None, tolerance: float = TOLERANCE,
            hour: bool = False) -> str:
    if left is None and right is None:
        return SAME
    if (left and left.error) or (right and right.error):
        return ERROR
    if left is None:
        return ONLY_RIGHT
    if right is None:
        return ONLY_LEFT
    if left.is_dir != right.is_dir:
        return CLASH
    if left.is_dir:
        return SAME
    if left.archive and right.archive:
        # Two members of zips: the directory's size and CRC say whether the
        # bytes agree, so the clock only decides which "same" it is.
        if left.size != right.size or left.crc != right.crc:
            return CONTENT_DIFF
        return SAME if abs(left.mtime - right.mtime) <= tolerance else CONTENT_SAME
    apart = abs(left.mtime - right.mtime)
    if apart <= tolerance:
        return SAME if left.size == right.size else DIFFERENT
    if hour and left.size == right.size and abs(apart - HOUR) <= tolerance:
        return HOUR_APART
    return NEWER_LEFT if left.mtime > right.mtime else NEWER_RIGHT


def _judge(node: Node, tolerance: float, hour: bool = False) -> None:
    """Verdicts bottom up. A folder differs if anything under it does, and
    says how many files that is."""
    for child in node.children:
        _judge(child, tolerance, hour)
    own = verdict(node.left, node.right, tolerance, hour) if node.rel else SAME
    if node.rel and not node.is_dir:
        # A zip's members (1.9) were judged above for showing under it; the
        # zip itself is still one file with its own verdict, so a folder
        # counts it once and not once per member.
        node.status = own
        node.files = 1
        node.differing = 1 if own in DIFFERENT_KINDS else 0
        return
    node.files = sum(child.files for child in node.children)
    node.differing = sum(child.differing for child in node.children)
    if own in (ONLY_LEFT, ONLY_RIGHT, CLASH, ERROR):
        node.status = own
        if own != ERROR:
            node.differing = max(node.differing, 1)
    else:
        node.status = DIFFERENT if node.differing else SAME


def rejudge(node: Node) -> None:
    """Folders' verdicts again after some files' changed (a content compare).
    Walks up from `node`, which is cheaper than the whole tree each time."""
    current = node.parent
    while current is not None:
        current.differing = sum(child.differing for child in current.children)
        if current.rel and current.status in (ONLY_LEFT, ONLY_RIGHT, CLASH, ERROR):
            pass
        else:
            current.status = DIFFERENT if current.differing else SAME
        current = current.parent


def settle(node: Node, same_bytes: bool | None, error: str = "") -> None:
    """Record what a content compare found for one file pair."""
    if error:
        node.status = ERROR
    elif same_bytes is None:
        return
    elif same_bytes:
        node.status = SAME if node.status == SAME else CONTENT_SAME
    else:
        node.status = CONTENT_DIFF
    node.differing = 1 if node.status in DIFFERENT_KINDS else 0
    rejudge(node)


def _sort(node: Node) -> None:
    node.children.sort(key=lambda n: (not n.is_dir, n.name.lower()))
    for child in node.children:
        _sort(child)


def _prune_empty(node: Node) -> bool:
    """With an include mask, a folder with nothing matching under it is noise."""
    node.children = [c for c in node.children if not c.is_dir or _prune_empty(c)]
    return bool(node.children)


# ------------------------------------------------------------------ viewing

#: The show filter's settings.
SHOW_ALL = "all"
SHOW_DIFFERENT = "different"
SHOW_LEFT = "left"        # only on the left, or newer there
SHOW_RIGHT = "right"
SHOW_SAME = "same"

SHOWS = (SHOW_ALL, SHOW_DIFFERENT, SHOW_LEFT, SHOW_RIGHT, SHOW_SAME)


def shown(node: Node, show: str) -> bool:
    """Whether a node appears under the show filter. A folder appears when
    anything under it does, so a difference is never hidden by its folder."""
    if node.is_dir and node.children:
        return any(shown(child, show) for child in node.children) or (
            show in (SHOW_ALL, SHOW_DIFFERENT) and node.status in (ONLY_LEFT, ONLY_RIGHT, CLASH))
    status = node.status
    if show == SHOW_ALL:
        return True
    if show == SHOW_DIFFERENT:
        return status in DIFFERENT_KINDS
    if show == SHOW_LEFT:
        return status in (ONLY_LEFT, NEWER_LEFT)
    if show == SHOW_RIGHT:
        return status in (ONLY_RIGHT, NEWER_RIGHT)
    if show == SHOW_SAME:
        return status in (SAME, CONTENT_SAME, HOUR_APART)
    return True


def counts(root: Node) -> dict[str, int]:
    totals: dict[str, int] = {}
    for node in root.walk():
        if node.member:
            continue
        if node.is_dir:
            if node.status in (ONLY_LEFT, ONLY_RIGHT) and not node.children:
                totals[node.status] = totals.get(node.status, 0) + 1
            continue
        totals[node.status] = totals.get(node.status, 0) + 1
    return totals


def summary(root: Node) -> str:
    totals = counts(root)
    files = sum(totals.values())
    differing = sum(n for k, n in totals.items() if k in DIFFERENT_KINDS)
    if not files:
        return "Both folders are empty"
    if not differing:
        extra = ""
        if totals.get(CONTENT_SAME):
            extra = f"  ·  {totals[CONTENT_SAME]:,} with different times"
        if totals.get(HOUR_APART):
            extra += f"  ·  {totals[HOUR_APART]:,} an hour apart (clock change)"
        return f"No differences in {files:,} files{extra}"
    parts = []
    for key in (NEWER_LEFT, NEWER_RIGHT, ONLY_LEFT, ONLY_RIGHT, DIFFERENT, CONTENT_DIFF,
                CLASH, ERROR):
        if totals.get(key):
            parts.append(f"{totals[key]:,} {LABELS[key]}")
    if totals.get(HOUR_APART):
        parts.append(f"{totals[HOUR_APART]:,} an hour apart, not counted")
    return f"{differing:,} of {files:,} differ  ·  " + "  ·  ".join(parts)


def content_candidates(root: Node, *, all_pairs: bool = False) -> list[Node]:
    """The file pairs a content compare should read.

    By default the ones size and time cannot settle: same size, different
    time -- a copy whose timestamp moved, or an edit that kept the length.
    Different sizes are different files and need no reading; same size and
    time are taken as the same, as File Manager takes them. `all_pairs` reads
    those too, for when "probably the same" is not good enough.
    """
    out = []
    for node in root.walk():
        if not node.pair or node.member:
            continue
        if node.status in (NEWER_LEFT, NEWER_RIGHT, HOUR_APART) \
                and node.left.size == node.right.size:
            out.append(node)
        elif all_pairs and node.status == SAME:
            out.append(node)
    return out


def show_counts(root: Node) -> dict[str, int]:
    """How many files each show filter's button stands for (1.15), so the
    buttons double as the summary: "Differences 132", "Same 4,920"."""
    totals = counts(root)
    differing = sum(n for k, n in totals.items() if k in DIFFERENT_KINDS)
    return {
        SHOW_ALL: sum(totals.values()),
        SHOW_DIFFERENT: differing,
        SHOW_LEFT: totals.get(ONLY_LEFT, 0) + totals.get(NEWER_LEFT, 0),
        SHOW_RIGHT: totals.get(ONLY_RIGHT, 0) + totals.get(NEWER_RIGHT, 0),
        SHOW_SAME: totals.get(SAME, 0) + totals.get(CONTENT_SAME, 0) + totals.get(HOUR_APART, 0),
    }


# ------------------------------------------------------------------ paths

def _flavour(path: str):
    """`ntpath` for anything Windows-shaped, `posixpath` for a POSIX path --
    the tests and the preview tool run off Windows, as in `cli.resolve`."""
    return posixpath if path.startswith("/") else ntpath


def tidy(path: str) -> str:
    """A folder path as typed or pasted, made the shape the rest expects:
    quotes and spaces off the ends, no trailing separator except on a root
    (`C:\\`, `\\\\server\\share\\`), a bare `D:` as its root. Strings only."""
    path = path.strip().strip('"').strip()
    if not path:
        return ""
    flavour = _flavour(path)
    if flavour is ntpath:
        path = path.replace("/", "\\")
        if len(path) == 2 and path[1] == ":" and path[0].isalpha():
            return path + "\\"
        if path.startswith("\\\\"):
            path = "\\\\" + ntpath.normpath(path[2:])
        elif ntpath.isabs(path):
            path = ntpath.normpath(path)
        drive, rest = ntpath.splitdrive(path)
        if rest in ("", "\\"):
            return drive + "\\"
        return path.rstrip("\\")
    path = posixpath.normpath(path)
    return path


def same_path(a: str, b: str) -> bool:
    """Whether two tidied paths name the same folder, ignoring case on Windows."""
    a, b = tidy(a), tidy(b)
    if _flavour(a) is ntpath:
        return a.lower() == b.lower()
    return a == b


def ancestors(path: str) -> list[str]:
    """The folders above `path`, nearest first, up to and including its root:
    `S:\\Jobs\\1234\\PLC` gives `S:\\Jobs\\1234`, `S:\\Jobs`, `S:\\`. What the
    Up button's menu lists (1.15). Strings only."""
    out: list[str] = []
    path = tidy(path)
    flavour = _flavour(path)
    while path:
        up = tidy(flavour.dirname(path))
        if not up or same_path(up, path):
            break
        out.append(up)
        path = up
    return out


def rebased(rels, prefix: str) -> set[str]:
    """Folder rels, lowercased, as they read from a folder `prefix` below the
    old root: what stays open in the tree when "Compare these folders" moves
    both sides down into one (1.15). Rels outside it are dropped."""
    prefix = prefix.lower().strip("\\")
    if not prefix:
        return {r.lower() for r in rels}
    head = prefix + "\\"
    return {r.lower()[len(head):] for r in rels if r.lower().startswith(head)}
