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
from app.io import handoff as io_handoff
from app.io import walk as io_walk

LEFT, RIGHT = 0, 1

EMPTY = "empty"
WALKING = "walking"
READY = "ready"
FAILED = "failed"
SLOW = "not answering"


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
    #: 1.0: a line about the sync handed to File Manager -- sent, refused,
    #: finished -- for the status bar.
    handed = Signal(str)
    #: 1.0: whether each side is on a share, `(left, right)`, for the preview.
    remote = Signal(object)

    #: Seconds between looks for File Manager's result file.
    POLL = 2.0

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
        # 1.0: the sync handoff. One request outstanding per tab: the tree
        # is walked again when its result arrives, and a second sync planned
        # from the tree before that would be planned from stale verdicts.
        self._send_request = 0
        self._poll_request = 0
        self._remote_request = 0
        self.pending = ""                # the request file File Manager has
        self._poll = QTimer(self)
        self._poll.setInterval(int(self.POLL * 1000))
        self._poll.timeout.connect(self._look_for_result)

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
        self._content_request = self._loader.submit_io(left_root, io_walk.compare_contents,
                                                       pairs, progress=self.content)
        self._timer.start()
        self.changed.emit()
        return len(pairs)

    def cancel_contents(self) -> None:
        if self.content is not None:
            self.content.cancel.set()
        self._content_request = 0
        self.content = None

    def stop(self) -> None:
        self._poll.stop()
        for side in self.sides:
            if side.progress is not None:
                side.progress.cancel.set()
        self.cancel_contents()
        self._timer.stop()

    # ------------------------------------------------------ sync handoff

    @property
    def syncing(self) -> bool:
        return bool(self._send_request or self.pending)

    def check_remote(self) -> None:
        """Ask whether either side is on a share; `remote` answers."""
        self._remote_request = self._loader.submit(
            io_handoff.remote_sides, self.sides[0].path, self.sides[1].path)

    def send_sync(self, request: dict) -> bool:
        """Hand the jobs to File Manager. False if one is already out."""
        if self.syncing or not request.get("jobs"):
            return False
        self._send_request = self._loader.submit(io_handoff.send, request)
        self.handed.emit("Sending to File Manager...")
        return True

    def forget_sync(self) -> None:
        """Stop waiting for File Manager's result. The jobs, if File Manager
        took them, carry on in its queue; only this tab stops listening --
        for a File Manager older than 0.46, which never writes one."""
        self._poll.stop()
        self.pending = ""
        self._poll_request = 0
        self.changed.emit()

    def _look_for_result(self) -> None:
        if self.pending and not self._poll_request:
            self._poll_request = self._loader.submit(io_handoff.result, self.pending)

    def _handoff_answer(self, request: int, envelope: Envelope) -> bool:
        if request == self._remote_request:
            self._remote_request = 0
            self.remote.emit(envelope.value if envelope.ok else (False, False))
            return True
        if request == self._send_request:
            self._send_request = 0
            if envelope.ok:
                self.pending, _program = envelope.value
                self._poll.start()
                self.handed.emit("Handed to File Manager's queue. This comparison "
                                 "is read again when the jobs finish.")
            else:
                self.handed.emit("Could not hand the sync to File Manager: "
                                 + (envelope.error.split(": ", 1)[-1] if envelope.error
                                    else "unknown"))
            self.changed.emit()
            return True
        if request == self._poll_request:
            self._poll_request = 0
            outcome = envelope.value if envelope.ok else None
            if outcome is None:
                return True
            self._poll.stop()
            self.pending = ""
            self.handed.emit(describe(outcome))
            self.start()
            return True
        return False

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
        side.request = self._loader.submit_io(side.path, io_walk.walk, side.path,
                                              progress=side.progress)

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
                self._loader.abandon(side.request)
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
        if self._handoff_answer(request, envelope):
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


def describe(outcome: dict) -> str:
    """File Manager's result, in one line."""
    parts = [f"{int(outcome.get('copied', 0)):,} copied"]
    for key in ("skipped", "failed"):
        if outcome.get(key):
            parts.append(f"{int(outcome[key]):,} {key}")
    if outcome.get("cancelled"):
        parts.append("cancelled part way")
    for why in outcome.get("refused") or []:
        parts.append(f"refused: {why}")
    return "File Manager finished the sync: " + ", ".join(parts) + ". Read both folders again."


def _join(root: str, rel: str) -> str:
    if not rel:
        return root
    separator = "\\" if ("\\" in root or ":" in root[:3]) else "/"
    rel = rel.replace("\\", separator)
    return root.rstrip("\\/") + separator + rel
