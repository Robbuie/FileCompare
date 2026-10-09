"""The sync list view of a folder compare (1.20).

One list instead of two trees: the left file's size and time, what will
happen in the middle, the right file's time and size, and the result in
words -- Total and Double Commander's Synchronize Directories. The two trees
stay; this is the other way to look at the same comparison, chosen from the
toolbar, for when the question is "what do I copy" rather than "what is
where". The decisions are `core/synclist.py`'s; this draws them and turns
clicks into them.

- The arrow in the middle is the action. A click on it cycles copy right,
  copy left and leave alone, as far as the row allows.
- The box before the name is the same choice as a switch: unticked is
  "leave alone", ticked is the default action again.
- The plan under the list says how much goes each way, and its button hands
  it to File Manager's queue, as Sync does.

Nothing here reads a file: the tree is the folder session's, and the icons
come from the same shell-icon cache as the trees.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core import folders as F
from app.core import synclist as L
from app.ui import fileicons
from app.ui.diffview import parse_colour

COLUMNS = ("Name", "Size", "Modified", "Action", "Modified", "Size", "Result")
NAME, LSIZE, LTIME, ACTION, RTIME, RSIZE, RESULT = range(7)

ARROWS = {L.RIGHT: "→", L.LEFT: "←", L.SKIP: ""}

INK = {
    L.ONLY_LEFT: "dir_left_bar",
    L.ONLY_RIGHT: "dir_right_bar",
    L.LEFT_NEWER: "dir_newer_bar",
    L.RIGHT_NEWER: "dir_newer_bar",
    L.DIFFERENT: "dir_newer_bar",
    L.SAME: "",
}


def _size(entry) -> str:
    from app.ui.folderview import _size as size

    return size(entry)


def _time(entry) -> str:
    if entry is None or entry.is_dir or not entry.mtime:
        return ""
    import datetime as _dt

    return _dt.datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M")


class SyncModel(QAbstractItemModel):
    def __init__(self, parent=None, icons: fileicons.FileIcons | None = None) -> None:
        super().__init__(parent)
        self.root: F.Node | None = None
        self.decisions = L.Decisions()
        self.shown: set[str] = set(L.DEFAULT_SHOWN)
        self.tokens: dict[str, str] = {}
        self.icons = icons if icons is not None else fileicons.shared()
        self._kids: dict[int, list[F.Node]] = {}
        self._visible: dict[int, bool] = {}
        self._bold = QFont()

    # -------------------------------------------------------------- content

    def set_tree(self, root: F.Node | None) -> None:
        self.beginResetModel()
        self.root = root
        self.decisions = L.decide(root, self.decisions) if root is not None else L.Decisions()
        self._kids, self._visible = {}, {}
        self.endResetModel()

    def set_shown(self, shown: set[str]) -> None:
        self.beginResetModel()
        self.shown = set(shown)
        self._kids, self._visible = {}, {}
        self.endResetModel()

    def counts(self) -> dict[str, int]:
        """Files (and one-sided folders) in each category, for the toolbar."""
        out = dict.fromkeys(L.CATEGORIES, 0)
        if self.root is None:
            return out
        for node in self.root.walk():
            if node is self.root or node.member:
                continue
            if node.is_dir and node.status not in (F.ONLY_LEFT, F.ONLY_RIGHT):
                continue
            if L.inside_whole(node) is not None:
                continue            # counted as its folder
            out[L.category(node)] += 1
        return out

    def visible(self, node: F.Node) -> bool:
        key = id(node)
        hit = self._visible.get(key)
        if hit is not None:
            return hit
        if node.is_dir and node.status not in (F.ONLY_LEFT, F.ONLY_RIGHT):
            hit = any(self.visible(child) for child in node.children)
        else:
            hit = L.category(node) in self.shown
        self._visible[key] = hit
        return hit

    def kids(self, node: F.Node) -> list[F.Node]:
        hit = self._kids.get(id(node))
        if hit is None:
            hit = [child for child in node.children if self.visible(child)]
            self._kids[id(node)] = hit
        return hit

    def node(self, index: QModelIndex) -> F.Node | None:
        if not index.isValid():
            return self.root
        return index.internalPointer()

    def cycle(self, index: QModelIndex) -> None:
        node = self.node(index)
        if node is None or not L.choices(node):
            return
        self.decisions.cycle(node)
        self._changed_row(index)

    def set_action(self, nodes: list[F.Node], action: str) -> int:
        """Set an action on several rows; returns how many allowed it."""
        done = 0
        for node in nodes:
            if action in L.choices(node):
                self.decisions.set(node, action)
                done += 1
        self.layoutChanged.emit()
        return done

    def _changed_row(self, index: QModelIndex) -> None:
        left = self.index(index.row(), 0, index.parent())
        right = self.index(index.row(), len(COLUMNS) - 1, index.parent())
        self.dataChanged.emit(left, right)

    # ---------------------------------------------------------- the model

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
        node = index.internalPointer()
        up = node.parent
        if up is None or up is self.root:
            return QModelIndex()
        grand = up.parent or self.root
        kids = self.kids(grand)
        return self.createIndex(kids.index(up), 0, up) if up in kids else QModelIndex()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802, B008
        if parent.isValid() and parent.column() != 0:
            return 0
        node = self.node(parent)
        if node is None or not (node is self.root or node.is_dir):
            return 0
        return len(self.kids(node))

    def columnCount(self, parent=QModelIndex()):  # noqa: N802, B008
        return len(COLUMNS)

    def hasChildren(self, parent=QModelIndex()):  # noqa: N802, B008
        node = self.node(parent)
        return node is not None and (node is self.root or node.is_dir) and bool(self.kids(node))

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            if section in (LSIZE, LTIME, RSIZE):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if section == ACTION:
                return int(Qt.AlignCenter)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        node = self.node(index)
        if index.column() == NAME and node is not None and L.choices(node):
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.EditRole):  # noqa: N802
        if role != Qt.CheckStateRole or index.column() != NAME:
            return False
        node = self.node(index)
        options = L.choices(node)
        if not options:
            return False
        on = Qt.CheckState(value) == Qt.Checked
        if on:
            default = self.decisions.defaults.get(node.rel.lower(), L.SKIP)
            self.decisions.set(node, default if default != L.SKIP else options[0])
        else:
            self.decisions.set(node, L.SKIP)
        self._changed_row(index)
        return True

    def data(self, index, role=Qt.DisplayRole):
        node = self.node(index)
        if node is None or not index.isValid():
            return None
        column = index.column()
        category = L.category(node)
        if role == Qt.DisplayRole:
            if column == NAME:
                return node.name
            if column == LSIZE:
                return _size(node.left) if not node.is_dir else ""
            if column == LTIME:
                return _time(node.left)
            if column == RTIME:
                return _time(node.right)
            if column == RSIZE:
                return _size(node.right) if not node.is_dir else ""
            if column == RESULT:
                return L.result(node)
            return None
        if role == Qt.CheckStateRole and column == NAME and L.choices(node):
            return Qt.Checked if self.decisions.action(node) != L.SKIP else Qt.Unchecked
        if role == Qt.DecorationRole and column == NAME:
            return self.icons.icon(node.name, node.is_dir, self.tokens.get("txt_1", ""),
                                   self.tokens.get("txt_2", ""))
        if role == Qt.ForegroundRole and column != RESULT:
            name = INK.get(category, "")
            if node.is_dir and node.status not in (F.ONLY_LEFT, F.ONLY_RIGHT):
                name = "dir_newer_bar" if node.differing else ""
            if name and self.tokens:
                # The older side of a newer pair is drawn in grey, Beyond
                # Compare's way: the colour is on the side that would win.
                if column in (LSIZE, LTIME) and category == L.RIGHT_NEWER or \
                        column in (RSIZE, RTIME) and category == L.LEFT_NEWER:
                    return QBrush(parse_colour(self.tokens.get("txt_2")))
                return QBrush(parse_colour(self.tokens.get(name)))
            return None
        if role == Qt.FontRole:
            if column in (LTIME, LSIZE) and category == L.LEFT_NEWER or \
                    column in (RTIME, RSIZE) and category == L.RIGHT_NEWER:
                return self._bold
            return None
        if role == Qt.TextAlignmentRole:
            if column in (LSIZE, LTIME, RSIZE):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            if column == ACTION:
                options = L.choices(node)
                return ("Click to change: copy right, copy left, or leave it" if options
                        else L.result(node))
            return node.rel
        return None


class _Actions(QStyledItemDelegate):
    """The action column: an arrow on a pill, accent when it copies, muted
    when it is the default and plain when it was chosen by hand."""

    def __init__(self, view: "SyncTree", model: SyncModel) -> None:
        super().__init__(view)
        self.model = model

    def paint(self, painter: QPainter, option, index) -> None:
        node = self.model.node(index)
        tokens = self.model.tokens
        if node is None or not tokens:
            return
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, parse_colour(tokens.get("accent_row")))
        action = self.model.decisions.action(node)
        text = ARROWS.get(action, "")
        whole = L.inside_whole(node)
        if whole is not None:
            # Inside a folder copied whole: its arrow, quietly.
            arrow = ARROWS.get(self.model.decisions.action(whole), "")
            painter.setPen(parse_colour(tokens.get("txt_2")))
            painter.drawText(option.rect, Qt.AlignCenter, arrow or "\u00b7")
            return
        if not text:
            if not L.choices(node):
                text = "=" if L.category(node) == L.SAME else (
                    "≠" if node.is_dir and node.differing else "")
                colour = parse_colour(tokens.get("txt_2"))
                painter.setPen(colour)
                painter.drawText(option.rect, Qt.AlignCenter, text)
            else:
                painter.setPen(parse_colour(tokens.get("txt_2")))
                painter.drawText(option.rect, Qt.AlignCenter, "·")
            return
        accent = parse_colour(tokens.get("accent"))
        fill = parse_colour(tokens.get("accent_soft"))
        rect = QRect(0, 0, 40, option.rect.height() - 6)
        rect.moveCenter(option.rect.center())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 5, 5)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(accent if not self.model.decisions.changed(node)
                       else parse_colour(tokens.get("txt_0")))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class SyncTree(QTreeView):
    """The list: a click on the action column changes the action; keys as
    in the trees, plus Space for the row's box."""

    command = Signal(str)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        index = self.indexAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and index.isValid() and index.column() == ACTION:
            self.model().cycle(index)
            self.setCurrentIndex(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        names = {
            (Qt.NoModifier, Qt.Key_Return): "open", (Qt.NoModifier, Qt.Key_Enter): "open",
            (Qt.NoModifier, Qt.Key_Space): "toggle", (Qt.NoModifier, Qt.Key_F5): "copy-from-side",
            (Qt.AltModifier, Qt.Key_Right): "copy-right", (Qt.AltModifier, Qt.Key_Left): "copy-left",
            (Qt.AltModifier, Qt.Key_Down): "next", (Qt.AltModifier, Qt.Key_Up): "previous",
            (Qt.ControlModifier, Qt.Key_U): "swap", (Qt.ControlModifier, Qt.Key_R): "reload",
            (Qt.ControlModifier, Qt.Key_C): "copy-path",
            (Qt.ControlModifier | Qt.AltModifier, Qt.Key_S): "save-session",
        }
        name = names.get((mods, key))
        if name is None:
            super().keyPressEvent(event)
            return
        self.command.emit(name)
        event.accept()


class SyncList(QWidget):
    """The list and its plan bar. `run` is clicked to hand the plan over."""

    run = Signal()

    def __init__(self, icons: fileicons.FileIcons, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = SyncModel(self, icons)
        self.tree = SyncTree()
        self.tree.setModel(self.model)
        self.tree.setProperty("role", "foldertree")
        self.tree.setItemDelegateForColumn(ACTION, _Actions(self.tree, self.model))
        self.tree.setIconSize(QSize(fileicons.ROW_ICON, fileicons.ROW_ICON))
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setAllColumnsShowFocus(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setSectionResizeMode(NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(RESULT, QHeaderView.Stretch)
        for column in (LSIZE, LTIME, ACTION, RTIME, RSIZE):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
        self.summary = QLabel()
        self.summary.setProperty("role", "note")
        self.button = QPushButton("Run in File Manager")
        self.button.setProperty("role", "primary")
        self.button.setToolTip("Hand these copies to File Manager's queue. Nothing is removed; "
                               "a file left at its default is copied only if it is still newer.")
        self.button.clicked.connect(self.run)
        bar = QWidget()
        bar.setProperty("role", "planbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        title = QLabel("Plan")
        title.setProperty("role", "sidename")
        row.addWidget(title)
        row.addWidget(self.summary, 1)
        row.addWidget(self.button)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self.tree, 1)
        box.addWidget(bar)
        self.model.dataChanged.connect(lambda *_a: self.update_plan())
        self.model.layoutChanged.connect(lambda *_a: self.update_plan())
        self.model.modelReset.connect(self.update_plan)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.model.tokens = tokens
        font = QFont(self.tree.font())
        font.setBold(True)
        self.model._bold = font
        metrics = QFontMetrics(font)
        size = metrics.horizontalAdvance("9,999.9 MB") + 18
        time = metrics.horizontalAdvance("2026-12-31 23:59") + 30
        header = self.tree.header()
        for column, width in ((LSIZE, size), (RSIZE, size), (LTIME, time), (RTIME, time),
                              (ACTION, 64)):
            header.resizeSection(column, width)
        self.tree.viewport().update()

    def set_tree(self, root: F.Node | None) -> None:
        self.model.set_tree(root)
        if root is not None and sum(1 for _ in root.walk()) < 3000:
            self.tree.expandAll()

    def selected(self) -> list[F.Node]:
        rows = self.tree.selectionModel().selectedRows(0) if self.tree.selectionModel() else []
        return [self.model.node(index) for index in rows]

    def update_plan(self) -> None:
        root = self.model.root
        if root is None:
            self.summary.setText("")
            self.button.setEnabled(False)
            return
        totals = L.totals(root, self.model.decisions)
        parts = []
        for action, arrow, where in ((L.RIGHT, "→", "the right"), (L.LEFT, "←", "the left")):
            files, folders = totals.files[action], totals.folders[action]
            if not files and not folders:
                continue
            what = []
            if files:
                what.append(f"{files:,} file{'s' if files != 1 else ''}")
            if folders:
                what.append(f"{folders:,} folder{'s' if folders != 1 else ''}")
            parts.append(f"{arrow} copy {' and '.join(what)} to {where}, "
                         f"{_bytes(totals.size[action])}")
        self.summary.setText("     ".join(parts) + "     no deletions" if parts
                             else "Nothing to copy")
        self.button.setEnabled(bool(parts))


def _bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return ""
