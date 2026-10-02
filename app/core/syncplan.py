"""What would make one side of a folder compare match the other (1.0).

The folder view already knows every difference. This turns a direction and a
choice into a list of actions -- copy this, remove that, leave this alone and
why -- which the preview shows with a box beside each, and which is then
handed to File Manager's queue as ordinary jobs (`io/handoff.py`). Nothing
here, and nothing in this application, copies or removes a file: File
Manager has one engine for that and a second one would be the thing its own
rules forbid.

Three kinds of plan:

  * **Update** -- copy what is only on the source side, and what is newer
    there. A file newer on the target is left alone and listed, and so is a
    pair with the same time and different contents: neither timestamp says
    which one is right. The copy runs under the queue's "newer only" rule, so
    a file that changed on the target after the walk is still not overwritten.
  * **Mirror** -- update, and remove what is only on the target, to the
    Recycle Bin. Only offered when both walks saw everything: a folder that
    could not be read on the source side would make everything under it look
    like something to delete on the other.
  * **Selected rows** -- copy exactly the rows somebody picked, one way,
    replacing what is there whatever its time; or remove the picked rows from
    one side. A folder picked means the files under it that differ.

Rules all three keep, the same as File Manager's sync:

  * **A folder on one side only is one action**, copied or removed whole --
    and only when everything under it was seen: nothing unreadable, no link
    or junction, nothing the name mask left out of the tree. Otherwise it is
    left alone, and the preview says which of the three.
  * **Links and junctions are never copied or removed**, and never walked.
  * **Nothing that could not be read is acted on.**
  * **A picked row whose folder is not on the target is left alone**: the
    queue copies into folders that exist, and the folder is the thing to pick.

Pure: nodes in, actions out, and the request as a dict. The tests prove it
without a disk.
"""

from __future__ import annotations

import ntpath
import posixpath
from dataclasses import dataclass, field
from typing import Iterable

from app.core import folders as F

TO_RIGHT = "to right"
TO_LEFT = "to left"

UPDATE = "update"
MIRROR = "mirror"
COPY = "copy"          # the selected rows, one way
REMOVE = "remove"      # the selected rows, from one side

# What an action does.
ACT_COPY = "copy"
ACT_REMOVE = "remove"
ACT_SKIP = "left alone"

# Why a copy (shown in the preview).
NEW = "only on the source"
NEWER = "newer on the source"
REPLACE = "replaces the target"
EXTRA = "only on the target"
PICKED = "picked"

# Why something is left alone.
TARGET_NEWER = "newer on the target"
UNSURE = "same time, different contents"
CLASH = "a folder on one side, a file on the other"
LINK = "a link or junction"
UNREAD = "could not be read"
# 1.4.1: a folder that cannot be taken whole, and a file whose folder is not
# there to put it in.
HOLDS_LINK = "holds a link or junction"
HOLDS_UNREAD = "holds something that could not be read"
HOLDS_HIDDEN = "holds files the name filter hides"
NO_FOLDER = "its folder is not on the target; copy the folder"


@dataclass(frozen=True)
class Action:
    act: str
    rel: str
    why: str
    is_dir: bool = False
    size: int = 0           # bytes a copy writes
    files: int = 1          # files inside a folder copied or removed whole
    source_mtime: float = 0.0
    target_mtime: float = 0.0


@dataclass
class Plan:
    direction: str
    mode: str
    actions: list[Action] = field(default_factory=list)
    #: Set when removals were asked for and are not offered, saying why.
    no_removals: str = ""

    def of(self, act: str) -> list[Action]:
        return [a for a in self.actions if a.act == act]

    @property
    def copies(self) -> list[Action]:
        return self.of(ACT_COPY)

    @property
    def removals(self) -> list[Action]:
        return self.of(ACT_REMOVE)

    @property
    def skipped(self) -> list[Action]:
        return self.of(ACT_SKIP)

    @property
    def empty(self) -> bool:
        return not self.copies and not self.removals

    @property
    def conflict(self) -> str:
        """The queue's rule for a name already taken. An update never lets an
        older file replace a newer one, even one that changed after the walk;
        picked rows replace whatever is there, because somebody picked them."""
        return "overwrite" if self.mode == COPY else "newer"


def _sides(node: F.Node, direction: str) -> tuple[F.Entry | None, F.Entry | None]:
    return (node.left, node.right) if direction == TO_RIGHT else (node.right, node.left)


def _files_under(node: F.Node, direction: str, *, source: bool = True) -> tuple[int, int]:
    """(files, bytes) on one side under a folder, for a whole-folder action."""
    files = size = 0
    for child in node.walk():
        entry = _sides(child, direction)[0 if source else 1]
        if entry is not None and not entry.is_dir:
            files += 1
            size += entry.size
    return files, size


def _unread(node: F.Node) -> bool:
    return bool((node.left and node.left.error) or (node.right and node.right.error))


def _linked(node: F.Node) -> bool:
    return bool((node.left and node.left.is_link) or (node.right and node.right.is_link))


def _whole_refusal(node: F.Node, direction: str, *, source: bool) -> str:
    """Why a folder cannot be copied or removed whole, or "".

    Everything under it goes with it, so everything under it has to have been
    seen: nothing unreadable (its contents are unknown), no link or junction
    (the engine could walk through it, or remove what it points at), and
    nothing the name mask left out of the tree (it would go too, unseen).
    """
    side = (0 if direction == TO_RIGHT else 1) if source else (1 if direction == TO_RIGHT else 0)
    if node.masked[side]:
        return HOLDS_HIDDEN
    for child in node.walk():
        if _unread(child):
            return HOLDS_UNREAD
        if _linked(child):
            return HOLDS_LINK
        if child.masked[side]:
            return HOLDS_HIDDEN
    return ""


def _target_folder_missing(node: F.Node, direction: str) -> bool:
    """Whether a folder above `node` is missing on the target side, so a copy
    of `node` alone would have nowhere to land. The queue does not make the
    folders a copy goes into; a whole folder carries its own."""
    up = node.parent
    while up is not None and up.rel:
        _source, target = _sides(up, direction)
        if target is None:
            return True
        up = up.parent
    return False


def complete(root: F.Node) -> bool:
    """Whether both walks saw everything: no folder or file that could not be
    read anywhere in the tree."""
    return not any(_unread(node) for node in root.walk())


def _visit(node: F.Node, direction: str, *, picked: bool, removals: bool,
           tolerance: float, out: list[Action]) -> None:
    source, target = _sides(node, direction)
    if _unread(node):
        out.append(Action(ACT_SKIP, node.rel, UNREAD, is_dir=node.is_dir))
        return
    if _linked(node):
        out.append(Action(ACT_SKIP, node.rel, LINK, is_dir=bool(
            (source or target) and (source or target).is_dir)))
        return
    if source is not None and target is not None and source.is_dir != target.is_dir:
        out.append(Action(ACT_SKIP, node.rel, CLASH))
        return
    if source is not None and target is None:
        if picked and _target_folder_missing(node, direction):
            out.append(Action(ACT_SKIP, node.rel, NO_FOLDER, is_dir=source.is_dir))
            return
        if source.is_dir:
            refused = _whole_refusal(node, direction, source=True)
            if refused:
                out.append(Action(ACT_SKIP, node.rel, refused, is_dir=True))
                return
            files, size = _files_under(node, direction)
            out.append(Action(ACT_COPY, node.rel, NEW, is_dir=True, size=size,
                              files=files, source_mtime=source.mtime))
        else:
            out.append(Action(ACT_COPY, node.rel, NEW, size=source.size,
                              source_mtime=source.mtime))
        return
    if source is None and target is not None:
        if removals:
            refused = _whole_refusal(node, direction, source=False) if target.is_dir else ""
            if refused:
                out.append(Action(ACT_SKIP, node.rel, refused, is_dir=True))
                return
            files, _size = _files_under(node, direction, source=False)
            out.append(Action(ACT_REMOVE, node.rel, EXTRA, is_dir=target.is_dir,
                              files=files if target.is_dir else 1,
                              target_mtime=target.mtime))
        return
    if source is None:
        return
    if source.is_dir:
        for child in node.children:
            _visit(child, direction, picked=picked, removals=removals,
                   tolerance=tolerance, out=out)
        return
    # A file on both sides.
    if node.status in (F.SAME, F.CONTENT_SAME, F.HOUR_APART):
        # An hour apart is a clock change, not an edit (1.8): copying it
        # would only move the clock, so it is left alone like a same file.
        return
    if picked:
        if _target_folder_missing(node, direction):
            out.append(Action(ACT_SKIP, node.rel, NO_FOLDER))
            return
        out.append(Action(ACT_COPY, node.rel, REPLACE, size=source.size,
                          source_mtime=source.mtime, target_mtime=target.mtime))
        return
    if abs(source.mtime - target.mtime) <= tolerance:
        # Same moment: SAME was handled above, so the sizes or the bytes
        # differ, and no clock says which side is right.
        out.append(Action(ACT_SKIP, node.rel, UNSURE, source_mtime=source.mtime,
                          target_mtime=target.mtime))
    elif source.mtime > target.mtime:
        out.append(Action(ACT_COPY, node.rel, NEWER, size=source.size,
                          source_mtime=source.mtime, target_mtime=target.mtime))
    else:
        out.append(Action(ACT_SKIP, node.rel, TARGET_NEWER, source_mtime=source.mtime,
                          target_mtime=target.mtime))


def _tops(nodes: Iterable[F.Node]) -> list[F.Node]:
    """The picked nodes without any whose folder was picked as well, so a
    folder and a file inside it are not acted on twice."""
    chosen = list({id(node): node for node in nodes}.values())
    ids = {id(node) for node in chosen}
    out = []
    for node in chosen:
        up = node.parent
        while up is not None and id(up) not in ids:
            up = up.parent
        if up is None and node.rel:
            out.append(node)
    return out


_ORDER = {ACT_COPY: 0, ACT_REMOVE: 1, ACT_SKIP: 2}


def plan(root: F.Node, direction: str, mode: str, *,
         nodes: Iterable[F.Node] | None = None,
         tolerance: float = F.TOLERANCE) -> Plan:
    """The actions for `mode` in `direction`. `nodes` limits it to the picked
    rows (and, for update and mirror, what is under them)."""
    result = Plan(direction=direction, mode=mode)
    tops = _tops(nodes) if nodes is not None else list(root.children)
    if mode == REMOVE:
        # Remove from the side the direction points at -- "to right" removes
        # from the right -- so the one control means the same thing everywhere.
        for node in tops:
            _source, target = _sides(node, direction)
            if target is None:
                continue
            refused = _whole_refusal(node, direction, source=False) if target.is_dir else ""
            if _unread(node):
                result.actions.append(Action(ACT_SKIP, node.rel, UNREAD, is_dir=target.is_dir))
            elif _linked(node):
                result.actions.append(Action(ACT_SKIP, node.rel, LINK, is_dir=target.is_dir))
            elif refused:
                result.actions.append(Action(ACT_SKIP, node.rel, refused, is_dir=True))
            else:
                files, _size = _files_under(node, direction, source=False)
                result.actions.append(Action(ACT_REMOVE, node.rel, PICKED,
                                             is_dir=target.is_dir,
                                             files=files if target.is_dir else 1,
                                             target_mtime=target.mtime))
    else:
        removals = mode == MIRROR
        if removals and not complete(root):
            removals = False
            result.no_removals = ("Mirror is not offered: something could not be read, "
                                  "and a file the walk did not see would look like one "
                                  "to remove.")
        for node in tops:
            _visit(node, direction, picked=mode == COPY, removals=removals,
                   tolerance=tolerance, out=result.actions)
    result.actions.sort(key=lambda a: (_ORDER[a.act], a.rel.lower()))
    return result


# ------------------------------------------------------------- the request

def _join(root: str, rel: str) -> str:
    if len(root) == 2 and root[1] == ":":
        root += "\\"            # `D:` alone is drive-relative; its root is meant
    if not rel:
        return root
    windows = "\\" in root or root[1:2] == ":"
    if windows:
        return ntpath.join(root, rel)
    return posixpath.join(root, rel.replace("\\", "/"))


def _parent(root: str, rel: str) -> str:
    folder, _sep, _name = rel.rpartition("\\")
    return _join(root, folder) if folder else root


def request(plan_: Plan, chosen: Iterable[Action], left_root: str, right_root: str, *,
            title: str = "") -> dict:
    """The jobs File Manager's queue is asked to run, as `core/handoff.py`
    there reads them: at most one copy job and one recycle job."""
    left_root, right_root = (r + "\\" if len(r) == 2 and r[1] == ":" else r
                             for r in (left_root, right_root))
    source_root, target_root = ((left_root, right_root) if plan_.direction == TO_RIGHT
                                else (right_root, left_root))
    chosen = list(chosen)
    copies = [a for a in chosen if a.act == ACT_COPY]
    removals = [a for a in chosen if a.act == ACT_REMOVE]
    jobs: list[dict] = []
    if copies:
        jobs.append({
            "kind": "copy",
            "sources": [_join(source_root, a.rel) for a in copies],
            "destination": target_root,
            "into": [_parent(target_root, a.rel) for a in copies],
            "conflict": plan_.conflict,
        })
    if removals:
        jobs.append({"kind": "recycle",
                     "sources": [_join(target_root, a.rel) for a in removals]})
    # The two roots let File Manager refuse anything outside them: every copy
    # from inside the source, every copy and removal inside the target.
    return {"version": 1, "from": "File Compare", "title": title,
            "source_root": source_root, "target_root": target_root, "jobs": jobs}


def refusal(left_root: str, right_root: str) -> str:
    """Why these two folders cannot be synced at all, or "". By their names
    only; File Manager checks again at the moment it copies."""
    a = left_root.replace("/", "\\").rstrip("\\").lower()
    b = right_root.replace("/", "\\").rstrip("\\").lower()
    if not a or not b:
        return "Both sides need a folder."
    if a == b:
        return "Both sides are the same folder."
    if b.startswith(a + "\\") or a.startswith(b + "\\"):
        return "One folder is inside the other."
    return ""


def on_a_share(path: str) -> bool:
    """A UNC path, by its name. A mapped letter needs a look at the session's
    connections, which `io/handoff.drive_is_remote` makes off the UI thread."""
    return path.startswith("\\\\")
