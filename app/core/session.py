"""One open comparison: its two sides, its rules and its result.

The tab draws this; this asks the loader. The sequence for a pair of paths:

  1. each side is opened off the UI thread -- is it a file, a folder, or not
     there, and if a file, its text as `io/load.py` decoded it;
  2. each side has a deadline, and a side that misses it is shown as not
     answering with a retry, while the other side stays as it is;
  3. when both sides are text, the diff runs off the UI thread as well;
  4. a new rule, a swap or a retry starts again from whichever step it
     invalidates, and every reply carries the id it was asked with so an
     answer to an old question is dropped;
  5. an edit changes a side's `Document`, and the diff runs again. Small
     files are compared on the spot, so the view never shows rows that point
     past the end of a line list; large ones go to the loader, and until the
     answer arrives the result says which revision of each side it was made
     from, and block copies wait for it.

Saving goes to `io/save.py`, off the UI thread like every read, and a file
that changed on disk since it was read is never overwritten without asking.
A poll -- not a watcher, SMB change notification being what it is -- notices
a file changing under an open tab and says so over that side.

Nothing here touches Qt widgets, and nothing touches the disk directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from PySide6.QtCore import QObject, QTimer, Signal

from app.core.diff import align
from app.core import formats
from app.core.document import ENDINGS, Document
from app.core.loader import Envelope, Loader
from app.core.rules import Rules, comment_markers
from app.io import kind as io_kind
from app.io import load as io_load
from app.io import save as io_save

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

#: Below this many lines on both sides together, a comparison after an edit
#: runs at once on the UI thread: a few milliseconds, and the view goes
#: straight from one consistent state to the next. Above it, the loader.
SYNC_LINES = 40_000

#: Seconds between looks at whether a file changed on disk.
POLL_SECONDS = 3.0


def open_side(path: str, max_bytes: int) -> tuple[str, io_load.Loaded | None]:
    """The worker's half: what the path is, and its text if it is a file."""
    what = io_kind.kind(path)
    if what != io_kind.FILE:
        return what, None
    return what, io_load.load(path, max_bytes=max_bytes)


def save_side(path: str, lines: list[str], endings: list[str], encoding: str, bom: bool,
              expect: tuple[int, float] | None, backup: bool, force: bool) -> io_save.Saved:
    """The worker's half of a save: encode, then write beside and rename."""
    try:
        data = io_save.encode(lines, endings, encoding, bom)
    except UnicodeEncodeError as exc:
        return io_save.Saved(ok=False, path=path, error=f"Not saved: {exc.reason}")
    size, mtime = expect if expect else (None, None)
    return io_save.save(path, data, expect_size=size, expect_mtime=mtime,
                        backup=backup, force=force)


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
    #: The text as it is now, edits included. None until a text file loads.
    doc: Document | None = None
    #: What a save writes: from the file, unless changed from the side's menu.
    encoding: str = ""
    bom: bool = False
    #: Size and modification time on disk, as of the read or the last save.
    disk: tuple[int, float] | None = None
    #: The file changed on disk since then (the poll noticed).
    stale: bool = False
    saving: bool = False
    #: The most recent save's problem, shown over the side until the next.
    save_error: str = ""
    #: Shown through a format comparer (L5X, XML...): the lines are not the
    #: file's, so nothing is edited or saved through them.
    structured: bool = False

    @property
    def lines(self) -> list[str]:
        if self.doc is not None:
            return self.doc.lines
        return self.loaded.lines if self.loaded is not None else []

    @property
    def dirty(self) -> bool:
        return self.doc is not None and self.doc.dirty

    @property
    def editable(self) -> bool:
        """Text that can be changed and written back without losing a byte."""
        return (self.doc is not None and not self.readonly and self.loaded is not None
                and not self.loaded.lossy and not self.loaded.binary and not self.structured)

    @property
    def why_not_editable(self) -> str:
        if self.doc is None:
            return "Nothing is loaded on this side"
        if self.structured:
            return ("Showing the file by its structure, which is not its text; "
                    "switch Structure off to edit")
        if self.readonly:
            return "This side is read-only"
        if self.loaded is not None and self.loaded.lossy:
            return ("Some bytes of this file did not decode; saving it as text "
                    "would replace them, so it is read-only")
        return ""


@dataclass
class Options:
    rules: Rules = field(default_factory=Rules)
    intraline: str = "char"
    timeout: float = 20.0
    max_bytes: int = io_load.MAX_BYTES
    backup: bool = False
    poll: bool = True
    #: Folder compare's name mask, as typed (`core/folders.Mask`).
    folder_mask: str = ""
    #: "auto" picks a format comparer by extension; "text" never does.
    format: str = "auto"
    #: Whether a detected format comparer starts switched on.
    structure: bool = True
    #: The view the tab opens in: "auto", "text", "hex" or "image" (--mode).
    mode: str = "auto"


class Session(QObject):
    """Emits `changed` whenever anything a view draws has moved on."""

    changed = Signal()
    #: A save finished: (side index, `io_save.Saved`).
    saved = Signal(int, object)

    def __init__(self, loader: Loader, left: str, right: str, *,
                 options: Options | None = None, titles: tuple[str, str] = ("", ""),
                 readonly: set[str] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self.options = options or Options()
        markers = comment_markers(left) or comment_markers(right)
        self.options = replace(self.options,
                               rules=replace(self.options.rules, markers=markers))
        readonly = readonly or set()
        self.sides = [Side(path=left, title=titles[0], readonly="left" in readonly),
                      Side(path=right, title=titles[1], readonly="right" in readonly)]
        self.result: align.Comparison | None = None
        #: The lines `result` was computed from. The view draws these, never
        #: the live documents, so rows and lines always agree.
        self.result_lines: tuple[list[str], list[str]] = ([], [])
        #: Where each of those lines is in the file's structure, when a format
        #: comparer made them; empty strings otherwise.
        self.result_crumbs: tuple[list[str], list[str]] = ([], [])
        #: What the format comparer looked past, or why it could not.
        self.format_note = ""
        self.format_kind = formats.PLAIN if self.options.format == "text" else \
            formats.detect(left, right)
        self.structure = self.options.structure and self.format_kind in formats.DEFAULT_ON
        self._result_revisions: tuple[int, int] = (-1, -1)
        self.comparing = False
        self.problem = ""
        self._compare_request = 0
        self._compare_revisions: tuple[int, int] = (-1, -1)
        self._save_requests: dict[int, int] = {}
        self._save_revision: dict[int, int] = {}
        self._probe_requests: dict[int, int] = {}
        self._timers: list[QTimer | None] = [None, None]
        loader.finished.connect(self._finished)
        self._poll = QTimer(self)
        self._poll.setInterval(int(POLL_SECONDS * 1000))
        self._poll.timeout.connect(self._look_at_disk)
        if self.options.poll:
            self._poll.start()

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
    def current(self) -> bool:
        """The result describes the documents as they are now."""
        return self.result is not None and self._result_revisions == self._revisions()

    @property
    def dirty(self) -> bool:
        return any(side.dirty for side in self.sides)

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
        rules = replace(rules, markers=self.options.rules.markers)
        if rules == self.options.rules:
            return
        self.options = replace(self.options, rules=rules)
        self._compare()

    def set_structure(self, on: bool) -> None:
        """The format comparer on or off (the toolbar's Structure switch)."""
        on = on and self.format_kind != formats.PLAIN
        if on != self.structure:
            self.structure = on
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
        self._save_requests = {r: 1 - i for r, i in self._save_requests.items()}
        self._compare()

    # -------------------------------------------------------------- editing

    def replace_lines(self, index: int, start: int, end: int, lines: list[str]) -> bool:
        """Lines `start:end` of one side become `lines`, as one undo step."""
        side = self.sides[index]
        if not side.editable:
            return False
        if side.doc.replace(start, end, lines):
            self._edited()
            return True
        return False

    def copy_block(self, block: int, to_side: int) -> bool:
        """The other side's lines of difference `block` replace this side's.
        Only against a current result: rows from before an edit would copy
        the wrong lines."""
        if not self.current or not (0 <= block < len(self.result.blocks)):
            return False
        target = self.sides[to_side]
        if not target.editable:
            return False
        b = self.result.blocks[block]
        rows = self.result.rows
        src0, src1 = align.side_range(rows, b.start, b.end, 1 - to_side)
        dst0, dst1 = align.side_range(rows, b.start, b.end, to_side)
        source = self.sides[1 - to_side].lines[src0:src1]
        if target.doc.replace(dst0, dst1, source):
            self._edited()
            return True
        return False

    def copy_all(self, to_side: int) -> bool:
        """Every difference across at once: this side becomes the other's
        text, keeping its own line endings. One undo step."""
        target = self.sides[to_side]
        source = self.sides[1 - to_side]
        if not target.editable or source.doc is None and source.loaded is None:
            return False
        if target.doc.replace(0, len(target.doc.lines), list(source.lines)):
            self._edited()
            return True
        return False

    def undo(self, index: int) -> bool:
        side = self.sides[index]
        if side.doc is None or side.doc.undo() is None:
            return False
        self._edited()
        return True

    def redo(self, index: int) -> bool:
        side = self.sides[index]
        if side.doc is None or side.doc.redo() is None:
            return False
        self._edited()
        return True

    def set_encoding(self, index: int, encoding: str, bom: bool) -> None:
        """What the next save writes. Takes effect on save, and marks nothing
        dirty on its own -- but a side whose bytes would change says so."""
        side = self.sides[index]
        side.encoding, side.bom = encoding, bom
        self.changed.emit()

    def set_line_endings(self, index: int, eol: str) -> bool:
        """Every line of a side to one ending, as an undoable edit."""
        side = self.sides[index]
        if not side.editable or eol not in ENDINGS:
            return False
        doc = side.doc
        ending = ENDINGS[eol]
        endings = [ending if e else "" for e in doc.endings]
        doc.newline = ending
        if doc.replace(0, len(doc.lines), list(doc.lines), endings):
            self._edited()
            return True
        return False

    def encoding_changed(self, index: int) -> bool:
        side = self.sides[index]
        return side.loaded is not None and (side.encoding, side.bom) != (
            side.loaded.encoding, side.loaded.bom)

    def _edited(self) -> None:
        for side in self.sides:
            side.save_error = ""
        self._compare()

    # --------------------------------------------------------------- saving

    def save(self, index: int, *, force: bool = False, path: str = "") -> bool:
        """Write one side. `path` saves elsewhere (save as). The answer comes
        back as `saved`; a conflict is an answer, not a write."""
        side = self.sides[index]
        if side.doc is None or side.saving:
            return False
        if not path and not side.editable:
            return False
        target = path or side.path
        expect = None if path else side.disk
        side.saving = True
        side.save_error = ""
        request = self._loader.submit(
            save_side, target, list(side.doc.lines), list(side.doc.endings),
            side.encoding, side.bom, expect, self.options.backup, force)
        self._save_requests[request] = index
        self._save_revision[request] = side.doc.revision
        self.changed.emit()
        return True

    def _save_done(self, index: int, request: int, envelope: Envelope) -> None:
        side = self.sides[index]
        side.saving = False
        result: io_save.Saved
        if envelope.ok:
            result = envelope.value
        else:
            result = io_save.Saved(ok=False, path=side.path, error=envelope.error)
        if result.ok:
            if result.path == side.path or not side.path:
                side.path = result.path
            else:
                # Saved elsewhere: that file is now what this side is.
                side.path = result.path
                side.readonly = False
            revision = self._save_revision.pop(request, None)
            if side.doc is not None and revision == side.doc.revision:
                side.doc.mark_saved()
            side.disk = (result.size, result.mtime)
            side.stale = False
            if side.loaded is not None:
                side.loaded.encoding, side.loaded.bom = side.encoding, side.bom
        else:
            side.save_error = result.error
        self.saved.emit(index, result)
        self.changed.emit()

    # ------------------------------------------------------------- the disk

    def _look_at_disk(self) -> None:
        for index, side in enumerate(self.sides):
            if side.state != READY or side.kind != io_kind.FILE or side.disk is None \
                    or side.saving or index in self._probe_requests.values():
                continue
            request = self._loader.submit(io_save.probe, side.path)
            self._probe_requests[request] = index

    def _probe_done(self, index: int, envelope: Envelope) -> None:
        side = self.sides[index]
        if not envelope.ok or side.disk is None or side.saving:
            return
        stale = io_save.changed(envelope.value, *side.disk)
        if stale != side.stale:
            side.stale = stale
            self.changed.emit()

    def stop(self) -> None:
        """The tab is closing: no more polling."""
        self._poll.stop()

    # ------------------------------------------------------------- plumbing

    def _open(self, index: int) -> None:
        side = self.sides[index]
        if not side.path:
            # Nothing on this side: a file only on the other side of a folder
            # compare, or a new text. Compared against no lines at all, and
            # "saved" only by Save as.
            side.state = READY
            side.kind = io_kind.FILE
            side.loaded = io_load.Loaded(path="", ok=True, encoding="utf-8")
            side.encoding, side.bom = "utf-8", False
            side.doc = Document.from_lines([], [])
            side.disk = None
            if all(s.state == READY for s in self.sides):
                self._compare()
            else:
                self.changed.emit()
            return
        side.state = LOADING
        side.error = ""
        side.doc = None
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
        if not request:
            return
        for index, side in enumerate(self.sides):
            if side.request == request:
                self._side_done(index, envelope)
                return
        if request in self._save_requests:
            self._save_done(self._save_requests.pop(request), request, envelope)
            return
        if request in self._probe_requests:
            self._probe_done(self._probe_requests.pop(request), envelope)
            return
        if request == self._compare_request:
            self._compare_request = 0
            self.comparing = False
            if envelope.ok:
                result, lines, crumbs, note = envelope.value
                self._take(result, lines, self._compare_revisions, crumbs, note)
                if not self.current:
                    # Edited while this ran: go again with the text as it is.
                    self._compare()
                    return
            else:
                self.result = None
                self.problem = f"The comparison failed: {envelope.error}"
            self.changed.emit()

    def _take(self, result: align.Comparison, lines, revisions, crumbs=None,
              note: str = "") -> None:
        self.result = result
        self.result_lines = lines
        self.result_crumbs = crumbs or ([], [])
        self.format_note = note
        self._result_revisions = revisions
        self.problem = ""

    def _revisions(self) -> tuple[int, int]:
        return tuple(s.doc.revision if s.doc is not None else -1 for s in self.sides)

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
                side.stale = False
                side.save_error = ""
                if loaded is not None:
                    side.disk = (loaded.size, loaded.mtime)
                    side.encoding, side.bom = loaded.encoding, loaded.bom
                    if not loaded.binary:
                        side.doc = Document.from_lines(loaded.lines, loaded.endings)
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
        lines = (list(left.lines), list(right.lines))
        revisions = self._revisions()
        kind = self.format_kind if self.structure else formats.PLAIN
        for side in self.sides:
            side.structured = kind != formats.PLAIN
        if len(lines[0]) + len(lines[1]) <= SYNC_LINES:
            self._compare_request = 0
            self.comparing = False
            result, shown, crumbs, note = _compare_job(lines, self.options.rules, kind)
            self._take(result, shown, revisions, crumbs, note)
            self.changed.emit()
            return
        self.comparing = True
        self._compare_revisions = revisions
        self._compare_request = self._loader.submit(_compare_job, lines, self.options.rules, kind)
        self.changed.emit()


def _compare_job(lines, rules, kind=formats.PLAIN):
    """The diff, through a format comparer first when one is on. Returns the
    result, the lines it was computed from, their crumbs, and the note."""
    if kind == formats.PLAIN:
        return align.compare(lines[0], lines[1], rules), lines, ([], []), ""
    a = formats.normalise(kind, lines[0])
    b = formats.normalise(kind, lines[1])
    note = a.problem or b.problem or f"{formats.names()[kind]}: ignoring {a.ignored}"
    shown = (a.lines, b.lines)
    return align.compare(shown[0], shown[1], rules), shown, (a.crumbs, b.crumbs), note

