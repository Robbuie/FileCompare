"""The folder compare view: both trees as one, every row given its verdict.

One tree rather than two side by side. The names match on both sides by
definition -- that is what pairs them -- so a second name column would say the
same thing twice; what differs is size and time, and those sit either side of
a narrow verdict column, left then right, the way the text view puts the left
file on the left. A file that is only on one side has the other side's cells
empty, which reads as a gap the way a filler row does in the text view.

The difference colours are the text view's and mean the same things: red for
only on the left, green for only on the right, amber for on both and not the
same. A newer file's time is bold on the side that is newer.

Enter or a double-click on a file opens that pair in a tab of its own, in
whatever mode suits it. Nothing here reads a file: the walk, the verdicts and
the content compare are all `core/folderdiff.py`'s, off the UI thread.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core import folders as F
from app.core import syncplan as S
from app.core.folderdiff import FolderSession
from app.ui.diffview import mono_font, parse_colour

COLUMNS = ("Name", "Size", "Modified", "", "Modified", "Size")
NAME, LSIZE, LTIME, VERDICT, RTIME, RSIZE = range(6)

#: What the narrow middle column shows for each verdict. Words, not symbols:
#: colour carries it at a glance and the letters carry it for anyone who does
#: not see the colour.
MARKS = {
    F.SAME: "=",
    F.CONTENT_SAME: "=",
    F.HOUR_APART: "=",
    F.NEWER_LEFT: "<",
    F.NEWER_RIGHT: ">",
    F.DIFFERENT: "!=",
    F.CONTENT_DIFF: "!=",
    F.ONLY_LEFT: "<-",
    F.ONLY_RIGHT: "->",
    F.CLASH: "?",
    F.ERROR: "x",
}

SHOW_LABELS = (
    (F.SHOW_ALL, "All"),
    (F.SHOW_DIFFERENT, "Differences"),
    (F.SHOW_LEFT, "Left newer"),
    (F.SHOW_RIGHT, "Right newer"),
    (F.SHOW_SAME, "Same"),
)


def _size(entry: F.Entry | None) -> str:
    if entry is None or entry.is_dir:
        return ""
    n = entry.size
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return str(entry.size)


def _time(entry: F.Entry | None) -> str:
    if entry is None or entry.is_dir or not entry.mtime:
        return ""
    return _dt.datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M:%S")


class FolderModel(QAbstractItemModel):
    """The merged tree, filtered by the show setting, as Qt wants it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.root: F.Node | None = None
        self.show = F.SHOW_ALL
        self.tokens: dict[str, str] = {}
        self._kids: dict[int, list[F.Node]] = {}
        self._bold = QFont()
        self._bold.setBold(True)

    def set_tree(self, root: F.Node | None, show: str | None = None) -> None:
        self.beginResetModel()
        self.root = root
        if show is not None:
            self.show = show
        self._kids = {}
        self.endResetModel()

    def refresh(self) -> None:
        """The verdicts changed (a content compare): same shape, new colours."""
        self.set_tree(self.root)

    def kids(self, node: F.Node) -> list[F.Node]:
        found = self._kids.get(id(node))
        if found is None:
            found = [c for c in node.children if F.shown(c, self.show)]
            self._kids[id(node)] = found
        return found

    def node(self, index: QModelIndex) -> F.Node | None:
        if not index.isValid():
            return self.root
        return index.internalPointer()

    # ---------------------------------------------------------- Qt's model

    def index(self, row, column, parent=QModelIndex()):  # noqa: B008
        node = self.node(parent)
        if node is None:
            return QModelIndex()
        kids = self.kids(node)
        if 0 <= row < len(kids):
            return self.createIndex(row, column, kids[row])
        return QModelIndex()

    def parent(self, index=QModelIndex()):  # noqa: B008
        if not index.isValid():
            return QModelIndex()
        node: F.Node = index.internalPointer()
        up = node.parent
        if up is None or up is self.root:
            return QModelIndex()
        grand = up.parent or self.root
        row = self.kids(grand).index(up)
        return self.createIndex(row, 0, up)

    def rowCount(self, parent=QModelIndex()):  # noqa: N802, B008
        if parent.isValid() and parent.column() != 0:
            return 0
        node = self.node(parent)
        return len(self.kids(node)) if node is not None else 0

    def columnCount(self, parent=QModelIndex()):  # noqa: N802, B008
        return len(COLUMNS)

    def hasChildren(self, parent=QModelIndex()):  # noqa: N802, B008
        node = self.node(parent)
        return node is not None and bool(node.children) and bool(self.kids(node))

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if section in (LSIZE, RSIZE) \
                else int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node: F.Node = index.internalPointer()
        column = index.column()
        if role == Qt.DisplayRole:
            if column == NAME:
                if node.is_dir and node.files:
                    return node.name
                return node.name
            if column == LSIZE:
                return _size(node.left)
            if column == LTIME:
                return _time(node.left)
            if column == RSIZE:
                return _size(node.right)
            if column == RTIME:
                return _time(node.right)
            if column == VERDICT:
                if node.is_dir and node.status == F.DIFFERENT:
                    return f"{node.differing:,}"
                return MARKS.get(node.status, "")
            return None
        if role == Qt.ToolTipRole:
            if node.is_dir and node.status == F.DIFFERENT:
                return f"{node.differing:,} of {node.files:,} files below differ"
            text = F.LABELS.get(node.status, node.status)
            error = (node.left and node.left.error) or (node.right and node.right.error)
            return f"{text}: {error}" if error else text
        if role == Qt.TextAlignmentRole:
            if column in (LSIZE, RSIZE):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if column == VERDICT:
                return int(Qt.AlignCenter)
            return None
        if role == Qt.ForegroundRole:
            name = _ink(node.status)
            if column in (LSIZE, LTIME) and node.left is None:
                return None
            return QBrush(parse_colour(self.tokens.get(name))) if name else None
        if role == Qt.BackgroundRole:
            name = _wash(node.status)
            return QBrush(parse_colour(self.tokens.get(name))) if name else None
        if role == Qt.FontRole:
            if (column == LTIME and node.status == F.NEWER_LEFT) or \
                    (column == RTIME and node.status == F.NEWER_RIGHT):
                return self._bold
            if column == VERDICT:
                return self._bold
        return None


def _ink(status: str) -> str:
    return {
        F.ONLY_LEFT: "diff_del_bar",
        F.ONLY_RIGHT: "diff_add_bar",
        F.NEWER_LEFT: "diff_chg_bar",
        F.NEWER_RIGHT: "diff_chg_bar",
        F.DIFFERENT: "diff_chg_bar",
        F.CONTENT_DIFF: "diff_chg_bar",
        F.CLASH: "diff_del_bar",
        F.ERROR: "warn",
        F.CONTENT_SAME: "txt_2",
        F.HOUR_APART: "txt_2",
    }.get(status, "")


def _wash(status: str) -> str:
    return {
        F.ONLY_LEFT: "diff_del_row",
        F.ONLY_RIGHT: "diff_add_row",
        F.NEWER_LEFT: "diff_chg_row",
        F.NEWER_RIGHT: "diff_chg_row",
        F.DIFFERENT: "diff_chg_row",
        F.CONTENT_DIFF: "diff_chg_row",
        F.CLASH: "diff_del_row",
    }.get(status, "")


class FolderTree(QTreeView):
    """Keys: Enter opens, Alt+Up/Down steps through differences, and the
    tab's keys (swap, reload) go up as commands like the text view's."""

    command = Signal(str)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        if key in (Qt.Key_Return, Qt.Key_Enter) and mods == Qt.NoModifier:
            self.command.emit("open")
        elif mods == Qt.AltModifier and key == Qt.Key_Down:
            self.command.emit("next")
        elif mods == Qt.AltModifier and key == Qt.Key_Up:
            self.command.emit("previous")
        elif mods == Qt.ControlModifier and key == Qt.Key_U:
            self.command.emit("swap")
        elif mods == Qt.ControlModifier and key == Qt.Key_R:
            self.command.emit("reload")
        elif mods == Qt.ControlModifier and key == Qt.Key_C:
            self.command.emit("copy-path")
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class FolderView(QWidget):
    """Emits `openPair(left, right)` for a file pair to compare in a tab."""

    openPair = Signal(str, str)
    #: 1.9: a pair extracted from zips: (left, right, titles), opened read-only.
    openExtracted = Signal(str, str, object)
    status = Signal(str)
    #: Keys that belong to the tab: "swap", "reload".
    command = Signal(str)
    #: A folder setting to keep for next time: (config key, value).
    setting = Signal(str, object)

    def __init__(self, session: FolderSession, tokens: dict[str, str], *,
                 mask: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.model = FolderModel(self)
        self.tree = FolderTree()
        self.tree.setModel(self.model)
        self.tree.setProperty("role", "foldertree")
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        session.extracted.connect(self.openExtracted)
        self.tree.doubleClicked.connect(lambda _i: self._open())
        self.tree.command.connect(self._command)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME, QHeaderView.Stretch)
        for column in (LSIZE, LTIME, VERDICT, RTIME, RSIZE):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(36)

        self.shows: dict[str, QPushButton] = {}
        segments = QWidget()
        segments.setProperty("role", "segments")
        segments.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(segments)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(2)
        for value, label in SHOW_LABELS:
            button = QPushButton(label)
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, v=value: self.set_show(v))
            seg.addWidget(button)
            self.shows[value] = button
        self.mask = QLineEdit(mask)
        self.mask.setProperty("role", "findfield")
        self.mask.setPlaceholderText("Names: *.L5X;*.ini  -.git;-*.bak")
        self.mask.setToolTip("Which names take part. Patterns separated by ; -- a "
                             "leading - leaves a name out, files or folders.")
        self._mask_timer = QTimer(self)
        self._mask_timer.setSingleShot(True)
        self._mask_timer.setInterval(400)
        self._mask_timer.timeout.connect(lambda: self.session.set_mask(self.mask.text()))
        self.mask.textChanged.connect(lambda _t: self._mask_timer.start())
        self.contents = QToolButton()
        self.contents.setText("Compare contents")
        self.contents.setProperty("role", "retry")
        self.contents.setPopupMode(QToolButton.MenuButtonPopup)
        self.contents.setFocusPolicy(Qt.NoFocus)
        self.contents.setToolTip("Read the files whose size and time cannot settle it: "
                                 "same size, different time")
        self.contents.clicked.connect(lambda _c=False: self._contents())
        menu = QMenu(self)
        menu.addAction("Same size, different time", self._contents)
        menu.addAction("Every pair on both sides", lambda: self._contents(all_pairs=True))
        menu.addAction("The selected rows", self._contents_selected)
        menu.addSeparator()
        menu.addAction("Stop", self.session.cancel_contents)
        # 1.8: two ways of not trusting the clock.
        menu.addSeparator()
        self._always = menu.addAction("Always compare contents")
        self._always.setCheckable(True)
        self._always.setChecked(self.session.by_content)
        self._always.setToolTip("After every walk, read every pair with the same size, so "
                                "a file only counts as different when its bytes are")
        self._always.toggled.connect(self._set_by_content)
        self._hour = menu.addAction("Ignore a one-hour shift (clock change)")
        self._hour.setCheckable(True)
        self._hour.setChecked(self.session.hour)
        self._hour.toggled.connect(self._set_hour)
        self._zips = menu.addAction("Look inside .zip files")
        self._zips.setCheckable(True)
        self._zips.setChecked(self.session.archives)
        self._zips.setToolTip("List each zip's files under it and compare them by size "
                              "and CRC, without unpacking anything")
        self._zips.toggled.connect(self._set_archives)
        menu.setToolTipsVisible(True)
        self.contents.setMenu(menu)
        # 1.0: sync, handed to File Manager's queue (`ui/syncdialog.py`).
        self.sync = QToolButton()
        self.sync.setText("Sync")
        self.sync.setProperty("role", "retry")
        self.sync.setPopupMode(QToolButton.MenuButtonPopup)
        self.sync.setFocusPolicy(Qt.NoFocus)
        self.sync.setToolTip("Make one side match the other: previewed here, then run "
                             "by File Manager's queue")
        self.sync.clicked.connect(lambda _c=False: self.open_sync(S.TO_RIGHT, S.UPDATE))
        sync_menu = QMenu(self)
        sync_menu.addAction("Update left to right",
                            lambda: self.open_sync(S.TO_RIGHT, S.UPDATE))
        sync_menu.addAction("Update right to left",
                            lambda: self.open_sync(S.TO_LEFT, S.UPDATE))
        sync_menu.addSeparator()
        sync_menu.addAction("Mirror left to right",
                            lambda: self.open_sync(S.TO_RIGHT, S.MIRROR))
        sync_menu.addAction("Mirror right to left",
                            lambda: self.open_sync(S.TO_LEFT, S.MIRROR))
        sync_menu.addSeparator()
        self._stop_waiting = sync_menu.addAction("Stop waiting for File Manager",
                                                 self.session.forget_sync)
        sync_menu.aboutToShow.connect(
            lambda: self._stop_waiting.setEnabled(self.session.syncing))
        self.sync.setMenu(sync_menu)
        self.expand = QToolButton()
        self.expand.setText("Expand")
        self.expand.setProperty("role", "retry")
        self.expand.setFocusPolicy(Qt.NoFocus)
        self.expand.clicked.connect(lambda _c=False: self.tree.expandAll())
        self.collapse = QToolButton()
        self.collapse.setText("Collapse")
        self.collapse.setProperty("role", "retry")
        self.collapse.setFocusPolicy(Qt.NoFocus)
        self.collapse.clicked.connect(lambda _c=False: self.tree.collapseAll())
        self.line = QLabel()
        self.line.setProperty("role", "count")

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(6)
        bar.addWidget(segments)
        bar.addWidget(self.mask, 1)
        bar.addWidget(self.contents)
        bar.addWidget(self.sync)
        bar.addWidget(self.expand)
        bar.addWidget(self.collapse)
        top = QWidget()
        top.setProperty("role", "folderbar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setLayout(bar)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(top)
        box.addWidget(self.line)
        box.addWidget(self.tree, 1)

        session.changed.connect(self.refresh)
        session.progressed.connect(self._progress)
        session.handed.connect(self._handed)
        session.remote.connect(self._remote)
        self._dialog = None
        self.apply_tokens(tokens)
        self.set_show(F.SHOW_ALL, rebuild=False)
        self.refresh()

    # ----------------------------------------------------------- drawing

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.model.tokens = tokens
        self.tree.setFont(mono_font(tokens))
        self.tree.viewport().update()

    def refresh(self) -> None:
        tree = self.session.tree
        if tree is not self.model.root:
            self.model.set_tree(tree)
            if tree is not None:
                self._expand_differences()
        else:
            self.model.refresh()
            if tree is not None:
                self._expand_differences()
        self._progress()

    def _progress(self) -> None:
        text = self.session.status()
        self.line.setText(text)
        self.contents.setEnabled(self.session.tree is not None)
        self.sync.setEnabled(self.session.tree is not None or self.session.syncing)
        if self.session.syncing:
            text += "  ·  waiting for File Manager's queue"
            self.line.setText(text)
        self.status.emit(text)

    def _expand_differences(self) -> None:
        """Open the folders that hold differences, down to a sensible depth.
        A tree that opens collapsed hides the answer; one that opens fully
        expanded on fifty thousand files hides it differently."""
        def walk(parent: QModelIndex, depth: int) -> None:
            for row in range(self.model.rowCount(parent)):
                index = self.model.index(row, 0, parent)
                node = self.model.node(index)
                if node.is_dir and node.differing and depth < 3 and node.differing < 400:
                    self.tree.expand(index)
                    walk(index, depth + 1)
        walk(QModelIndex(), 0)

    def set_show(self, show: str, rebuild: bool = True) -> None:
        for value, button in self.shows.items():
            button.setChecked(value == show)
        if rebuild or self.model.show != show:
            self.model.set_tree(self.model.root, show)
            if self.model.root is not None:
                self._expand_differences()

    # ----------------------------------------------------------- actions

    def selected(self) -> list[F.Node]:
        rows = self.tree.selectionModel().selectedRows(0) if self.tree.selectionModel() else []
        return [self.model.node(index) for index in rows]

    def _open(self) -> None:
        for node in self.selected()[:8]:
            if node.is_dir:
                continue
            if node.member:
                if self.session.open_member(node):
                    self.status.emit(f"Opening {node.name} from the zip...")
                else:
                    self.status.emit("Still opening the last one from a zip")
                continue
            left, right = self.session.paths(node)
            if node.left is None:
                left = ""
            if node.right is None:
                right = ""
            self.openPair.emit(left, right)

    # ----------------------------------------------------------- sync

    def open_sync(self, direction: str, mode: str, nodes=None) -> None:
        """The preview, and on its OK the handoff. Nothing is sent from here
        that the preview did not show with its box ticked."""
        session = self.session
        if session.tree is None or session.building:
            return
        if session.syncing:
            self.status.emit("A sync is already with File Manager; this comparison is "
                             "read again when it finishes.")
            return
        from app.ui.syncdialog import SyncDialog

        dialog = SyncDialog(session.tree, session.sides[0].path, session.sides[1].path,
                            direction=direction, mode=mode, nodes=nodes,
                            titles=(session.sides[0].title, session.sides[1].title),
                            tokens=self.model.tokens, parent=self)
        self._dialog = dialog
        session.check_remote()
        try:
            accepted = dialog.exec()
        finally:
            self._dialog = None
        if accepted and dialog.request:
            session.send_sync(dialog.request)

    def _picked(self, direction: str, mode: str) -> None:
        nodes = self.selected()
        if nodes:
            self.open_sync(direction, mode, nodes)

    def _remote(self, sides) -> None:
        if self._dialog is not None:
            self._dialog.set_remote(tuple(sides))

    def _handed(self, text: str) -> None:
        self.line.setText(text)
        self.status.emit(text)
        # The line keeps the handoff's words; only the button follows the state.
        self.sync.setEnabled(self.session.tree is not None or self.session.syncing)

    def _set_by_content(self, on: bool) -> None:
        self.session.set_by_content(on)
        self.setting.emit("folders.by_content", bool(on))
        self.status.emit("Every pair with the same size is read after each walk" if on
                         else "Pairs are judged by size and time; Compare contents reads them")

    def _set_archives(self, on: bool) -> None:
        self.session.set_archives(on)
        self.setting.emit("folders.archives", bool(on))

    def _set_hour(self, on: bool) -> None:
        self.session.set_hour(on)
        self.setting.emit("folders.ignore_hour", bool(on))
        self.status.emit("Files the same size exactly an hour apart count as the same"
                         if on else "An hour's difference counts as newer")

    def _contents(self, all_pairs: bool = False) -> None:
        count = self.session.compare_contents(all_pairs=all_pairs)
        if not count:
            self.status.emit("Nothing to read: every pair is settled by size and time"
                             if not all_pairs else "No file pairs to read")

    def _contents_selected(self) -> None:
        nodes = []
        for node in self.selected():
            nodes.extend([node] if not node.is_dir else [n for n in node.walk() if n.pair])
        self.session.compare_contents(nodes=nodes)

    def _step(self, direction: int) -> None:
        """Alt+Down / Alt+Up: the next file that differs, opening folders."""
        order = [n for n in self.model.root.walk() if not n.is_dir and n.differs
                 and F.shown(n, self.model.show)] if self.model.root else []
        if not order:
            return
        current = self.selected()
        here = order.index(current[0]) if current and current[0] in order else -1
        target = order[(here + direction) % len(order)] if here >= 0 else (
            order[0] if direction > 0 else order[-1])
        self._select(target)

    def _select(self, node: F.Node) -> None:
        chain = []
        up = node
        while up is not None and up is not self.model.root:
            chain.append(up)
            up = up.parent
        parent = QModelIndex()
        index = QModelIndex()
        for step in reversed(chain):
            kids = self.model.kids(self.model.node(parent))
            if step not in kids:
                return
            index = self.model.index(kids.index(step), 0, parent)
            if step is not node:
                self.tree.expand(index)
            parent = index
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index, QAbstractItemView.PositionAtCenter)

    def _command(self, name: str) -> None:
        if name == "open":
            nodes = self.selected()
            if len(nodes) == 1 and nodes[0].is_dir:
                index = self.tree.currentIndex()
                self.tree.setExpanded(index, not self.tree.isExpanded(index))
            else:
                self._open()
        elif name == "next":
            self._step(1)
        elif name == "previous":
            self._step(-1)
        elif name in ("swap", "reload"):
            self.command.emit(name)
        elif name == "copy-path":
            paths = []
            for node in self.selected():
                left, right = self.session.paths(node)
                paths.append(left if node.left is not None else right)
            QApplication.clipboard().setText("\n".join(paths))

    def _context(self, point) -> None:
        nodes = self.selected()
        if not nodes:
            return
        menu = QMenu(self)
        files = [n for n in nodes if not n.is_dir]
        if files:
            menu.addAction("Compare in a new tab\tEnter", self._open)
        menu.addAction("Compare contents", self._contents_selected)
        menu.addSeparator()
        ready = not self.session.syncing
        for label, direction, mode in (("Copy to the right...", S.TO_RIGHT, S.COPY),
                                       ("Copy to the left...", S.TO_LEFT, S.COPY),
                                       ("Remove from the left...", S.TO_LEFT, S.REMOVE),
                                       ("Remove from the right...", S.TO_RIGHT, S.REMOVE)):
            action = menu.addAction(label, lambda d=direction, m=mode: self._picked(d, m))
            action.setEnabled(ready)
        menu.addSeparator()
        node = nodes[0]
        left, right = self.session.paths(node)
        if node.left is not None:
            menu.addAction("Copy left path",
                           lambda: QApplication.clipboard().setText(left))
        if node.right is not None:
            menu.addAction("Copy right path",
                           lambda: QApplication.clipboard().setText(right))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.tree.viewport().mapToGlobal(point))

    def focus(self) -> None:
        self.tree.setFocus(Qt.OtherFocusReason)
