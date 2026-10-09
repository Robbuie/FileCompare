"""The differences list beside a text comparison (1.19).

Every difference on one line each -- where it is and what it is, "Line 10:
copy to copy2" -- grouped under the function, class or section it falls in
(`core/outline.py`). Kaleidoscope's and ExamDiff's change list: a long file
with a dozen scattered changes reads as a dozen lines here, and a click goes
to one. A box at the top filters by any word in the list.

Ignored differences are listed last, under their own heading, rather than
left out: a list that reports fewer changes than there are, without saying
so, is the failure CLAUDE.md warns about for the rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.diffview import parse_colour

ROLE = Qt.UserRole + 1          # the entry an item draws


@dataclass
class Entry:
    block: int                  # -1 for a group heading
    title: str
    detail: str = ""
    bar: str = ""               # the token of its colour
    count: int = 0              # a heading's number of entries


class _Delegate(QStyledItemDelegate):
    """Draws a heading as small capitals with its count, and a difference as
    a coloured dot, its place in bold and what it is under it."""

    def __init__(self, owner: "DiffSidebar") -> None:
        super().__init__(owner)
        self.owner = owner

    def _fonts(self, option) -> tuple[QFont, QFont, QFont]:
        base = QFont(option.font)
        bold = QFont(base)
        bold.setBold(True)
        small = QFont(base)
        small.setPixelSize(max(9, (base.pixelSize() if base.pixelSize() > 0 else 13) - 2))
        small.setBold(True)
        return base, bold, small

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        entry: Entry = index.data(ROLE)
        base, _bold, small = self._fonts(option)
        line = QFontMetrics(base).height()
        if entry is None or entry.block < 0:
            return QSize(10, QFontMetrics(small).height() + 12)
        return QSize(10, line * 2 + 8)

    def paint(self, painter: QPainter, option, index) -> None:
        entry: Entry = index.data(ROLE)
        if entry is None:
            return
        tokens = self.owner.tokens
        colour = lambda name: parse_colour(tokens.get(name))  # noqa: E731
        base, bold, small = self._fonts(option)
        rect = option.rect
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.fillRect(rect, colour("accent_row"))
            painter.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()), colour("accent"))
        elif option.state & QStyle.State_MouseOver and entry.block >= 0:
            painter.fillRect(rect, colour("bg_3"))
        if entry.block < 0:
            painter.setFont(small)
            painter.setPen(colour("txt_2"))
            inner = rect.adjusted(10, 4, -10, 0)
            painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter,
                             QFontMetrics(small).elidedText(entry.title, Qt.ElideRight,
                                                            inner.width() - 30))
            painter.drawText(inner, Qt.AlignRight | Qt.AlignVCenter, f"{entry.count:,}")
            painter.restore()
            return
        line = QFontMetrics(base).height()
        dot = colour(entry.bar or "diff_chg_bar")
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(rect.left() + 12, rect.top() + 4 + line // 2 - 4, 8, 8)
        text_left = rect.left() + 28
        width = rect.right() - text_left - 8
        painter.setFont(bold)
        painter.setPen(colour("txt_2" if not entry.bar or entry.bar == "diff_ignored_bar"
                              else "txt_0"))
        painter.drawText(QRect(text_left, rect.top() + 4, width, line),
                         Qt.AlignLeft | Qt.AlignVCenter, entry.title)
        painter.setFont(base)
        painter.setPen(colour("txt_1"))
        painter.drawText(QRect(text_left, rect.top() + 4 + line, width, line),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(base).elidedText(entry.detail, Qt.ElideRight, width))
        painter.restore()


class DiffSidebar(QWidget):
    """Emits `goTo(block)` when a difference is clicked."""

    goTo = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.tokens: dict[str, str] = {}
        self.filter = QLineEdit()
        self.filter.setProperty("role", "pathbox")
        self.filter.setPlaceholderText("Filter differences")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        self.tree = QTreeWidget()
        self.tree.setProperty("role", "difflist")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setMouseTracking(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setItemDelegate(_Delegate(self))
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.itemClicked.connect(self._clicked)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 0, 6)
        box.setSpacing(6)
        box.addWidget(self.filter)
        box.addWidget(self.tree, 1)
        self._items: dict[int, QTreeWidgetItem] = {}
        self._key = None
        self.setMinimumWidth(200)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.tree.viewport().update()

    def set_entries(self, key, groups: list[tuple[str, list[Entry]]]) -> None:
        """The list, grouped. `key` names what it was made from, so the same
        comparison asked again does not rebuild it."""
        if key is not None and key == self._key:
            return
        self._key = key
        self.tree.clear()
        self._items = {}
        for heading, entries in groups:
            if not entries:
                continue
            group = QTreeWidgetItem([heading])
            group.setData(0, ROLE, Entry(-1, heading, count=len(entries)))
            group.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(group)
            for entry in entries:
                item = QTreeWidgetItem([f"{entry.title} {entry.detail} {heading}"])
                item.setData(0, ROLE, entry)
                item.setToolTip(0, f"{heading}\n{entry.title}: {entry.detail}" if heading
                                else f"{entry.title}: {entry.detail}")
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tree.addTopLevelItem(item)
                self._items[entry.block] = item
        self._filter(self.filter.text())

    def set_current(self, block: int | None) -> None:
        item = self._items.get(block) if block is not None else None
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        if item is not None:
            item.setSelected(True)
            self.tree.scrollToItem(item)
        self.tree.blockSignals(False)

    def count(self) -> int:
        return len(self._items)

    def _clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        entry: Entry = item.data(0, ROLE)
        if entry is not None and entry.block >= 0:
            self.goTo.emit(entry.block)

    def _filter(self, text: str) -> None:
        words = text.lower().split()
        heading = None
        shown_under = 0
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            entry: Entry = item.data(0, ROLE)
            if entry.block < 0:
                if heading is not None:
                    heading.setHidden(shown_under == 0)
                heading, shown_under = item, 0
                continue
            hay = item.text(0).lower()
            hidden = bool(words) and not all(w in hay for w in words)
            item.setHidden(hidden)
            shown_under += not hidden
        if heading is not None:
            heading.setHidden(shown_under == 0)
