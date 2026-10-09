"""The sync list (1.20): one row per file, with what would happen to it.

Total and Double Commander's Synchronize Directories in this application's
terms. Every row of the folder tree gets a category (only on the left, newer
on the left, different, the same, newer on the right, only on the right), a
result in words, and an action: copy right, copy left, or leave it. The
default action is what an update in each direction would do
(`core/syncplan.py`, so its rules hold -- nothing unread, no links, whole
folders only when everything under them was seen); a click changes it.

Running the list asks `syncplan` again for each direction, with exactly the
rows chosen: those left at their default as an update (a file that changed
on the target after the walk is still not overwritten), those turned round by
hand as picked copies (they replace what is there, because somebody chose
that). Each becomes one request for File Manager's queue, as the sync dialog
sends. Nothing here removes a file: the list copies; Mirror stays in Sync.

Pure: nodes in, decisions and requests out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core import folders as F
from app.core import syncplan as S

RIGHT = "right"
LEFT = "left"
SKIP = "skip"

#: Categories, in the toolbar's order.
ONLY_LEFT = "only left"
LEFT_NEWER = "left newer"
DIFFERENT = "different"
SAME = "same"
RIGHT_NEWER = "right newer"
ONLY_RIGHT = "only right"
CATEGORIES = (ONLY_LEFT, LEFT_NEWER, DIFFERENT, SAME, RIGHT_NEWER, ONLY_RIGHT)
#: What the list shows when it first opens: everything but the same files.
DEFAULT_SHOWN = frozenset(CATEGORIES) - {SAME}


def category(node: F.Node) -> str:
    status = node.status
    if status == F.ONLY_LEFT:
        return ONLY_LEFT
    if status == F.ONLY_RIGHT:
        return ONLY_RIGHT
    if status == F.NEWER_LEFT:
        return LEFT_NEWER
    if status == F.NEWER_RIGHT:
        return RIGHT_NEWER
    if status in (F.SAME, F.CONTENT_SAME, F.HOUR_APART):
        return SAME
    return DIFFERENT


def result(node: F.Node) -> str:
    """What the row's two sides are, in words."""
    status = node.status
    if node.is_dir and status not in (F.ONLY_LEFT, F.ONLY_RIGHT):
        if node.differing:
            return f"{node.differing:,} file{'s' if node.differing != 1 else ''} differ"
        return "Same"
    folder = "Folder only" if node.is_dir else "Only"
    words = {
        F.ONLY_LEFT: f"{folder} on the left",
        F.ONLY_RIGHT: f"{folder} on the right",
        F.NEWER_LEFT: "Left is newer",
        F.NEWER_RIGHT: "Right is newer",
        F.SAME: "Same",
        F.CONTENT_SAME: "Same contents, different times",
        F.HOUR_APART: "Same size, an hour apart",
        F.DIFFERENT: "Same time, different size",
        F.CONTENT_DIFF: "Contents differ",
        F.CLASH: "A folder on one side, a file on the other",
        F.ERROR: "Could not be read",
    }
    return words.get(status, status)


def inside_whole(node: F.Node) -> F.Node | None:
    """The folder on one side only that this row is inside, if any: it goes
    with that folder, which is the row to act on."""
    up = node.parent
    while up is not None:
        if up.status in (F.ONLY_LEFT, F.ONLY_RIGHT):
            return up
        up = up.parent
    return None


def choices(node: F.Node) -> tuple[str, ...]:
    """The actions a click cycles through for this row; () for none."""
    if node.member or node.status in (F.CLASH, F.ERROR) or inside_whole(node) is not None:
        return ()
    if node.status == F.ONLY_LEFT:
        return (RIGHT, SKIP)
    if node.status == F.ONLY_RIGHT:
        return (LEFT, SKIP)
    if node.is_dir:
        return ()
    if category(node) == SAME:
        return ()
    return (RIGHT, LEFT, SKIP)


@dataclass
class Decisions:
    """The default action of every row, and the ones changed by hand."""

    defaults: dict[str, str] = field(default_factory=dict)
    #: rel (lowercased) -> action, for rows somebody changed.
    chosen: dict[str, str] = field(default_factory=dict)

    def action(self, node: F.Node) -> str:
        key = node.rel.lower()
        return self.chosen.get(key, self.defaults.get(key, SKIP))

    def changed(self, node: F.Node) -> bool:
        key = node.rel.lower()
        return key in self.chosen and self.chosen[key] != self.defaults.get(key, SKIP)

    def set(self, node: F.Node, action: str) -> None:
        if action not in choices(node):
            return
        key = node.rel.lower()
        if action == self.defaults.get(key, SKIP):
            self.chosen.pop(key, None)
        else:
            self.chosen[key] = action

    def cycle(self, node: F.Node) -> str:
        options = choices(node)
        if not options:
            return self.action(node)
        now = self.action(node)
        following = options[(options.index(now) + 1) % len(options)] if now in options \
            else options[0]
        self.set(node, following)
        return self.action(node)


def defaults(root: F.Node, tolerance: float = F.TOLERANCE) -> dict[str, str]:
    """What an update each way would copy, as each row's default action."""
    out: dict[str, str] = {}
    for direction, action in ((S.TO_RIGHT, RIGHT), (S.TO_LEFT, LEFT)):
        plan = S.plan(root, direction, S.UPDATE, tolerance=tolerance)
        for item in plan.copies:
            out[item.rel.lower()] = action
    return out


def decide(root: F.Node, previous: Decisions | None = None) -> Decisions:
    """Fresh defaults for a tree, keeping the rows changed by hand that are
    still there and still allow what was chosen."""
    decisions = Decisions(defaults=defaults(root))
    if previous is not None:
        by_rel = {node.rel.lower(): node for node in root.walk()}
        for key, action in previous.chosen.items():
            node = by_rel.get(key)
            if node is not None:
                decisions.set(node, action)
    return decisions


@dataclass
class Totals:
    files: dict[str, int] = field(default_factory=lambda: {RIGHT: 0, LEFT: 0})
    folders: dict[str, int] = field(default_factory=lambda: {RIGHT: 0, LEFT: 0})
    size: dict[str, int] = field(default_factory=lambda: {RIGHT: 0, LEFT: 0})


def totals(root: F.Node, decisions: Decisions) -> Totals:
    """How much each way, counting a whole folder as its files."""
    out = Totals()
    for node in _acting(root, decisions):
        action = decisions.action(node)
        entry = node.left if action == RIGHT else node.right
        if entry is None:
            continue
        if node.is_dir:
            out.folders[action] += 1
            for child in node.walk():
                source = child.left if action == RIGHT else child.right
                if source is not None and not source.is_dir:
                    out.size[action] += source.size
        else:
            out.files[action] += 1
            out.size[action] += entry.size
    return out


def _acting(root: F.Node, decisions: Decisions):
    """The rows that copy, without anything under a folder that is copied
    whole (it goes with its folder)."""
    def walk(node: F.Node):
        for child in node.children:
            action = decisions.action(child)
            if action in (RIGHT, LEFT):
                yield child
                if child.is_dir:
                    continue
            if child.is_dir:
                yield from walk(child)
    yield from walk(root)


def requests(root: F.Node, decisions: Decisions, left_root: str, right_root: str, *,
             titles: tuple[str, str] = ("", "")) -> list[tuple[S.Plan, dict]]:
    """The requests that carry out the list, in the order to send them: for
    each direction, the rows at their default as an update, then the rows
    turned that way by hand as picked copies."""
    out = []
    names = (titles[0] or left_root, titles[1] or right_root)
    acting = list(_acting(root, decisions))
    for direction, action in ((S.TO_RIGHT, RIGHT), (S.TO_LEFT, LEFT)):
        source, target = names if direction == S.TO_RIGHT else names[::-1]
        rows = [n for n in acting if decisions.action(n) == action]
        for mode, group in ((S.UPDATE, [n for n in rows if not decisions.changed(n)]),
                            (S.COPY, [n for n in rows if decisions.changed(n)])):
            if not group:
                continue
            plan = S.plan(root, direction, mode, nodes=group)
            chosen = plan.copies
            if not chosen:
                continue
            out.append((plan, S.request(plan, chosen, left_root, right_root,
                                        title=f"{source} -> {target}")))
    return out
