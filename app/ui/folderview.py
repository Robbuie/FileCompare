"""The folder compare view: two mirrored trees in one, every row given its verdict.

Laid out the way Beyond Compare and File Manager's two panes are (1.12): the
left folder on the left with its own name, size and time, the right folder on
the right with the same three, and a narrow verdict column between them that
is drawn like the text view's gutter. A file only on one side leaves the other
side's half of the row blank, which reads as a gap the way a filler row does
in the text view, and the colour wash covers only the side that has the file.

It is still one `QTreeView` with one model. Two views would need their scroll
positions, expansion and selection kept in step by hand, and every one of
those is a way for the halves to drift; one view cannot drift. The tree draws
the left name's indentation and arrows itself; `RightNames` draws the right
name's, from the same depth, and an arrow click on the right toggles the same
row.

The difference colours are the text view's and mean the same things: red for
only on the left, green for only on the right, amber for on both and not the
same. A newer file's time is bold on the side that is newer.

Icons are Windows' own, by kind, through `ui/fileicons.py` -- never by path,
so a dead share costs nothing to draw.

Enter or a double-click on a file opens that pair in a tab of its own, in
whatever mode suits it. Nothing here reads a file: the walk, the verdicts and
the content compare are all `core/folderdiff.py`'s, off the UI thread.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QFont, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core import folders as F
from app.core import syncplan as S
from app.core.folderdiff import FolderSession
from app.ui import fileicons, glyphs
from app.ui.diffview import parse_colour

#: Left half, verdict, right half -- the same three columns on each side, in
#: the same order, as in File Manager's two panes (1.12).
COLUMNS = ("Name", "Size", "Modified", "", "Name", "Size", "Modified")
LNAME, LSIZE, LTIME, VERDICT, RNAME, RSIZE, RTIME = range(7)
#: Before 1.12 there was one name column; code that only wants "the row"
#: still asks for column 0.
NAME = LNAME
LEFT_COLUMNS = (LNAME, LSIZE, LTIME)
RIGHT_COLUMNS = (RNAME, RSIZE, RTIME)

#: What the narrow middle column shows for each verdict. Colour carries it at
#: a glance and the mark carries it for anyone who does not see the colour.
MARKS = {
    F.SAME: "=",
    F.CONTENT_SAME: "=",
    F.HOUR_APART: "=",
    F.NEWER_LEFT: "<",
    F.NEWER_RIGHT: ">",
    F.DIFFERENT: "\u2260",
    F.CONTENT_DIFF: "\u2260",
    F.ONLY_LEFT: "\u2190",
    F.ONLY_RIGHT: "\u2192",
    F.CLASH: "?",
    F.ERROR: "\u00d7",
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


def _rollup(node: F.Node) -> str:
    """A folder's size column (1.15): how many files under it differ, so a
    collapsed tree still says where to look."""
    if node.status in (F.ONLY_LEFT, F.ONLY_RIGHT):
        return f"{node.files:,} file{'s' if node.files != 1 else ''}" if node.files else ""
    if node.differing:
        return f"{node.differing:,} differ"
    return ""


def _time(entry: F.Entry | None) -> str:
    if entry is None or entry.is_dir or not entry.mtime:
        return ""
    return _dt.datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M:%S")


class FolderModel(QAbstractItemModel):
    """The merged tree, filtered by the show setting, as Qt wants it."""

    def __init__(self, parent=None, icons: fileicons.FileIcons | None = None) -> None:
        super().__init__(parent)
        self.root: F.Node | None = None
        self.show = F.SHOW_ALL
        self.tokens: dict[str, str] = {}
        self.icons = icons if icons is not None else fileicons.shared()
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

    def depth(self, node: F.Node) -> int:
        """How many folders above this row, for the right name's indent."""
        depth = 0
        up = node.parent
        while up is not None and up is not self.root:
            depth += 1
            up = up.parent
        return depth

    def icon(self, node: F.Node) -> QIcon:
        return self.icons.icon(node.name, node.is_dir, self.tokens.get("txt_1", ""),
                               self.tokens.get("txt_2", ""))

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
        if parent.isValid() and parent.column() != 0:
            return False
        node = self.node(parent)
        return node is not None and bool(node.children) and bool(self.kids(node))

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if section in (LSIZE, RSIZE) \
                else int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    @staticmethod
    def side_of(column: int) -> int:
        return 0 if column in LEFT_COLUMNS else 1 if column in RIGHT_COLUMNS else -1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node: F.Node = index.internalPointer()
        column = index.column()
        side = self.side_of(column)
        entry = node.left if side == 0 else node.right if side == 1 else None
        if role == Qt.DisplayRole:
            if column in (LNAME, RNAME):
                return node.name if entry is not None else ""
            if column in (LSIZE, RSIZE):
                if node.is_dir and entry is not None:
                    return _rollup(node)
                return _size(entry)
            if column in (LTIME, RTIME):
                return _time(entry)
            if column == VERDICT:
                if node.is_dir and node.status == F.DIFFERENT:
                    return f"{node.differing:,}"
                return MARKS.get(node.status, "")
            return None
        if role == Qt.DecorationRole:
            if column == LNAME and entry is not None:
                return self.icon(node)
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
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            if side >= 0 and entry is None:
                return None
            name = _ink(node.status)
            return QBrush(parse_colour(self.tokens.get(name))) if name else None
        if role == Qt.BackgroundRole:
            if side < 0:
                return None
            # Only the side that has the file is washed: the other half is a
            # gap, the way a filler row is in the text view.
            if node.status in (F.ONLY_LEFT, F.ONLY_RIGHT) and entry is None:
                return None
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


def _wash_cell(painter, option, index) -> None:
    """The row wash, drawn by hand: once the stylesheet styles `::item`, Qt's
    style stops drawing BackgroundRole, and the wash is what makes a file that
    is only on one side read as a filled half beside an empty one."""
    if option.state & QStyle.State_Selected:
        return
    brush = index.data(Qt.BackgroundRole)
    if brush is not None:
        painter.fillRect(option.rect, brush)


def _wash_cell_rect(painter, rect, brush) -> None:
    if brush is not None:
        painter.fillRect(rect, brush)


class Washed(QStyledItemDelegate):
    """Every ordinary cell: the wash, then whatever Qt draws."""

    def paint(self, painter, option, index) -> None:
        _wash_cell(painter, option, index)
        super().paint(painter, option, index)


class RightNames(QStyledItemDelegate):
    """The right folder's name column, drawn as if it were the tree column.

    Same indent per level as the tree's own, a chevron on folders that turns
    with the left one, and the icon -- so the right half is a mirror of the
    left rather than a list of names in a table. A click on the chevron
    toggles the row, the same row the left arrow toggles.
    """

    ICON = fileicons.ROW_ICON
    CHEVRON = 12

    def __init__(self, tree: QTreeView, model: FolderModel) -> None:
        super().__init__(tree)
        self.tree = tree
        self.model = model

    def _parts(self, rect: QRect, node: F.Node) -> tuple[QRect, QRect, QRect]:
        indent = self.tree.indentation()
        x = rect.x() + self.model.depth(node) * indent + 4
        mid = rect.y() + rect.height() // 2
        chevron = QRect(x + (indent - self.CHEVRON) // 2 - 4, mid - self.CHEVRON // 2,
                        self.CHEVRON, self.CHEVRON)
        x += indent - 4
        icon = QRect(x, mid - self.ICON // 2, self.ICON, self.ICON)
        text = QRect(x + self.ICON + 6, rect.y(), max(0, rect.right() - x - self.ICON - 8),
                     rect.height())
        return chevron, icon, text

    def paint(self, painter, option, index) -> None:
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        node: F.Node = index.internalPointer()
        text = opt.text
        opt.text = ""
        opt.icon = QIcon()
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        _wash_cell(painter, opt, index)
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, widget)
        if node is None or node.right is None:
            return
        tokens = self.model.tokens
        chevron, icon_rect, text_rect = self._parts(opt.rect, node)
        painter.save()
        if node.is_dir and self.model.kids(node):
            first = self.model.index(index.row(), LNAME, index.parent())
            glyph = "chevron_down" if self.tree.isExpanded(first) else "chevron_right"
            ratio = float(painter.device().devicePixelRatioF() or 1.0)
            glyphs.icon(glyph, colour=tokens.get("txt_2", ""), muted=tokens.get("txt_2", ""),
                        size=self.CHEVRON, ratio=ratio).paint(painter, chevron)
        self.model.icon(node).paint(painter, icon_rect)
        selected = bool(opt.state & QStyle.State_Selected)
        brush = index.data(Qt.ForegroundRole)
        colour = parse_colour(tokens.get("txt_0")) if selected or brush is None \
            else brush.color()
        painter.setPen(QPen(colour))
        painter.setFont(opt.font)
        elided = QFontMetrics(opt.font).elidedText(text, Qt.ElideMiddle, text_rect.width())
        painter.drawText(text_rect, int(Qt.AlignLeft | Qt.AlignVCenter), elided)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            node: F.Node = index.internalPointer()
            if node is not None and node.right is not None and node.is_dir:
                chevron, _icon, _text = self._parts(option.rect, node)
                if chevron.adjusted(-4, -4, 4, 4).contains(event.position().toPoint()):
                    first = self.model.index(index.row(), LNAME, index.parent())
                    self.tree.setExpanded(first, not self.tree.isExpanded(first))
                    return True
        return super().editorEvent(event, model, option, index)


class Verdicts(QStyledItemDelegate):
    """The middle column, drawn as the text view's gutter: its own surface,
    a hairline either side, the mark centred in the difference colour."""

    def __init__(self, tree: QTreeView, model: FolderModel) -> None:
        super().__init__(tree)
        self.model = model

    def paint(self, painter, option, index) -> None:
        tokens = self.model.tokens
        rect = option.rect
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        painter.fillRect(rect, parse_colour(tokens.get("accent_row" if selected else "bg_1")))
        painter.setPen(QPen(parse_colour(tokens.get("line_soft"))))
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        painter.drawLine(rect.topRight(), rect.bottomRight())
        text = index.data(Qt.DisplayRole) or ""
        if text:
            brush = index.data(Qt.ForegroundRole)
            colour = brush.color() if brush is not None else parse_colour(tokens.get("txt_2"))
            painter.setPen(QPen(colour))
            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, int(Qt.AlignCenter), text)
        painter.restore()


class FolderTree(QTreeView):
    """Keys: Enter opens, Alt+Up/Down steps through differences, and the
    tab's keys (swap, reload) go up as commands like the text view's."""

    command = Signal(str)
    #: 1.14: the half last clicked, 0 left or 1 right -- the side F5 copies from.
    sideClicked = Signal(int)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: N802, A002
        """Tab is "the other side" here, as in the text view and File Manager,
        so it reaches keyPressEvent instead of moving the focus away."""
        return False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        column = self.header().logicalIndexAt(int(event.position().x()))
        side = FolderModel.side_of(column)
        if side >= 0:
            self.sideClicked.emit(side)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        """The verdict column's surface runs the full height, rows or not, so
        the two halves stay visibly two halves below the last row too."""
        model = self.model()
        tokens = getattr(model, "tokens", None)
        if tokens:
            header = self.header()
            x = header.sectionViewportPosition(VERDICT)
            w = header.sectionSize(VERDICT)
            painter = QPainter(self.viewport())
            painter.fillRect(QRect(x, 0, w, self.viewport().height()),
                             parse_colour(tokens.get("bg_1")))
            painter.setPen(QPen(parse_colour(tokens.get("line_soft"))))
            painter.drawLine(x, 0, x, self.viewport().height())
            painter.drawLine(x + w - 1, 0, x + w - 1, self.viewport().height())
            painter.end()
        super().paintEvent(event)

    def drawBranches(self, painter, rect, index) -> None:  # noqa: N802
        """No arrow on the left for a folder that is only on the right: the
        left half of that row is a gap, and the right name draws its own."""
        node = index.internalPointer() if index.isValid() else None
        if node is not None and node.left is None:
            model = self.model()
            _wash_cell_rect(painter, rect, model.data(index, Qt.BackgroundRole))
            return
        model = self.model()
        if node is not None and not self.selectionModel().isSelected(index):
            _wash_cell_rect(painter, rect, model.data(index, Qt.BackgroundRole))
        super().drawBranches(painter, rect, index)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        if key in (Qt.Key_Return, Qt.Key_Enter) and mods == Qt.NoModifier:
            self.command.emit("open")
        elif key == Qt.Key_F5 and mods == Qt.NoModifier:
            self.command.emit("copy-from-side")
        elif mods == Qt.AltModifier and key == Qt.Key_Right:
            self.command.emit("copy-right")
        elif mods == Qt.AltModifier and key == Qt.Key_Left:
            self.command.emit("copy-left")
        elif key == Qt.Key_Tab and mods == Qt.NoModifier:
            self.command.emit("other-side")
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
        elif mods == (Qt.ControlModifier | Qt.AltModifier) and key == Qt.Key_S:
            self.command.emit("save-session")
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
    #: 1.12: where the halves meet, (left half width, verdict width), so the
    #: tab can put each side's header over its own half.
    split = Signal(int, int)
    #: 1.14: which half is the active one, for the tab to mark its header.
    sideChanged = Signal(int)
    #: 1.15: compare other folders: (left, right), "" for a side that stays.
    rebase = Signal(str, str)

    def __init__(self, session: FolderSession, tokens: dict[str, str], *,
                 mask: str = "", open_expanded: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.model = FolderModel(self)
        self.model.icons.set_scale(float(self.devicePixelRatioF() or 1.0))
        self.model.icons.changed.connect(self._icons_arrived)
        self.tree = FolderTree()
        self.tree.setModel(self.model)
        self.tree.setProperty("role", "foldertree")
        self.tree.setItemDelegate(Washed(self.tree))
        self.tree.setItemDelegateForColumn(RNAME, RightNames(self.tree, self.model))
        self.tree.setItemDelegateForColumn(VERDICT, Verdicts(self.tree, self.model))
        self.tree.setIconSize(QSize(fileicons.ROW_ICON, fileicons.ROW_ICON))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        session.extracted.connect(self.openExtracted)
        self.tree.doubleClicked.connect(lambda _i: self._open())
        self.tree.command.connect(self._command)
        self.tree.sideClicked.connect(self.set_side)
        self.tree.selectionModel().selectionChanged.connect(lambda *_a: self._update_copies())
        #: 1.14: the side F5 copies from, as in File Manager: the half last
        #: clicked, or switched to with Tab.
        self.side = 0
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setMinimumSectionSize(28)
        # Both names stretch and everything else is a fixed width worked out
        # from the font, the same on both sides, so the halves are always the
        # same width and the verdict column sits in the middle (1.12).
        for column in (LNAME, RNAME):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        for column in (LSIZE, LTIME, VERDICT, RSIZE, RTIME):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
        header.sectionResized.connect(lambda *_a: self._emit_split())

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
            button.clicked.connect(lambda _c=False, v=value: self.set_show(v, keep=True))
            seg.addWidget(button)
            self.shows[value] = button
        self.mask = QLineEdit(mask)
        self.mask.setProperty("role", "findfield")
        self.mask.setMaximumWidth(460)
        self.mask.setMinimumWidth(150)
        self.mask.setPlaceholderText("*.L5X;*.ini  -.git;-*.bak")
        self._mask_label = QLabel("Filter")
        self._mask_label.setProperty("role", "hint")
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
        # 1.14: the selected rows to one side, through the same preview and
        # File Manager handoff as the right-click menu's copies.
        self.to_left = QToolButton()
        self.to_left.setText("Copy to left")
        self.to_left.setProperty("role", "retry")
        self.to_left.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.to_left.setFocusPolicy(Qt.NoFocus)
        self.to_left.setToolTip("Copy the selected rows to the left folder (Alt+Left; "
                                "F5 copies from the side you are on)")
        self.to_left.clicked.connect(lambda _c=False: self.copy_selected(S.TO_LEFT))
        self.to_right = QToolButton()
        self.to_right.setText("Copy to right")
        self.to_right.setProperty("role", "retry")
        self.to_right.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.to_right.setLayoutDirection(Qt.RightToLeft)
        self.to_right.setFocusPolicy(Qt.NoFocus)
        self.to_right.setToolTip("Copy the selected rows to the right folder (Alt+Right; "
                                 "F5 copies from the side you are on)")
        self.to_right.clicked.connect(lambda _c=False: self.copy_selected(S.TO_RIGHT))
        # 1.15: the tree opens collapsed, with each folder's size column
        # saying how many files under it differ; Expand opens just the
        # folders that hold differences, its menu everything.
        self.expand = QToolButton()
        self.expand.setText("Expand")
        self.expand.setProperty("role", "retry")
        self.expand.setPopupMode(QToolButton.MenuButtonPopup)
        self.expand.setFocusPolicy(Qt.NoFocus)
        self.expand.setToolTip("Open the folders that hold differences")
        self.expand.clicked.connect(lambda _c=False: self.expand_differences())
        expand_menu = QMenu(self)
        expand_menu.addAction("Expand differences", self.expand_differences)
        expand_menu.addAction("Expand all", self.tree.expandAll)
        expand_menu.addAction("Collapse all", self.collapse_all)
        expand_menu.addSeparator()
        self._open_expanded = expand_menu.addAction("Open with differences expanded")
        self._open_expanded.setCheckable(True)
        self._open_expanded.setChecked(open_expanded)
        self._open_expanded.setToolTip("Open each new comparison with the folders that hold "
                                       "differences expanded, rather than collapsed")
        self._open_expanded.toggled.connect(
            lambda on: self.setting.emit("folders.open_expanded", bool(on)))
        expand_menu.setToolTipsVisible(True)
        self.expand.setMenu(expand_menu)
        self.collapse = QToolButton()
        self.collapse.setText("Collapse")
        self.collapse.setProperty("role", "retry")
        self.collapse.setFocusPolicy(Qt.NoFocus)
        self.collapse.clicked.connect(lambda _c=False: self.collapse_all())
        #: 1.15: the folders open in the tree, by rel and lowercased, kept
        #: across every rebuild -- a content compare, a filter, a walk again,
        #: one side pointed somewhere else -- so the tree stays as it was left.
        #: None until the first tree has been shown.
        self._opened: set[str] | None = None
        # The summary is the status bar's to show; before 1.12 it was here as
        # well, word for word. The label stays for what reads it.
        self.line = QLabel()
        self.line.setProperty("role", "count")
        self.line.hide()

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(6)
        bar.addWidget(segments)
        bar.addSpacing(6)
        bar.addWidget(self._mask_label)
        bar.addWidget(self.mask, 1)
        bar.addStretch(0)
        bar.addWidget(self.to_left)
        bar.addWidget(self.to_right)
        bar.addSpacing(6)
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
        box.addWidget(self.tree, 1)

        session.changed.connect(self.refresh)
        session.progressed.connect(self._progress)
        session.handed.connect(self._handed)
        session.remote.connect(self._remote)
        self._dialog = None
        self.apply_tokens(tokens)
        self.set_show(F.SHOW_DIFFERENT, rebuild=False)
        self.refresh()

    # ----------------------------------------------------------- drawing

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        # The tree is in the interface font, like File Manager's listing; the
        # sizes line up by being right-aligned, not by being monospaced.
        self.model.tokens = tokens
        ratio = float(self.devicePixelRatioF() or 1.0)
        for button, glyph in ((self.to_left, "copy_left"), (self.to_right, "copy_right")):
            button.setIcon(glyphs.icon(glyph, colour=tokens.get("txt_1", ""),
                                       muted=tokens.get("txt_2", ""), size=14, ratio=ratio))
        self._size_columns()
        self.tree.viewport().update()

    def _size_columns(self) -> None:
        # Bold, because a newer side's time is drawn bold and must still fit.
        font = QFont(self.tree.font())
        font.setBold(True)
        self.model._bold = font
        metrics = QFontMetrics(font)
        size = metrics.horizontalAdvance("9,999.9 MB") + 22
        time = metrics.horizontalAdvance("2026-12-31 23:59:59") + 26
        header = self.tree.header()
        for column, width in ((LSIZE, size), (RSIZE, size), (LTIME, time), (RTIME, time),
                              (VERDICT, 34)):
            header.resizeSection(column, width)
        self._emit_split()

    def _emit_split(self) -> None:
        header = self.tree.header()
        left = sum(header.sectionSize(c) for c in LEFT_COLUMNS)
        self.split.emit(self.tree.x() + self.tree.viewport().x() + left,
                        header.sectionSize(VERDICT))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._emit_split()

    def _icons_arrived(self) -> None:
        self.tree.viewport().update()

    def refresh(self) -> None:
        self._rebuild(self.session.tree)
        self._update_counts()
        self._progress()

    def _rebuild(self, tree: F.Node | None, show: str | None = None) -> None:
        """The model reset, with the open folders put back afterwards. A reset
        closes every folder, and before 1.15 each one -- every batch of a
        content compare -- opened them again its own way, undoing whatever the
        user had closed."""
        if self.model.root is not None:
            self._opened = self.open_folders()
        self.model.set_tree(tree, show)
        if tree is None:
            return
        if self._opened is None:
            self._opened = set()
            if self._open_expanded.isChecked():
                self._expand_differences()
                return
        self.reopen(self._opened)

    def open_folders(self) -> set[str]:
        """The rels of the folders open in the tree now, lowercased."""
        out: set[str] = set()

        def walk(parent: QModelIndex) -> None:
            for row in range(self.model.rowCount(parent)):
                index = self.model.index(row, 0, parent)
                if self.tree.isExpanded(index):
                    out.add(self.model.node(index).rel.lower())
                    walk(index)
        walk(QModelIndex())
        return out

    def reopen(self, rels: set[str]) -> None:
        """Open the folders named, where the tree still has them."""
        if not rels:
            return

        def walk(parent: QModelIndex) -> None:
            for row in range(self.model.rowCount(parent)):
                index = self.model.index(row, 0, parent)
                node = self.model.node(index)
                if node.is_dir and node.rel.lower() in rels:
                    self.tree.expand(index)
                    walk(index)
        walk(QModelIndex())

    def expand_differences(self) -> None:
        """Every folder that holds a difference, all the way down (1.15)."""
        self._expand_differences(limit=None)

    def collapse_all(self) -> None:
        self.tree.collapseAll()
        self._opened = set()

    def forget_open(self, keep: set[str] | None = None) -> None:
        """The next tree opens with `keep` open -- or, given nothing, as a
        new comparison does: for when both sides moved to other folders."""
        self._opened = keep
        if self.model.root is not None:
            # The model's tree is the old one: let go of it now, so the next
            # rebuild does not read the old tree's open folders over these.
            self.model.set_tree(None)

    def _progress(self) -> None:
        text = self.session.status()
        self.line.setText(text)
        self.contents.setEnabled(self.session.tree is not None)
        self.sync.setEnabled(self.session.tree is not None or self.session.syncing)
        self._update_copies()
        if self.session.syncing:
            text += "  ·  waiting for File Manager's queue"
            self.line.setText(text)
        self.status.emit(text)

    def _expand_differences(self, limit: int | None = 3) -> None:
        """Open the folders that hold differences: all of them when asked
        for, or (`limit`) only near the top with few enough in each, which is
        what "Open with differences expanded" does to a new comparison."""
        def walk(parent: QModelIndex, depth: int) -> None:
            for row in range(self.model.rowCount(parent)):
                index = self.model.index(row, 0, parent)
                node = self.model.node(index)
                if not (node.is_dir and node.differing):
                    continue
                if limit is not None and (depth >= limit or node.differing >= 400):
                    continue
                self.tree.expand(index)
                walk(index, depth + 1)
        walk(QModelIndex(), 0)

    def set_show(self, show: str, rebuild: bool = True, *, keep: bool = False) -> None:
        """`keep`: the user picked it, so it is kept for next time (1.15)."""
        for value, button in self.shows.items():
            button.setChecked(value == show)
        if rebuild or self.model.show != show:
            self._rebuild(self.model.root, show)
            self._update_counts()
        if keep:
            self.setting.emit("folders.show", show)

    def _update_counts(self) -> None:
        """The show buttons carry their counts (1.15), which makes them the
        summary as well as the filter: one click from "Right newer 7" to the
        seven."""
        totals = F.show_counts(self.model.root) if self.model.root is not None else {}
        for value, label in SHOW_LABELS:
            count = totals.get(value)
            self.shows[value].setText(f"{label}  {count:,}" if count is not None else label)

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

    def copy_selected(self, direction: str) -> None:
        """The selected rows copied one way (1.14): the preview first, where
        rows with nothing to copy say so, then File Manager's queue."""
        if not self.selected():
            self.status.emit("Select the files or folders to copy first")
            return
        if self.session.syncing:
            self.status.emit("A sync is already with File Manager; this comparison is "
                             "read again when it finishes.")
            return
        self._picked(direction, S.COPY)

    def set_side(self, side: int) -> None:
        if side in (0, 1) and side != self.side:
            self.side = side
            self.sideChanged.emit(side)

    def _update_copies(self) -> None:
        ready = (self.session.tree is not None and not self.session.syncing
                 and bool(self.selected()))
        self.to_left.setEnabled(ready)
        self.to_right.setEnabled(ready)

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
        elif name == "copy-from-side":
            self.copy_selected(S.TO_RIGHT if self.side == 0 else S.TO_LEFT)
        elif name == "copy-right":
            self.copy_selected(S.TO_RIGHT)
        elif name == "copy-left":
            self.copy_selected(S.TO_LEFT)
        elif name == "other-side":
            self.set_side(1 - self.side)
        elif name == "next":
            self._step(1)
        elif name == "previous":
            self._step(-1)
        elif name in ("swap", "reload", "save-session"):
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
        # 1.15: Beyond Compare's "set as base folder": move one side, or both,
        # down into the folder under the cursor.
        here = nodes[0] if len(nodes) == 1 else None
        if here is not None and here.is_dir and not here.member:
            left, right = self.session.paths(here)
            menu.addSeparator()
            if here.left is not None and here.right is not None:
                menu.addAction("Compare these two folders",
                               lambda: self._rebase(here, left, right))
            if here.left is not None:
                menu.addAction("Use as the left folder",
                               lambda: self._rebase(here, left, ""))
            if here.right is not None:
                menu.addAction("Use as the right folder",
                               lambda: self._rebase(here, "", right))
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

    def _rebase(self, node: F.Node, left: str, right: str) -> None:
        if left and right:
            # Both sides moved down into this folder: what was open under it
            # stays open, now one level nearer the top.
            self.forget_open(F.rebased(self.open_folders(), node.rel))
        self.rebase.emit(left, right)

    def focus(self) -> None:
        self.tree.setFocus(Qt.OtherFocusReason)
