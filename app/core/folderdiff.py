"""One folder comparison: two walks, the merged tree, and a content compare.

The folder counterpart of `core/session.py`, with the same rules. Every
filesystem call is in the loader; a side has a deadline and says so when it
misses it; every answer carries the id it was asked with, so a walk that
finishes after a re-walk or a closed tab is dropped.

The deadline is a **stall** deadline, not a total one. Walking fifty thousand
files on a slow share can honestly take a minute, and a walk that is still
finding files is not a dead share; one that has found nothing new for
`timeout` seconds is. The walk reports progress through a shared object
(`io/walk.Progress`) and a timer here looks at it.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from app.core import folders
from app.core.loader import Envelope, Loader
from app.io import walk as io_walk

LEFT, RIGHT = 0, 1

EMPTY = "empty"
WALKING = "walking"
READY = "ready"
FAILED = "failed"
SLOW = "not answering"


def _walk_job(root: str, progress: io_walk.Progress) -> list[folders.Entry]:
    return io_walk.walk(root, progress)


def _build_job(left, right, mask, tolerance):
    return folders.build(left, right, mask=mask, tolerance=tolerance)


class FolderSide:
    def __init__(self, path: str, title: str = "") -> None:
        self.path = path
        self.title = title
        self.state = EMPTY
        self.error = ""
        self.entries: list[folders.Entry] | None = None
        self.request = 0
        self.progress: io_walk.Progress | None = None
        self.seen = -1
        self.still = 0.0


class FolderSession(QObject):
    """Emits `changed` when the tree or a side's state moves on, and
    `progressed` on the timer while something is running."""

    changed = Signal()
    progressed = Signal()

    #: Seconds between looks at the walks' progress.
    TICK = 0.25

    def __init__(self, loader: Loader, left: str, right: str, *, mask: str = "",
                 timeout: float = 30.0, titles: tuple[str, str] = ("", ""),
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self.sides = [FolderSide(left, titles[0]), FolderSide(right, titles[1])]
        self.mask = folders.Mask.parse(mask)
        self.timeout = timeout
        self.tree: folders.Node | None = None
        self.building = False
        self._build_request = 0
        self.content: io_walk.Progress | None = None
        self.content_total = 0
        self._content_request = 0
        self._content_nodes: dict[int, folders.Node] = {}
        self.problem = ""
        loader.finished.connect(self._finished)
        self._timer = QTimer(self)
        self._timer.setInterval(int(self.TICK * 1000))
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------ the state

    @property
    def busy(self) -> bool:
        return (any(s.state == WALKING for s in self.sides) or self.building
                or self._content_request != 0)

    @property
    def broken(self) -> bool:
        return any(s.state in (FAILED, SLOW) for s in self.sides)

    def status(self) -> str:
        """One line on what is happening, for the view's toolbar."""
        walking = [s for s in self.sides if s.state == WALKING]
        if walking:
            found = sum(s.progress.files for s in walking if s.progress)
            return f"Reading folders...  {found:,} files so far"
        if self.building:
            return "Comparing..."
        if self._content_request and self.content is not None:
            return (f"Comparing contents...  {self.content.files:,} of "
                    f"{self.content_total:,}")
        if self.tree is not None:
            return folders.summary(self.tree)
        return ""

    # -------------------------------------------------------------- actions

    def start(self) -> None:
        self.tree = None
        self.cancel_contents()
        for index in (LEFT, RIGHT):
            self._walk(index)
        self._timer.start()
        self.changed.emit()

    def retry(self, index: int) -> None:
        self.tree = None
        self._walk(index)
        self._timer.start()
        self.changed.emit()

    def set_mask(self, text: str) -> None:
        mask = folders.Mask.parse(text)
        if mask == self.mask:
            return
        self.mask = mask
        self._build()

    def swap(self) -> None:
        self.sides.reverse()
        self._build()

    def compare_contents(self, *, all_pairs: bool = False, nodes=None) -> int:
        """Read the pairs size and time cannot settle (or all of them, or the
        given ones). Returns how many are queued."""
        if self.tree is None or self._content_request:
            return 0
        chosen = list(nodes) if nodes is not None else folders.content_candidates(
            self.tree, all_pairs=all_pairs)
        chosen = [n for n in chosen if n.pair]
        if not chosen:
            return 0
        left_root, right_root = (s.path for s in self.sides)
        self._content_nodes = {i: node for i, node in enumerate(chosen)}
        pairs = [(i, _join(left_root, node.rel), _join(right_root, node.rel))
                 for i, node in self._content_nodes.items()]
        self.content = io_walk.Progress()
        self.content_total = len(pairs)
        self._content_request = self._loader.submit(io_walk.compare_contents, pairs,
                                                    self.content)
        self._timer.start()
        self.changed.emit()
        return len(pairs)

    def cancel_contents(self) -> None:
        if self.content is not None:
            self.content.cancel.set()
        self._content_request = 0
        self.content = None

    def stop(self) -> None:
        for side in self.sides:
            if side.progress is not None:
                side.progress.cancel.set()
        self.cancel_contents()
        self._timer.stop()

    def paths(self, node: folders.Node) -> tuple[str, str]:
        return _join(self.sides[0].path, node.rel), _join(self.sides[1].path, node.rel)

    # ------------------------------------------------------------- plumbing

    def _walk(self, index: int) -> None:
        side = self.sides[index]
        if side.progress is not None:
            side.progress.cancel.set()
        side.entries = None
        side.error = ""
        if not side.path:
            side.state = EMPTY
            return
        side.state = WALKING
        side.progress = io_walk.Progress()
        side.seen = -1
        side.still = 0.0
        side.request = self._loader.submit(_walk_job, side.path, side.progress)

    def _tick(self) -> None:
        for side in self.sides:
            if side.state != WALKING or side.progress is None:
                continue
            seen = side.progress.folders + side.progress.files
            if seen != side.seen:
                side.seen, side.still = seen, 0.0
                continue
            side.still += self.TICK
            if side.still >= self.timeout:
                side.state = SLOW
                side.request = 0
                side.progress.cancel.set()
                side.error = (f"Nothing new for {self.timeout:g} seconds. "
                              "The share may be unreachable.")
                self.changed.emit()
        if not self.busy:
            self._timer.stop()
        self.progressed.emit()

    def _finished(self, request: int, envelope: Envelope) -> None:
        if not request:
            return
        for side in self.sides:
            if side.request == request:
                side.request = 0
                if envelope.ok:
                    side.entries = envelope.value
                    side.state = READY
                else:
                    side.state = FAILED
                    side.error = envelope.error.split(": ", 1)[-1] if envelope.error else \
                        "Could not be read"
                    if "Cancelled" in (envelope.error or ""):
                        side.error = "Stopped"
                if all(s.state == READY for s in self.sides):
                    self._build()
                else:
                    self.changed.emit()
                return
        if request == self._build_request:
            self._build_request = 0
            self.building = False
            if envelope.ok:
                self.tree = envelope.value
                self.problem = ""
            else:
                self.problem = f"The comparison failed: {envelope.error}"
            self.changed.emit()
            return
        if request == self._content_request:
            self._content_request = 0
            if envelope.ok and self.tree is not None:
                for key, same, error in envelope.value:
                    node = self._content_nodes.get(key)
                    if node is not None:
                        folders.settle(node, same, error)
            self._content_nodes = {}
            self.content = None
            self.changed.emit()

    def _build(self) -> None:
        if not all(s.state == READY and s.entries is not None for s in self.sides):
            self.changed.emit()
            return
        self.cancel_contents()
        self.building = True
        self._build_request = self._loader.submit(
            _build_job, self.sides[0].entries, self.sides[1].entries, self.mask,
            folders.TOLERANCE)
        self.changed.emit()


def _join(root: str, rel: str) -> str:
    if not rel:
        return root
    separator = "\\" if ("\\" in root or ":" in root[:3]) else "/"
    rel = rel.replace("\\", separator)
    return root.rstrip("\\/") + separator + rel
