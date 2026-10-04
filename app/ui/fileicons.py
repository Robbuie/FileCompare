"""The folder compare's row icons: Windows' own, by kind, kept for the session.

File Manager's `core/icons.py` in miniature, for the same reasons (1.12). The
cache is keyed on the kind -- an extension, a folder, a file with no extension
-- so a tree of 50,000 rows costs one lookup per distinct extension, and the
second folder compare of the day usually costs nothing.

`icon` is called from the model's `data()` while the tree paints, so it never
waits: it records a kind it does not have, returns the drawn stand-in, and
the kinds gathered during one paint go to the icon thread together a moment
later. When they come back `changed` fires and the tree paints again.

One thread for the whole application rather than one per tab, because the
shell wants COM initialised on the thread that asks it, and because the
answers are the same for every tab.
"""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap

from app.io import shellicons
from app.ui import glyphs

#: Logical pixels an icon occupies in a row.
ROW_ICON = 16
#: How long kinds gather before they are sent, in milliseconds.
COALESCE_MS = 30


class FileIcons(QObject):
    changed = Signal()
    _arrived = Signal(object)

    def __init__(self, fetch=shellicons.pixels, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fetch = fetch
        self._cache: dict[str, QIcon] = {}
        self._asked: set[str] = set()
        self._pending: set[str] = set()
        self._fallback: dict[tuple, QIcon] = {}
        self._size = ROW_ICON
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COALESCE_MS)
        self._timer.timeout.connect(self.flush)
        self._arrived.connect(self._take)

    def set_scale(self, ratio: float) -> None:
        """Ask the shell for 32 pixels on a scaled display, so the icon is the
        sharp one, drawn in the same 16 logical pixels either way."""
        size = 32 if ratio > 1.25 else ROW_ICON
        if size != self._size:
            self._size = size
            self._cache.clear()
            self._asked.clear()

    def icon(self, name: str, is_dir: bool, colour: str, muted: str) -> QIcon:
        key = shellicons.key_for(name, is_dir)
        found = self._cache.get(key)
        if found is not None:
            return found
        self.want(key)
        return self.stand_in(key, colour, muted)

    def stand_in(self, key: str, colour: str, muted: str) -> QIcon:
        glyph = "folder" if key == shellicons.FOLDER else "zip" if key == ".zip" else "file"
        ratio = self._size / ROW_ICON
        token = (glyph, colour, ratio)
        found = self._fallback.get(token)
        if found is None:
            found = glyphs.icon(glyph, colour=colour, muted=muted, size=ROW_ICON, ratio=ratio)
            self._fallback[token] = found
        return found

    def want(self, key: str) -> None:
        if key in self._cache or key in self._asked:
            return
        self._pending.add(key)
        if not self._timer.isActive():
            self._timer.start()

    def flush(self) -> None:
        self._timer.stop()
        if not self._pending:
            return
        keys = sorted(self._pending)
        self._pending.clear()
        self._asked.update(keys)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="file-icons", daemon=True)
            self._thread.start()
        self._jobs.put((keys, self._size))

    def _run(self) -> None:
        while True:
            keys, size = self._jobs.get()
            found = {}
            for key in keys:
                data = self._fetch(key, size)
                if data is not None and len(data) == size * size * 4:
                    found[key] = data
            # Emitted from this thread; the receiver lives on the UI thread,
            # so Qt queues it.
            self._arrived.emit((size, found))

    def _take(self, answer) -> None:
        size, found = answer
        if size != self._size:
            return
        added = False
        for key, data in found.items():
            image = QImage(data, size, size, size * 4,
                           QImage.Format_ARGB32_Premultiplied).copy()
            if image.isNull():
                continue
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(size / ROW_ICON)
            self._cache[key] = QIcon(pixmap)
            added = True
        if added:
            self.changed.emit()


_shared: FileIcons | None = None


def shared() -> FileIcons:
    global _shared
    if _shared is None:
        _shared = FileIcons()
    return _shared
