"""One open comparison: its two sides, its rules and its result.

The tab draws this; this asks the loader. The sequence for a pair of paths:

  1. each side is opened off the UI thread -- is it a file, a folder, or not
     there, and if a file, its text as `io/load.py` decoded it;
  2. each side has a deadline, and a side that misses it is shown as not
     answering with a retry, while the other side stays as it is;
  3. when both sides are text, the diff runs off the UI thread as well;
  4. a new rule, a swap or a retry starts again from whichever step it
     invalidates, and every reply carries the id it was asked with so an
     answer to an old question is dropped.

Nothing here touches Qt widgets, and nothing touches the disk directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from PySide6.QtCore import QObject, QTimer, Signal

from app.core.diff import align
from app.core.loader import Envelope, Loader
from app.core.rules import Rules
from app.io import kind as io_kind
from app.io import load as io_load

LEFT, RIGHT = 0, 1
SIDES = ("left", "right")

# Side states.
EMPTY = "empty"
LOADING = "loading"
READY = "ready"
FAILED = "failed"
SLOW = "not answering"

# What the whole comparison is.
WAITING = "waiting"      # a side is still loading or comparing
TEXT = "text"            # both sides text, compared
BINARY = "binary"        # at least one side binary: matched by hash only
FOLDERS = "folders"      # folder compare, not in this version
MIXED = "mixed"          # a file on one side and a folder on the other
BROKEN = "broken"        # a side failed or is not answering


def open_side(path: str, max_bytes: int) -> tuple[str, io_load.Loaded | None]:
    """The worker's half: what the path is, and its text if it is a file."""
    what = io_kind.kind(path)
    if what != io_kind.FILE:
        return what, None
    return what, io_load.load(path, max_bytes=max_bytes)


@dataclass
class Side:
    path: str = ""
    title: str = ""
    readonly: bool = False
    state: str = EMPTY
    kind: str = ""
    loaded: io_load.Loaded | None = None
    error: str = ""
    request: int = 0

    @property
    def lines(self) -> list[str]:
        return self.loaded.lines if self.loaded is not None else []


@dataclass
class Options:
    rules: Rules = field(default_factory=Rules)
    intraline: str = "char"
    timeout: float = 20.0
    max_bytes: int = io_load.MAX_BYTES


class Session(QObject):
    """Emits `changed` whenever anything a view draws has moved on."""

    changed = Signal()

    def __init__(self, loader: Loader, left: str, right: str, *,
                 options: Options | None = None, titles: tuple[str, str] = ("", ""),
                 readonly: set[str] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self.options = options or Options()
        readonly = readonly or set()
        self.sides = [Side(path=left, title=titles[0], readonly="left" in readonly),
                      Side(path=right, title=titles[1], readonly="right" in readonly)]
        self.result: align.Comparison | None = None
        self.comparing = False
        self.problem = ""
        self._compare_request = 0
        self._timers: list[QTimer | None] = [None, None]
        loader.finished.connect(self._finished)

    # ------------------------------------------------------------ the state

    @property
    def kind(self) -> str:
        left, right = self.sides
        if any(s.state in (FAILED, SLOW) for s in self.sides):
            return BROKEN
        if any(s.state in (LOADING, EMPTY) for s in self.sides):
            return WAITING
        if left.kind == io_kind.FOLDER and right.kind == io_kind.FOLDER:
            return FOLDERS
        if left.kind != right.kind:
            return MIXED
        if any(s.loaded is not None and s.loaded.binary for s in self.sides):
            return BINARY
        if self.result is None:
            return WAITING
        return TEXT

    @property
    def rules(self) -> Rules:
        return self.options.rules

    @property
    def byte_identical(self) -> bool:
        left, right = (s.loaded for s in self.sides)
        return bool(left and right and left.digest and left.digest == right.digest)

    # -------------------------------------------------------------- actions

    def start(self) -> None:
        for index in (LEFT, RIGHT):
            self._open(index)

    def retry(self, index: int) -> None:
        self._open(index)

    def reload(self) -> None:
        """Read both sides from disk again and compare (Ctrl+R)."""
        self.start()

    def set_rules(self, rules: Rules) -> None:
        if rules == self.options.rules:
            return
        self.options = replace(self.options, rules=rules)
        self._compare()

    def set_intraline(self, mode: str) -> None:
        if mode != self.options.intraline:
            self.options = replace(self.options, intraline=mode)
            self.changed.emit()

    def swap(self) -> None:
        """Left becomes right. The loaded text goes with its side, so there is
        nothing to read again -- only the diff, which is not symmetric in its
        kinds, is run again."""
        self.sides.reverse()
        self._timers.reverse()
        self._compare()

    # ------------------------------------------------------------- plumbing

    def _open(self, index: int) -> None:
        side = self.sides[index]
        if not side.path:
            side.state = EMPTY
            self.changed.emit()
            return
        side.state = LOADING
        side.error = ""
        side.request = self._loader.submit(open_side, side.path, self.options.max_bytes)
        self.result = None
        self._compare_request = 0
        self._arm(index, side.request)
        self.changed.emit()

    def _arm(self, index: int, request: int) -> None:
        old = self._timers[index]
        if old is not None:
            old.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda i=index, r=request: self._late(i, r))
        timer.start(int(self.options.timeout * 1000))
        self._timers[index] = timer

    def _late(self, index: int, request: int) -> None:
        side = self.sides[index]
        if side.request != request or side.state != LOADING:
            return
        side.state = SLOW
        side.request = 0          # the answer, if it ever comes, is dropped
        side.error = (f"No answer after {self.options.timeout:g} seconds. "
                      "The share may be unreachable.")
        self.changed.emit()

    def _finished(self, request: int, envelope: Envelope) -> None:
        for index, side in enumerate(self.sides):
            if request and side.request == request:
                self._side_done(index, envelope)
                return
        if request and request == self._compare_request:
            self._compare_request = 0
            self.comparing = False
            if envelope.ok:
                self.result = envelope.value
                self.problem = ""
            else:
                self.result = None
                self.problem = f"The comparison failed: {envelope.error}"
            self.changed.emit()

    def _side_done(self, index: int, envelope: Envelope) -> None:
        side = self.sides[index]
        side.request = 0
        timer = self._timers[index]
        if timer is not None:
            timer.stop()
        if not envelope.ok:
            side.state = FAILED
            side.error = envelope.error
            side.loaded = None
        else:
            what, loaded = envelope.value
            side.kind = what
            side.loaded = loaded
            if what == io_kind.MISSING:
                side.state = FAILED
                side.error = "Not found"
            elif loaded is not None and not loaded.ok:
                side.state = FAILED
                side.error = loaded.error
            else:
                side.state = READY
        if all(s.state == READY for s in self.sides):
            self._compare()
        else:
            self.changed.emit()

    def _compare(self) -> None:
        if not all(s.state == READY for s in self.sides):
            self.changed.emit()
            return
        left, right = self.sides
        texts = (left.loaded, right.loaded)
        if left.kind != io_kind.FILE or right.kind != io_kind.FILE \
                or any(t is None or t.binary for t in texts):
            self.result = None
            self.changed.emit()
            return
        self.comparing = True
        self._compare_request = self._loader.submit(
            align.compare, list(left.lines), list(right.lines), self.options.rules)
        self.changed.emit()
