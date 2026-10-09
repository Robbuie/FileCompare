"""Home: what a new tab shows (1.21; the plain start page before that).

Beyond Compare's Home, in this application's terms:

- **Saved sessions** down the left, in folders of your own -- the comparisons
  made every week, a double-click away. Right-click one to rename it, move it
  to another folder, or remove it. A comparison is added with Session > Add
  to Home.
- **A quick compare row**: a path for each side, Browse, and Compare.
- **A tile for each kind of comparison**: folders, text, tables, hex,
  images, a three-way merge, PDFs and drawings (which go to Redline PDF and
  DWG Viewer), and a saved session file. A tile sets what the row compares
  as, and its Browse picks folders or files to suit.
- **Recent comparisons**, newest first, each with what it found last time.

Nothing here checks that a path exists. A typed path is handed to the session
as it is, and the session finds out off the UI thread; a missing file becomes
a side that says "Not found", which is a better answer than a field that turns
red while somebody is still typing into it. The browse buttons are the one
exception to the rule about the filesystem, and a narrow one: they are
Windows' own file dialogs, which run their own loops and are somebody asking.
"""

from __future__ import annotations

import ntpath
import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import library
from app.ui import glyphs

#: The tiles: (mode, glyph, title, what it does). Mode "" is no change.
TILES = (
    ("folder", "folder", "Folders", "Trees or a sync list",
     "Two trees or a sync list; copies run in File Manager"),
    ("text", "layout_sbs", "Text", "Side by side or unified",
     "Side by side, fluid or unified, and editable"),
    ("table", "contents", "Table", "CSV and Excel by key",
     "CSV and Excel, rows matched on a key"),
    ("hex", "show_all", "Hex", "Byte by byte", "Byte by byte, for firmware and binaries"),
    ("image", "view", "Image", "Overlay, swipe, blink", "Side by side, overlay, swipe, blink"),
    ("merge", "structure", "Three-way merge", "Mine, base and theirs",
     "Mine, base and theirs into one output"),
    ("sibling", "report", "PDF and drawings", "Redline PDF, DWG Viewer",
     "Opens the pair in Redline PDF or DWG Viewer"),
    ("session", "sessions", "Saved session", "Open a .fcsession file",
     "Open a comparison saved as a .fcsession file"),
)

ROLE = Qt.UserRole + 1


def when(stamp: float, now: float | None = None) -> str:
    """A time as a person says it: today's as a time, then Yesterday, the
    weekday within a week, and a date after that."""
    if not stamp:
        return ""
    now = now or time.time()
    then, today = time.localtime(stamp), time.localtime(now)
    days = (time.mktime(today[:3] + (0, 0, 0, 0, 0, -1))
            - time.mktime(then[:3] + (0, 0, 0, 0, 0, -1))) / 86400
    if days < 0.5:
        return "Today " + time.strftime("%H:%M", then)
    if days < 1.5:
        return "Yesterday"
    if days < 7:
        return time.strftime("%A", then)
    return time.strftime("%Y-%m-%d", then)


class Tile(QToolButton):
    def __init__(self, mode: str, glyph: str, title: str, text: str, tip: str) -> None:
        super().__init__()
        self.mode = mode
        self.glyph = glyph
        self.setProperty("role", "tile")
        self.setCheckable(mode not in ("merge", "session"))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(28, 28))
        self.setText(f"{title}\n{text}")
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.TabFocus)
        from PySide6.QtWidgets import QSizePolicy

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(62)
        self.setMinimumWidth(150)


class StartTab(QWidget):
    """Home. Emits `compareRequested(left, right)` (with `mode` set),
    `sessionRequested(path)` for a session file, `savedRequested(text)` for a
    session kept on Home, `mergeRequested(mine, theirs, base)`, and
    `libraryChanged(entries)` after a rename, move or removal."""

    compareRequested = Signal(str, str)
    browsed = Signal(int, str)          # side, the folder browsed from
    sessionRequested = Signal(str)      # 1.10: a .fcsession file to open
    savedRequested = Signal(str)        # 1.21: a session kept on Home
    mergeRequested = Signal(str, str, str)
    libraryChanged = Signal(object)

    def __init__(self, folders: tuple[str, str] = ("", ""),
                 parent: QWidget | None = None, *,
                 recent: list[tuple[str, str]] | None = None,
                 notes: dict | None = None,
                 sessions: list[dict] | None = None) -> None:
        super().__init__(parent)
        self._folders = list(folders)
        self._recent = list(recent or [])
        self._notes = dict(notes or {})
        self.sessions = library.clean(sessions or [])
        #: What the quick row compares as: "auto", "folder", "text", ...
        self.mode = "auto"
        self.setAcceptDrops(True)

        # --- the saved sessions, down the left
        self.tree = QTreeWidget()
        self.tree.setProperty("role", "sessions")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._session_menu)
        self.tree.itemActivated.connect(self._open_item)
        self.tree.itemDoubleClicked.connect(self._open_item)
        head = QLabel("Saved sessions")
        head.setProperty("role", "sidelabel")
        self.empty = QLabel("Compare something, then Session > Add to Home keeps it here.")
        self.empty.setProperty("role", "hint")
        self.empty.setWordWrap(True)
        side = QWidget()
        side.setProperty("role", "homeside")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side_box = QVBoxLayout(side)
        side_box.setContentsMargins(12, 12, 6, 12)
        side_box.setSpacing(6)
        side_box.addWidget(head)
        side_box.addWidget(self.tree, 1)
        side_box.addWidget(self.empty)
        side.setMinimumWidth(220)

        # --- the quick row
        title = QLabel("Compare")
        title.setProperty("role", "starttitle")
        self.note = QLabel("Choose or paste a path for each side, drop two files or folders "
                           "here, or pick a kind of comparison below.")
        self.note.setProperty("role", "note")
        self.note.setWordWrap(True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.fields: list[QLineEdit] = []
        for row, name in enumerate(("LEFT", "RIGHT")):
            label = QLabel(name)
            label.setProperty("role", "sidelabel")
            field = QLineEdit()
            field.setProperty("role", "pathfield")
            field.setPlaceholderText("C:\\path\\to\\file.txt  or  \\\\server\\share\\folder")
            field.textChanged.connect(self._update)
            field.returnPressed.connect(self._go)
            browse = QPushButton("Browse")
            browse.clicked.connect(lambda _c=False, r=row: self._browse(r))
            grid.addWidget(label, row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(browse, row, 2)
            self.fields.append(field)
        self.go = QPushButton("Compare")
        self.go.setProperty("role", "primary")
        self.go.clicked.connect(self._go)
        hint = QLabel("From File Manager: Ctrl+F2 compares the two panes, "
                      "Alt+F2 the marked files.")
        hint.setProperty("role", "hint")
        self.open_session = QPushButton("Open session")
        self.open_session.setToolTip("A comparison saved with Ctrl+Alt+S: the same two paths, "
                                     "rules, filter and pins")
        self.open_session.clicked.connect(self._browse_session)
        buttons = QHBoxLayout()
        buttons.addWidget(hint, 1)
        buttons.addWidget(self.open_session)
        buttons.addWidget(self.go)

        # --- the tiles
        kinds = QLabel("New comparison")
        kinds.setProperty("role", "sidelabel")
        tiles = QGridLayout()
        tiles.setSpacing(8)
        self.tiles: list[Tile] = []
        for number, (mode, glyph, name, text, tip) in enumerate(TILES):
            tile = Tile(mode, glyph, name, text, tip)
            tile.clicked.connect(lambda _c=False, t=tile: self._tile(t))
            tiles.addWidget(tile, number // 4, number % 4)
            self.tiles.append(tile)
        for column in range(4):
            tiles.setColumnStretch(column, 1)

        # --- recent
        recent_label = QLabel("Recent")
        recent_label.setProperty("role", "sidelabel")
        self.recent = QTreeWidget()
        self.recent.setProperty("role", "recentlist")
        self.recent.setRootIsDecorated(False)
        self.recent.setHeaderHidden(True)
        self.recent.setColumnCount(3)
        self.recent.itemActivated.connect(self._open_recent)
        self.recent.itemClicked.connect(self._open_recent)
        for left, right in self._recent[:10]:
            note, stamp = self._notes.get(f"{left}\n{right}", ("", 0))
            item = QTreeWidgetItem([f"{left}   \u2194   {right}", note, when(stamp)])
            item.setToolTip(0, f"{left}\n{right}")
            item.setData(0, ROLE, (left, right))
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            self.recent.addTopLevelItem(item)
        header = self.recent.header()
        header.setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView

        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recent.setVisible(bool(self._recent))
        recent_label.setVisible(bool(self._recent))

        main = QFrame()
        main.setProperty("role", "start")
        inner = QVBoxLayout(main)
        inner.setContentsMargins(26, 20, 26, 20)
        inner.setSpacing(10)
        inner.addWidget(title)
        inner.addWidget(self.note)
        inner.addLayout(grid)
        inner.addLayout(buttons)
        inner.addSpacing(6)
        inner.addWidget(kinds)
        inner.addLayout(tiles)
        inner.addSpacing(6)
        inner.addWidget(recent_label)
        inner.addWidget(self.recent, 1)
        if not self._recent:
            inner.addStretch(1)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(side)
        split.addWidget(main)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 1000])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.addWidget(split)
        self._fill_sessions()
        self._update()

    # ---------------------------------------------------------- for window

    def title(self) -> str:
        return "Home"

    def tooltip(self) -> str:
        return ""

    def page_kind(self) -> str:
        return "start"

    def command_state(self, id_: str):
        from app.ui.commands import HIDDEN

        return HIDDEN

    def run_command(self, id_: str) -> None:
        pass

    def fill_menu(self, name: str, menu) -> None:
        pass

    def focus_view(self) -> None:
        self.fields[0].setFocus(Qt.OtherFocusReason)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        ratio = float(self.devicePixelRatioF() or 1.0)
        for tile in self.tiles:
            tile.setIcon(glyphs.icon(tile.glyph, colour=tokens["accent"], muted=tokens["txt_2"],
                                     size=28, ratio=ratio))

    def set_paths(self, left: str = "", right: str = "") -> None:
        if left:
            self.fields[0].setText(left)
        if right:
            self.fields[1].setText(right)

    def set_sessions(self, entries: list[dict]) -> None:
        self.sessions = library.clean(entries)
        self._fill_sessions()

    # ---------------------------------------------------------- sessions

    def _fill_sessions(self) -> None:
        self.tree.clear()
        for folder in library.folders(self.sessions):
            top = QTreeWidgetItem([folder])
            top.setData(0, ROLE, None)
            top.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for index, entry in enumerate(self.sessions):
                if entry["folder"] != folder:
                    continue
                item = QTreeWidgetItem([entry["name"]])
                item.setData(0, ROLE, index)
                item.setToolTip(0, library.describe(entry))
                top.addChild(item)
            top.setExpanded(True)
        self.empty.setVisible(not self.sessions)

    def _open_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        index = item.data(0, ROLE)
        if isinstance(index, int) and 0 <= index < len(self.sessions):
            self.savedRequested.emit(self.sessions[index]["text"])

    def _session_menu(self, point) -> None:
        item = self.tree.itemAt(point)
        index = item.data(0, ROLE) if item is not None else None
        if not isinstance(index, int):
            return
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open_item(item))
        menu.addSeparator()
        menu.addAction("Rename...", lambda: self._rename(index))
        move = menu.addMenu("Move to")
        for folder in library.folders(self.sessions):
            if folder != self.sessions[index]["folder"]:
                move.addAction(folder, lambda f=folder: self._change(
                    library.move(self.sessions, index, f)))
        move.addSeparator()
        move.addAction("New folder...", lambda: self._new_folder(index))
        menu.addSeparator()
        menu.addAction("Remove from Home", lambda: self._change(
            library.remove(self.sessions, index)))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.tree.viewport().mapToGlobal(point))

    def _rename(self, index: int) -> None:
        name, ok = QInputDialog.getText(self, "Rename", "Name:",
                                        text=self.sessions[index]["name"])
        if ok and name.strip():
            self._change(library.rename(self.sessions, index, name))

    def _new_folder(self, index: int) -> None:
        name, ok = QInputDialog.getText(self, "New folder", "Folder:")
        if ok and name.strip():
            self._change(library.move(self.sessions, index, name))

    def _change(self, entries: list[dict]) -> None:
        self.sessions = entries
        self._fill_sessions()
        self.libraryChanged.emit(entries)

    # ---------------------------------------------------------- the row

    def _update(self) -> None:
        self.go.setEnabled(all(field.text().strip() for field in self.fields))

    def _go(self) -> None:
        left, right = (field.text().strip().strip('"') for field in self.fields)
        if left and right:
            self.compareRequested.emit(left, right)

    def _tile(self, tile: Tile) -> None:
        if tile.mode == "merge":
            self._browse_merge()
            return
        if tile.mode == "session":
            self._browse_session()
            return
        on = tile.isChecked()
        for other in self.tiles:
            if other is not tile:
                other.setChecked(False)
        self.mode = tile.mode if on and tile.mode != "sibling" else "auto"
        words = {"folder": "two folders", "text": "two files, as text",
                 "table": "two CSV or Excel files", "hex": "two files, byte by byte",
                 "image": "two pictures", "sibling": "two PDFs or drawings"}
        self.note.setText(f"Choose {words.get(tile.mode, 'two files')} and press Compare."
                          if on else "Choose or paste a path for each side, drop two files "
                          "or folders here, or pick a kind of comparison below.")
        if on:
            self.fields[0].setFocus(Qt.OtherFocusReason)

    def _browse(self, side: int) -> None:
        start = self.fields[side].text().strip() or self._folders[side] or self._folders[1 - side]
        which = "left" if side == 0 else "right"
        if self.mode == "folder":
            path = QFileDialog.getExistingDirectory(self, f"Choose the {which} folder", start)
        else:
            path, _filter = QFileDialog.getOpenFileName(self, f"Choose the {which} file", start)
        if path:
            path = path.replace("/", "\\")
            self.fields[side].setText(path)
            self._folders[side] = path if self.mode == "folder" else ntpath.dirname(path)
            self.browsed.emit(side, self._folders[side])
            if not self.fields[1 - side].text().strip():
                self.fields[1 - side].setFocus()

    def _browse_session(self) -> None:
        start = self._folders[0] or self._folders[1]
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a saved session", start, "File Compare session (*.fcsession)")
        if path:
            self.sessionRequested.emit(path.replace("/", "\\"))

    def _browse_merge(self) -> None:
        start = self._folders[0] or self._folders[1]
        picked = []
        for which in ("yours (mine)", "theirs", "the common base"):
            path, _filter = QFileDialog.getOpenFileName(self, f"Choose {which}", start)
            if not path:
                return
            picked.append(path.replace("/", "\\"))
            start = ntpath.dirname(picked[-1])
        self.mergeRequested.emit(*picked)

    def _open_recent(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        pair = item.data(0, ROLE)
        if pair:
            self.mode = "auto"
            self.compareRequested.emit(*pair)

    # ------------------------------------------------------------ dropping

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [url.toLocalFile().replace("/", "\\") for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if not paths:
            return
        event.acceptProposedAction()
        if len(paths) == 1 and paths[0].lower().endswith(".fcsession"):
            self.sessionRequested.emit(paths[0])
            return
        if len(paths) >= 2:
            self.set_paths(paths[0], paths[1])
            self._go()
            return
        # One file: the side it was dropped on, or the empty side.
        over_right = event.position().x() > self.width() / 2
        empty = [i for i, field in enumerate(self.fields) if not field.text().strip()]
        side = 1 if over_right else 0
        if empty and side not in empty:
            side = empty[0]
        self.fields[side].setText(paths[0])
        if all(field.text().strip() for field in self.fields):
            self._go()
