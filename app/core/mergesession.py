"""One three-way merge: mine, theirs and base read, merged, and the output saved.

The shape git's `mergetool` calls: `--merge <mine> <theirs> <base> -o <out>`.
The three inputs are read off the UI thread like every side in the
application; the merge itself is `core/diff/merge3.py` and is fast enough to
run on the spot. The output is written with `io/save.py` -- beside, then
renamed -- in the encoding, byte order mark and line endings of *mine*, which
is the working copy the user was editing.

The output file is git's MERGED, which git has already filled with its own
conflict markers. It is not read and is overwritten on save without the
"changed on disk" check: its content is not the user's work, and the check
would stop every merge.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.core.diff import merge3
from app.core.document import dominant
from app.core.loader import Envelope, Loader
from app.core.session import open_side, save_side
from app.io import kind as io_kind

NAMES = ("mine", "theirs", "base")


class MergeSession(QObject):
    changed = Signal()
    saved = Signal(object)

    def __init__(self, loader: Loader, mine: str, theirs: str, base: str, output: str,
                 *, max_bytes: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self.paths = {"mine": mine, "theirs": theirs, "base": base}
        self.output_path = output
        self.max_bytes = max_bytes
        self.loaded: dict[str, object] = {}
        self.errors: dict[str, str] = {}
        self._requests: dict[int, str] = {}
        self._save_request = 0
        self.merge: merge3.Merge | None = None
        #: The output as text, once somebody edits it by hand. None while the
        #: output is still made from the chunks' resolutions.
        self.freehand: list[str] | None = None
        self.dirty = False
        self.saved_ok = False
        self.saving = False
        loader.finished.connect(self._finished)

    def start(self) -> None:
        for name in NAMES:
            self._requests[self._loader.submit(open_side, self.paths[name],
                                               self.max_bytes)] = name

    @property
    def problem(self) -> str:
        if self.errors:
            return "  ·  ".join(f"{name}: {why}" for name, why in self.errors.items())
        return ""

    # ------------------------------------------------------------ resolving

    def resolve(self, index: int, resolution: str, custom: list[str] | None = None) -> None:
        if self.merge is None or self.freehand is not None:
            return
        chunk = self.merge.chunks[index]
        chunk.resolution = resolution
        chunk.custom = list(custom or [])
        self.dirty = True
        self.changed.emit()

    def resolve_all(self, resolution: str) -> None:
        if self.merge is None:
            return
        for index in self.merge.unresolved:
            self.merge.chunks[index].resolution = resolution
        self.dirty = True
        self.changed.emit()

    def set_freehand(self, lines: list[str]) -> None:
        self.freehand = list(lines)
        self.dirty = True

    def output(self) -> tuple[list[str], list[tuple[int, int]]]:
        if self.merge is None:
            return [], []
        if self.freehand is not None:
            return list(self.freehand), []
        return self.merge.output(labels=("mine", "base", "theirs"))

    @property
    def unresolved(self) -> int:
        if self.merge is None:
            return 0
        if self.freehand is not None:
            return sum(1 for line in self.freehand if line.startswith("<<<<<<< "))
        return len(self.merge.unresolved)

    # --------------------------------------------------------------- saving

    def save(self, path: str = "") -> bool:
        target = path or self.output_path
        if not target or self.merge is None or self.saving:
            return False
        lines, _spans = self.output()
        mine = self.loaded.get("mine")
        encoding = getattr(mine, "encoding", "") or "utf-8"
        bom = bool(getattr(mine, "bom", False))
        endings = getattr(mine, "endings", []) or []
        newline = dominant(endings)
        final = endings[-1] if endings else newline
        out_endings = [newline] * len(lines)
        if out_endings:
            out_endings[-1] = final
        self.saving = True
        self._save_request = self._loader.submit(save_side, target, lines, out_endings,
                                                 encoding, bom, None, False, True)
        self.changed.emit()
        return True

    # ------------------------------------------------------------- plumbing

    def _finished(self, request: int, envelope: Envelope) -> None:
        if request in self._requests:
            name = self._requests.pop(request)
            if not envelope.ok:
                self.errors[name] = envelope.error
            else:
                what, loaded = envelope.value
                if what != io_kind.FILE or loaded is None:
                    self.errors[name] = "Not found" if what == io_kind.MISSING else "Not a file"
                elif not loaded.ok:
                    self.errors[name] = loaded.error
                elif loaded.binary:
                    self.errors[name] = "A binary file cannot be merged line by line"
                else:
                    self.loaded[name] = loaded
            if not self._requests and not self.errors:
                self.merge = merge3.merge(self.loaded["base"].lines, self.loaded["mine"].lines,
                                          self.loaded["theirs"].lines)
            self.changed.emit()
        elif request and request == self._save_request:
            self._save_request = 0
            self.saving = False
            result = envelope.value if envelope.ok else None
            if result is not None and result.ok:
                self.dirty = False
                self.saved_ok = True
            self.saved.emit(result if result is not None else envelope.error)
            self.changed.emit()
