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

Pure Python: entries in, a tree of `Node`s out. The walking is `io/walk.py`,
the reading for a content compare is `io/walk.py` too, and the tests prove
everything here without a disk.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Iterable

#: Seconds two timestamps may differ by and still be the same moment.
TOLERANCE = 2.0

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
          tolerance: float = TOLERANCE) -> Node:
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
            if entry.is_dir:
                excluded.add(entry.rel.lower())
            return False
        return True

    for side, entries in (("left", left), ("right", right)):
        excluded.clear()
        # Parents before children, whatever order the walk produced.
        for entry in sorted(entries, key=lambda e: e.rel.lower().count("\\")):
            if not entry.rel or not kept(entry):
                continue
            node = node_for(entry.rel)
            setattr(node, side, entry)

    _judge(root, tolerance)
    _sort(root)
    if mask.include:
        _prune_empty(root)
    return root


def verdict(left: Entry | None, right: Entry | None, tolerance: float = TOLERANCE) -> str:
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
    if abs(left.mtime - right.mtime) <= tolerance:
        return SAME if left.size == right.size else DIFFERENT
    return NEWER_LEFT if left.mtime > right.mtime else NEWER_RIGHT


def _judge(node: Node, tolerance: float) -> None:
    """Verdicts bottom up. A folder differs if anything under it does, and
    says how many files that is."""
    for child in node.children:
        _judge(child, tolerance)
    own = verdict(node.left, node.right, tolerance) if node.rel else SAME
    if node.rel and not node.is_dir:
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
        return status in (SAME, CONTENT_SAME)
    return True


def counts(root: Node) -> dict[str, int]:
    totals: dict[str, int] = {}
    for node in root.walk():
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
        return f"No differences in {files:,} files{extra}"
    parts = []
    for key in (NEWER_LEFT, NEWER_RIGHT, ONLY_LEFT, ONLY_RIGHT, DIFFERENT, CONTENT_DIFF,
                CLASH, ERROR):
        if totals.get(key):
            parts.append(f"{totals[key]:,} {LABELS[key]}")
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
        if not node.pair:
            continue
        if node.status in (NEWER_LEFT, NEWER_RIGHT) and node.left.size == node.right.size:
            out.append(node)
        elif all_pairs and node.status == SAME:
            out.append(node)
    return out
