"""The rung view: a Logix comparison's rungs drawn as ladder, side by side (1.16).

The Logix comparers turn each rung into one line of neutral text, which is
the right thing to diff and the wrong thing to read. This view takes the
same comparison -- the rows the text view shows, nothing compared again --
picks out the rungs (`core/ladder.pairs`) and draws each pair the way Logix
Designer would: power rails, contacts, coils, boxes, branches. The left
rung is on the left and the right on the right, with the verdict gutter
between them like the text view's.

Colour means what it means everywhere else here: amber for an instruction
that is on both sides but differs, red for one only on the left, green for
one only on the right. Which instructions those are is `ladder.mark`'s
answer, an instruction-by-instruction match of the two rungs, so a rung
with one changed contact shows one amber contact and not an amber rung.

By default only the rungs that differ are listed, each under its program,
routine and rung number. "All rungs" lists the unchanged ones too, greyed.
Double-click a rung, or press Enter, to see it in the text view.

Painted, not built from widgets: a routine can have thousands of rungs, and
only the ones on screen are drawn. Layouts are cached per width.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import ladder as L
from app.ui.diffview import mono_font, parse_colour

#: The middle column between the halves, as in the folder view.
GUTTER = 34
#: Space around each half's ladder.
MARGIN = 14


@dataclass
class _Shown:
    """One pair as drawn: its rungs parsed, marked and laid out."""

    pair: L.RungPair
    trees: tuple[L.Series | None, L.Series | None]
    marks: tuple[list[int], list[int]]
    layouts: tuple[L.Layout | None, L.Layout | None] = (None, None)
    cells: int = 0
    top: float = 0.0
    height: float = 0.0


class RungCanvas(QAbstractScrollArea):
    """The painted list of rung pairs."""

    currentChanged = Signal()
    #: A pair's first comparison row, to show it in the text view.
    openRow = Signal(int)
    command = Signal(str)

    def __init__(self, owner: "RungView") -> None:
        super().__init__(owner)
        self.owner = owner
        self.shown: list[_Shown] = []
        self.current = -1
        self._width = -1
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(24)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # ------------------------------------------------------------ metrics

    def _metrics(self) -> None:
        o = self.owner
        self.fm = QFontMetricsF(o.mono)
        self.ui = QFontMetricsF(o.ui)
        line = self.fm.height()
        # Two lines of tag above a contact, as Logix Designer gives a long
        # tag, and room under it for a one-shot's name.
        self.wire_dy = 2 * line + 18
        self.row_h = 3 * line + 26
        self.cell_w = max(92.0, self.fm.horizontalAdvance("M") * 12)
        self.head_h = self.ui.height() + 14
        self.comment_h = self.ui.height() + 2

    def half_width(self) -> float:
        return max(120.0, (self.viewport().width() - GUTTER) / 2)

    def relayout(self) -> None:
        """Every pair's layout at the current width, and where each starts."""
        self._metrics()
        cells = max(2.0, (self.half_width() - 2 * MARGIN - 24) / self.cell_w)
        top = 0.0
        for item in self.shown:
            if item.cells != int(cells) or item.layouts == (None, None):
                item.layouts = tuple(
                    L.layout(tree, cells) if tree is not None else None
                    for tree in item.trees)
                item.cells = int(cells)
            comments = max(len(r.comments) if r is not None else 0
                           for r in (item.pair.left, item.pair.right))
            rows = max(lay.height if lay is not None else 1 for lay in item.layouts)
            item.top = top
            item.height = (self.head_h + comments * self.comment_h + rows * self.row_h
                           + 2 * 10)
            top += item.height
        self._total = top
        bar = self.verticalScrollBar()
        bar.setPageStep(max(1, self.viewport().height()))
        bar.setRange(0, max(0, int(top - self.viewport().height())))
        self._width = self.viewport().width()
        self.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.viewport().width() != self._width:
            self.relayout()
        else:
            self.verticalScrollBar().setPageStep(max(1, self.viewport().height()))

    # ------------------------------------------------------------ moving

    def at(self, y: float) -> int:
        y += self.verticalScrollBar().value()
        for index, item in enumerate(self.shown):
            if item.top <= y < item.top + item.height:
                return index
        return -1

    def go(self, index: int) -> None:
        if not self.shown:
            return
        index = max(0, min(len(self.shown) - 1, index))
        self.current = index
        item = self.shown[index]
        bar = self.verticalScrollBar()
        view_h = self.viewport().height()
        if item.top < bar.value() or item.top + min(item.height, view_h) > bar.value() + view_h:
            bar.setValue(int(item.top - 8))
        self.viewport().update()
        self.currentChanged.emit()

    def step(self, direction: int) -> None:
        """The next pair that differs, wrapping; with only differing pairs
        listed, simply the next."""
        if not self.shown:
            return
        count = len(self.shown)
        start = self.current if self.current >= 0 else (-1 if direction > 0 else count)
        for n in range(1, count + 1):
            index = (start + direction * n) % count
            if self.shown[index].pair.differs:
                self.go(index)
                return

    def mousePressEvent(self, event) -> None:  # noqa: N802
        index = self.at(event.position().y())
        if index >= 0:
            self.current = index
            self.viewport().update()
            self.currentChanged.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        index = self.at(event.position().y())
        if index >= 0:
            self.openRow.emit(self.shown[index].pair.row)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        bar = self.verticalScrollBar()
        if mods == Qt.AltModifier and key == Qt.Key_Down:
            self.step(1)
        elif mods == Qt.AltModifier and key == Qt.Key_Up:
            self.step(-1)
        elif mods == Qt.NoModifier and key == Qt.Key_Home:
            self.step(1) if self.current < 0 else self.go(0)
        elif mods == Qt.NoModifier and key == Qt.Key_End:
            self.go(len(self.shown) - 1)
        elif mods == Qt.NoModifier and key in (Qt.Key_Return, Qt.Key_Enter):
            if 0 <= self.current < len(self.shown):
                self.openRow.emit(self.shown[self.current].pair.row)
        elif mods == Qt.ControlModifier and key == Qt.Key_U:
            self.command.emit("swap")
        elif mods == Qt.ControlModifier and key == Qt.Key_R:
            self.command.emit("reload")
        elif key == Qt.Key_Down:
            bar.setValue(bar.value() + bar.singleStep())
        elif key == Qt.Key_Up:
            bar.setValue(bar.value() - bar.singleStep())
        elif key == Qt.Key_PageDown:
            bar.setValue(bar.value() + bar.pageStep())
        elif key == Qt.Key_PageUp:
            bar.setValue(bar.value() - bar.pageStep())
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # ------------------------------------------------------------ drawing

    def paintEvent(self, event) -> None:  # noqa: N802
        tokens = self.owner.tokens
        colour = lambda name: parse_colour(tokens.get(name))  # noqa: E731
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = self.viewport().width()
        height = self.viewport().height()
        painter.fillRect(self.viewport().rect(), colour("bg_2"))
        half = self.half_width()
        gutter_x = half
        painter.fillRect(QRectF(gutter_x, 0, GUTTER, height), colour("bg_1"))
        if not self.shown:
            painter.setPen(QPen(colour("txt_2")))
            painter.setFont(self.owner.ui)
            painter.drawText(QRectF(0, 0, width, height), int(Qt.AlignCenter),
                             self.owner.empty_text())
            painter.end()
            return
        scroll = self.verticalScrollBar().value()
        for index, item in enumerate(self.shown):
            top = item.top - scroll
            if top > height:
                break
            if top + item.height < 0:
                continue
            self._paint_pair(painter, item, top, half, index == self.current, colour)
        painter.setPen(QPen(colour("line_soft")))
        painter.drawLine(QPointF(gutter_x, 0), QPointF(gutter_x, height))
        painter.drawLine(QPointF(gutter_x + GUTTER, 0), QPointF(gutter_x + GUTTER, height))
        painter.end()

    def _paint_pair(self, painter: QPainter, item: _Shown, top: float, half: float,
                    current: bool, colour) -> None:
        pair = item.pair
        width = self.viewport().width()
        rect = QRectF(0, top, width, item.height)
        painter.fillRect(QRectF(0, top, width, self.head_h), colour("bg_1"))
        painter.setPen(QPen(colour("line_soft")))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        # Each half's heading: where, and the rung number.
        for side, rung in enumerate((pair.left, pair.right)):
            x = 0 if side == 0 else half + GUTTER
            box = QRectF(x + MARGIN, top, half - 2 * MARGIN, self.head_h)
            if rung is None:
                painter.setPen(QPen(colour("txt_2")))
                painter.setFont(self.owner.ui)
                painter.drawText(box, int(Qt.AlignLeft | Qt.AlignVCenter),
                                 "not on this side")
                continue
            label = rung.label + (f"  ({rung.kind})" if rung.kind != "N" else "")
            painter.setFont(self.owner.ui_bold)
            painter.setPen(QPen(colour("txt_0")))
            painter.drawText(box, int(Qt.AlignLeft | Qt.AlignVCenter), label)
            used = QFontMetricsF(self.owner.ui_bold).horizontalAdvance(label) + 12
            painter.setFont(self.owner.ui)
            painter.setPen(QPen(colour("txt_2")))
            where = self.ui.elidedText(rung.where, Qt.ElideLeft, max(0.0, box.width() - used))
            painter.drawText(box.adjusted(used, 0, 0, 0), int(Qt.AlignLeft | Qt.AlignVCenter),
                             where)
        # The verdict in the gutter, as in the folder view.
        mark, ink = "=", "txt_2"
        if pair.differs:
            if pair.left is None:
                mark, ink = "→", "diff_add_bar"
            elif pair.right is None:
                mark, ink = "←", "diff_del_bar"
            else:
                mark, ink = "≠", "diff_chg_bar"
        painter.setFont(self.owner.ui_bold)
        painter.setPen(QPen(colour(ink)))
        painter.drawText(QRectF(half, top, GUTTER, self.head_h), int(Qt.AlignCenter), mark)

        y = top + self.head_h
        comments = max(len(r.comments) if r is not None else 0
                       for r in (pair.left, pair.right))
        if comments:
            painter.setFont(self.owner.ui_italic)
            for side, rung in enumerate((pair.left, pair.right)):
                if rung is None:
                    continue
                other = pair.right if side == 0 else pair.left
                changed = other is not None and other.comments != rung.comments
                painter.setPen(QPen(colour("diff_chg_bar" if changed else "txt_2")))
                x = (0 if side == 0 else half + GUTTER) + MARGIN
                for n, text in enumerate(rung.comments):
                    line = QRectF(x, y + n * self.comment_h, half - 2 * MARGIN,
                                  self.comment_h)
                    painter.drawText(line, int(Qt.AlignLeft | Qt.AlignVCenter),
                                     self.ui.elidedText(text, Qt.ElideRight, line.width()))
            y += comments * self.comment_h
        y += 10
        for side in (0, 1):
            tree = item.trees[side]
            lay = item.layouts[side]
            x = (0 if side == 0 else half + GUTTER) + MARGIN
            if tree is None or lay is None:
                continue
            whole = None
            if pair.differs and (pair.left is None or pair.right is None):
                whole = "diff_del" if side == 0 else "diff_add"
            self._paint_rung(painter, lay, item.marks[side], x, y, half - 2 * MARGIN,
                             side, whole, pair.differs, colour)
        if current:
            pen = QPen(colour("accent_line"))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def _paint_rung(self, painter: QPainter, lay: L.Layout, marks: list[int], x0: float,
                    y0: float, width: float, side: int, whole: str | None, differs: bool,
                    colour) -> None:
        cw, rh = self.cell_w, self.row_h
        wire_dy = self.wire_dy
        inner = x0 + 12                      # where the cells start, past the rail
        right_rail = x0 + width
        rows = lay.height
        ink = colour("txt_1" if differs else "txt_2")
        wire = QPen(ink)
        wire.setWidthF(1.3)
        rail = QPen(colour("txt_2"))
        rail.setWidthF(2.0)
        painter.setPen(rail)
        painter.drawLine(QPointF(x0, y0 + 4), QPointF(x0, y0 + rows * rh - 4))
        painter.drawLine(QPointF(right_rail, y0 + 4), QPointF(right_rail, y0 + rows * rh - 4))
        painter.setPen(wire)
        cx = lambda cells: inner + cells * cw  # noqa: E731
        wy = lambda row: y0 + row * rh + wire_dy  # noqa: E731
        # From the left rail to each line's first cell, and from each line's
        # last thing to the right rail.
        starts = list(lay.lines) + [lay.height]
        for number, first in enumerate(lay.lines):
            stop = starts[number + 1]
            end = 0.0
            for placed in lay.placed:
                if first <= placed.y < stop:
                    end = max(end, placed.x + placed.w)
            for rx, r1, _r2 in lay.rails:
                if first <= r1 < stop:
                    end = max(end, rx)
            for x1, x2, row in lay.wires:
                if first <= row < stop:
                    end = max(end, x2)
            painter.drawLine(QPointF(x0, wy(first)), QPointF(cx(0), wy(first)))
            painter.drawLine(QPointF(cx(end), wy(first)), QPointF(right_rail, wy(first)))
        for x1, x2, row in lay.wires:
            if x2 > x1:
                painter.drawLine(QPointF(cx(x1), wy(row)), QPointF(cx(x2), wy(row)))
        for rx, r1, r2 in lay.rails:
            painter.drawLine(QPointF(cx(rx), wy(r1)), QPointF(cx(rx), wy(r2)))
        for placed in lay.placed:
            state = marks[placed.index] if placed.index < len(marks) else L.SAME
            tone = None
            if whole is not None:
                tone = whole
            elif state == L.CHANGED:
                tone = "diff_chg"
            elif state == L.ONLY:
                tone = "diff_del" if side == 0 else "diff_add"
            cell = QRectF(cx(placed.x), y0 + placed.y * rh, placed.w * cw, placed.h * rh)
            self._paint_instr(painter, placed.instr, cell, wy(placed.y), tone, differs, colour)

    def _paint_instr(self, painter: QPainter, instr: L.Instr, cell: QRectF, wire_y: float,
                     tone: str | None, differs: bool, colour) -> None:
        if tone is not None:
            painter.fillRect(cell.adjusted(2, 3, -2, -3), colour(tone + "_row"))
        ink = colour(tone + "_bar") if tone is not None else colour(
            "txt_0" if differs else "txt_2")
        pen = QPen(ink)
        pen.setWidthF(1.4)
        wire = QPen(colour("txt_1" if differs else "txt_2"))
        wire.setWidthF(1.3)
        shape = instr.shape
        mid = cell.center().x()
        fm = self.fm
        painter.setFont(self.owner.mono)
        if shape in ("contact", "coil"):
            half = 9.0
            painter.setPen(wire)
            painter.drawLine(QPointF(cell.left(), wire_y), QPointF(mid - half, wire_y))
            painter.drawLine(QPointF(mid + half, wire_y), QPointF(cell.right(), wire_y))
            painter.setPen(pen)
            tall = 9.0
            if shape == "contact":
                painter.drawLine(QPointF(mid - half, wire_y - tall),
                                 QPointF(mid - half, wire_y + tall))
                painter.drawLine(QPointF(mid + half, wire_y - tall),
                                 QPointF(mid + half, wire_y + tall))
                if instr.name == "XIO":
                    painter.drawLine(QPointF(mid - half + 3, wire_y + tall - 2),
                                     QPointF(mid + half - 3, wire_y - tall + 2))
                elif instr.name not in L.CONTACTS:
                    painter.setFont(self.owner.mono_small)
                    painter.drawText(QRectF(mid - 30, wire_y + tall, 60, fm.height()),
                                     int(Qt.AlignHCenter | Qt.AlignTop), instr.name)
                    painter.setFont(self.owner.mono)
            else:
                path = QPainterPath()
                path.arcMoveTo(QRectF(mid - half - 4, wire_y - tall, 10, 2 * tall), 120)
                path.arcTo(QRectF(mid - half - 4, wire_y - tall, 10, 2 * tall), 120, 120)
                path.arcMoveTo(QRectF(mid + half - 6, wire_y - tall, 10, 2 * tall), 60)
                path.arcTo(QRectF(mid + half - 6, wire_y - tall, 10, 2 * tall), 60, -120)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
                letter = {"OTL": "L", "OTU": "U"}.get(instr.name, "")
                if letter:
                    painter.setFont(self.owner.mono_small)
                    painter.drawText(QRectF(mid - half, wire_y - tall, 2 * half, 2 * tall),
                                     int(Qt.AlignCenter), letter)
                    painter.setFont(self.owner.mono)
            tag = instr.operands[0] if instr.operands else instr.name
            room = cell.width() - 6
            lines = _two_lines(tag, fm, room)
            for n, text in enumerate(lines):
                bottom = wire_y - tall - 3 - (len(lines) - 1 - n) * fm.height()
                painter.drawText(QRectF(cell.left() + 3, bottom - fm.height(), room,
                                        fm.height()),
                                 int(Qt.AlignHCenter | Qt.AlignBottom), text)
            return
        # A box: the name on top, one operand a line below it.
        box = QRectF(cell.left() + 8, cell.top() + 6, cell.width() - 16, cell.height() - 12)
        painter.setPen(wire)
        painter.drawLine(QPointF(cell.left(), wire_y), QPointF(box.left(), wire_y))
        painter.drawLine(QPointF(box.right(), wire_y), QPointF(cell.right(), wire_y))
        painter.setPen(pen)
        painter.setBrush(colour("bg_2") if tone is None else Qt.NoBrush)
        painter.drawRect(box)
        painter.setBrush(Qt.NoBrush)
        lines = [instr.raw] if instr.raw else [instr.name] + list(instr.operands)
        lh = fm.height()
        for n, text in enumerate(lines):
            y = box.top() + 3 + n * lh
            if y + lh > box.bottom() + 1:
                break
            painter.setFont(self.owner.mono_bold if n == 0 and not instr.raw else self.owner.mono)
            painter.drawText(QRectF(box.left() + 6, y, box.width() - 12, lh),
                             int(Qt.AlignLeft | Qt.AlignVCenter),
                             fm.elidedText(text, Qt.ElideRight, box.width() - 12))
        painter.setFont(self.owner.mono)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        """A tooltip with the rung's whole text, for a tag cut short."""
        if event.type() == event.Type.ToolTip:
            index = self.at(event.pos().y())
            if index >= 0:
                pair = self.shown[index].pair
                tips = [r.text for r in (pair.left, pair.right) if r is not None]
                self.viewport().setToolTip("\n".join(tips))
        return super().viewportEvent(event)


def _two_lines(tag: str, fm: QFontMetricsF, room: float) -> list[str]:
    """A tag over at most two lines, broken after a `.`, `_` or `[` where it
    can be -- `Conveyor_Motor.` / `Run` -- and cut in the middle only when
    even that does not fit."""
    if fm.horizontalAdvance(tag) <= room:
        return [tag]
    best = -1
    for at, ch in enumerate(tag):
        if ch in "._[" and fm.horizontalAdvance(tag[:at + 1]) <= room:
            best = at + 1
    if best <= 0:
        best = 1
        while best < len(tag) and fm.horizontalAdvance(tag[:best + 1]) <= room:
            best += 1
    return [tag[:best], fm.elidedText(tag[best:], Qt.ElideMiddle, room)]


class RungView(QWidget):
    """The bar (differing only or all rungs, and the count) over the canvas."""

    currentChanged = Signal()
    openRow = Signal(int)
    command = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tokens: dict[str, str] = {}
        self.mono = mono_font({})
        self._fonts()
        self.pairs: list[L.RungPair] = []
        self.all = False
        self.canvas = RungCanvas(self)
        self.canvas.currentChanged.connect(self.currentChanged)
        self.canvas.openRow.connect(self.openRow)
        self.canvas.command.connect(self.command)
        self.only = QPushButton("Differing rungs")
        self.every = QPushButton("All rungs")
        segments = QWidget()
        segments.setProperty("role", "segments")
        segments.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(segments)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(2)
        for button, value in ((self.only, False), (self.every, True)):
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, v=value: self.set_all(v))
            seg.addWidget(button)
        self.note = QLabel()
        self.note.setProperty("role", "hint")
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(8)
        bar.addWidget(segments)
        bar.addWidget(self.note, 1)
        top = QWidget()
        top.setProperty("role", "folderbar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setLayout(bar)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(top)
        box.addWidget(self.canvas, 1)
        self._buttons()

    def _fonts(self) -> None:
        self.mono_bold = QFont(self.mono)
        self.mono_bold.setBold(True)
        self.mono_small = QFont(self.mono)
        self.mono_small.setPixelSize(max(8, self.mono.pixelSize() - 3))
        self.ui = QFont(self.font())
        self.ui_bold = QFont(self.ui)
        self.ui_bold.setBold(True)
        self.ui_italic = QFont(self.ui)
        self.ui_italic.setItalic(True)

    def _buttons(self) -> None:
        self.only.setChecked(not self.all)
        self.every.setChecked(self.all)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.mono = mono_font(tokens)
        self._fonts()
        self.canvas.relayout()

    def set_pairs(self, pairs: list[L.RungPair]) -> None:
        """A new comparison. Where the reader was is kept by rung, if it is
        still listed."""
        before = None
        if 0 <= self.canvas.current < len(self.canvas.shown):
            before = self.canvas.shown[self.canvas.current].pair
        self.pairs = pairs
        self._show(keep=before)

    def set_all(self, on: bool) -> None:
        self.all = on
        self._buttons()
        before = None
        if 0 <= self.canvas.current < len(self.canvas.shown):
            before = self.canvas.shown[self.canvas.current].pair
        self._show(keep=before)

    def _show(self, keep: L.RungPair | None = None) -> None:
        listed = [p for p in self.pairs if self.all or p.differs]
        shown = []
        for pair in listed:
            trees = tuple(L.parse(r.text) if r is not None else None
                          for r in (pair.left, pair.right))
            shown.append(_Shown(pair, trees, L.mark(*trees)))
        self.canvas.shown = shown
        self.canvas.current = -1
        if keep is not None:
            for index, item in enumerate(shown):
                if item.pair.row == keep.row:
                    self.canvas.current = index
                    break
        differing = sum(1 for p in self.pairs if p.differs)
        total = len(self.pairs)
        if not total:
            self.note.setText("")
        else:
            self.note.setText(f"{differing:,} of {total:,} rungs differ"
                              + ("" if self.all else
                                 "  ·  double-click a rung for its text"))
        self.canvas.relayout()
        self.currentChanged.emit()

    def empty_text(self) -> str:
        if not self.pairs:
            return "No rungs in these files"
        return "No rung differs. All rungs lists them."

    # The tab's navigation buttons and its count line.

    def position(self) -> tuple[int, int]:
        differing = [i for i, s in enumerate(self.canvas.shown) if s.pair.differs]
        current = differing.index(self.canvas.current) + 1 \
            if self.canvas.current in differing else 0
        return current, len(differing)

    def step(self, direction: int) -> None:
        self.canvas.step(direction)

    def go_first(self) -> None:
        differing = [i for i, s in enumerate(self.canvas.shown) if s.pair.differs]
        if differing:
            self.canvas.go(differing[0])

    def go_last(self) -> None:
        differing = [i for i, s in enumerate(self.canvas.shown) if s.pair.differs]
        if differing:
            self.canvas.go(differing[-1])

    def current_pair(self) -> L.RungPair | None:
        if 0 <= self.canvas.current < len(self.canvas.shown):
            return self.canvas.shown[self.canvas.current].pair
        return None

    def focus(self) -> None:
        self.canvas.setFocus(Qt.OtherFocusReason)
