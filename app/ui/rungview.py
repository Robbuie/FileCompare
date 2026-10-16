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

1.24: down the left, the programs and routines, as Logix Designer's
Controller Organizer lists them, each with how many of its rungs differ. A
click shows that routine's rungs alone; "All routines" shows them all again.
Boxes are drawn with Logix Designer's labels (Timer, Preset, Accum) and
status bits (EN, DN), and a comparison whose differences are not all in
rungs -- a tag value, a module -- says how many it has elsewhere.

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
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
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
    #: Per side, the instruction opposite each changed one (1.24).
    opposite: tuple[dict, dict] = ({}, {})
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
                             side, whole, pair.differs, colour, item.opposite[side])
        if current:
            pen = QPen(colour("accent_line"))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def _paint_rung(self, painter: QPainter, lay: L.Layout, marks: list[int], x0: float,
                    y0: float, width: float, side: int, whole: str | None, differs: bool,
                    colour, opposite: dict | None = None) -> None:
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
            operands: set[int] = set()
            if tone == "diff_chg" and placed.instr.shape == "box" and opposite:
                operands = L.changed_operands(placed.instr, opposite.get(placed.index))
            self._paint_instr(painter, placed.instr, cell, wy(placed.y), tone, differs, colour,
                              operands)

    def _paint_instr(self, painter: QPainter, instr: L.Instr, cell: QRectF, wire_y: float,
                     tone: str | None, differs: bool, colour,
                     operands: set[int] | frozenset = frozenset()) -> None:
        # A box that is the same instruction with some operands changed is
        # outlined in the change colour, and only those operands are filled.
        if tone is not None and not operands:
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
                letter = {"OTL": "L", "OTU": "U"}.get(instr.name, "")
                if instr.name in ("RES", "JMP", "RET"):
                    # Named coils are wider, as Logix Designer draws (RES).
                    letter = instr.name
                    half = 17.0
                    painter.setPen(wire)
                    painter.drawLine(QPointF(cell.left(), wire_y), QPointF(mid - half, wire_y))
                    painter.drawLine(QPointF(mid + half, wire_y), QPointF(cell.right(), wire_y))
                    painter.setPen(pen)
                path = QPainterPath()
                path.arcMoveTo(QRectF(mid - half - 4, wire_y - tall, 10, 2 * tall), 120)
                path.arcTo(QRectF(mid - half - 4, wire_y - tall, 10, 2 * tall), 120, 120)
                path.arcMoveTo(QRectF(mid + half - 6, wire_y - tall, 10, 2 * tall), 60)
                path.arcTo(QRectF(mid + half - 6, wire_y - tall, 10, 2 * tall), 60, -120)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
                if letter:
                    painter.setFont(self.owner.mono_small)
                    painter.drawText(QRectF(mid - half, wire_y - tall, 2 * half, 2 * tall),
                                     int(Qt.AlignCenter), letter)
                    painter.setFont(self.owner.mono)
            tag = instr.operands[0] if instr.operands else (
                "" if instr.name in ("RET",) else instr.name)
            room = cell.width() - 6
            lines = _two_lines(tag, fm, room)
            for n, text in enumerate(lines):
                bottom = wire_y - tall - 3 - (len(lines) - 1 - n) * fm.height()
                painter.drawText(QRectF(cell.left() + 3, bottom - fm.height(), room,
                                        fm.height()),
                                 int(Qt.AlignHCenter | Qt.AlignBottom), text)
            return
        # A box as Logix Designer draws one (1.24): its name and what it is
        # on the top line, each operand under it with the operand's label on
        # the left and its tag or value on the right, and the status bits
        # (EN, DN, ER) down the right edge.
        known = L.spec(instr.name) if not instr.raw else None
        pins = known.pins if known is not None else ()
        lh = fm.height()
        small = QFontMetricsF(self.owner.mono_small)
        step = max(lh, small.height() * 1.6)
        # As tall as what it holds -- its lines, or its status bits under
        # the wire -- and never taller than its cell.
        lines = 1 if instr.raw else 1 + len(instr.operands)
        need = max(lines * lh + 8, (wire_y - cell.top() - 6) + max(0, len(pins) - 1) * step
                   + small.height() / 2 + 8, wire_y - cell.top() - 6 + lh)
        box = QRectF(cell.left() + 8, cell.top() + 6, cell.width() - 16,
                     min(cell.height() - 12, need))
        painter.setPen(wire)
        painter.drawLine(QPointF(cell.left(), wire_y), QPointF(box.left(), wire_y))
        painter.drawLine(QPointF(box.right(), wire_y), QPointF(cell.right(), wire_y))
        painter.setPen(pen)
        painter.setBrush(colour("bg_2") if tone is None or operands else Qt.NoBrush)
        painter.drawRect(box)
        painter.setBrush(Qt.NoBrush)
        if operands:
            # Outlined in the change colour; its text plain but for the
            # operands that changed.
            changed_pen = pen
            pen = QPen(colour("txt_0"))
            painter.setPen(pen)
            tone_text = None
        else:
            changed_pen = pen
            tone_text = tone
        pin_w = small.horizontalAdvance("MM") + 10 if pins else 0
        text_w = box.width() - 12 - pin_w
        if instr.raw:
            painter.drawText(QRectF(box.left() + 6, box.top() + 3, text_w, lh),
                             int(Qt.AlignLeft | Qt.AlignVCenter),
                             fm.elidedText(instr.raw, Qt.ElideRight, text_w))
            painter.setFont(self.owner.mono)
            return
        painter.setFont(self.owner.mono_bold)
        head = QRectF(box.left() + 6, box.top() + 3, text_w, lh)
        painter.drawText(head, int(Qt.AlignLeft | Qt.AlignVCenter), instr.name)
        used = QFontMetricsF(self.owner.mono_bold).horizontalAdvance(instr.name) + 10
        if known is not None and used < text_w:
            painter.setFont(self.owner.ui)
            painter.setPen(QPen(colour("txt_2") if tone_text is None else ink))
            painter.drawText(head.adjusted(used, 0, 0, 0), int(Qt.AlignLeft | Qt.AlignVCenter),
                             self.ui.elidedText(known.title, Qt.ElideRight, text_w - used))
            painter.setPen(pen)
        painter.setFont(self.owner.mono)
        for n, (label, value) in enumerate(L.box_lines(instr)):
            y = box.top() + 3 + (n + 1) * lh
            if y + lh > box.bottom() + 1:
                break
            row = QRectF(box.left() + 6, y, text_w, lh)
            if n in operands:
                painter.fillRect(row.adjusted(-4, 0, 4, 0), colour(tone + "_row"))
            if label:
                painter.setFont(self.owner.ui)
                painter.setPen(QPen(colour("txt_2") if tone_text is None else ink))
                painter.drawText(row, int(Qt.AlignLeft | Qt.AlignVCenter), label)
                room = text_w - self.ui.horizontalAdvance(label) - 10
                painter.setFont(self.owner.mono)
                painter.setPen(changed_pen if n in operands else pen)
                painter.drawText(row, int(Qt.AlignRight | Qt.AlignVCenter),
                                 fm.elidedText(value, Qt.ElideLeft, max(0.0, room)))
            else:
                painter.setPen(changed_pen if n in operands else pen)
                painter.drawText(row, int(Qt.AlignLeft | Qt.AlignVCenter),
                                 fm.elidedText(value, Qt.ElideRight, text_w))
        if pins:
            # The first bit sits on the rung's wire, the others under it.
            painter.setFont(self.owner.mono_small)
            painter.setPen(QPen(colour("txt_2") if tone_text is None else ink))
            for n, pin in enumerate(pins):
                y = wire_y + n * step
                if y + small.height() / 2 > box.bottom():
                    break
                painter.drawText(QRectF(box.right() - pin_w, y - small.height() / 2,
                                        pin_w - 4, small.height()),
                                 int(Qt.AlignRight | Qt.AlignVCenter), pin)
            painter.setPen(pen)
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


ALL = ""                        # the routine list's "All routines"
_ENTRY = Qt.UserRole + 1


class _RoutineDelegate(QStyledItemDelegate):
    """A program as a small heading; a routine as its name with its count of
    differing rungs, a dot in the difference colour when there are some."""

    def __init__(self, owner: "RoutineList") -> None:
        super().__init__(owner)
        self.owner = owner

    def sizeHint(self, option, index):  # noqa: N802
        size = super().sizeHint(option, index)
        line = QFontMetricsF(option.font).height()
        heading = index.data(_ENTRY) is None
        size.setHeight(int(line + (14 if heading else 12)))
        return size

    def paint(self, painter: QPainter, option, index) -> None:
        tokens = self.owner.tokens
        colour = lambda name: parse_colour(tokens.get(name))  # noqa: E731
        entry = index.data(_ENTRY)
        text = index.data(Qt.DisplayRole) or ""
        rect = QRectF(option.rect)
        painter.save()
        base = QFont(option.font)
        if entry is None:
            small = QFont(base)
            small.setBold(True)
            small.setPixelSize(max(9, (base.pixelSize() if base.pixelSize() > 0 else 13) - 2))
            painter.setFont(small)
            painter.setPen(colour("txt_2"))
            inner = rect.adjusted(10, 4, -10, 0)
            painter.drawText(inner, int(Qt.AlignLeft | Qt.AlignVCenter),
                             QFontMetricsF(small).elidedText(text.upper(), Qt.ElideRight,
                                                             inner.width()))
            painter.restore()
            return
        key, differing, total = entry
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, colour("accent_row"))
            painter.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), colour("accent"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, colour("bg_3"))
        indent = 12 if key == ALL else 22
        if differing:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour("diff_chg_bar"))
            painter.drawEllipse(QRectF(rect.left() + indent - 10, rect.center().y() - 3, 6, 6))
        bold = QFont(base)
        bold.setBold(key == ALL)
        count = f"{differing:,} of {total:,}" if total else ""
        fm = QFontMetricsF(base)
        room = rect.width() - indent - fm.horizontalAdvance(count) - 22
        painter.setFont(bold)
        painter.setPen(colour("txt_0" if differing or key == ALL else "txt_2"))
        painter.drawText(rect.adjusted(indent, 0, 0, 0), int(Qt.AlignLeft | Qt.AlignVCenter),
                         QFontMetricsF(bold).elidedText(text, Qt.ElideRight, max(0.0, room)))
        painter.setFont(base)
        painter.setPen(colour("txt_1" if differing else "txt_2"))
        painter.drawText(rect.adjusted(0, 0, -10, 0), int(Qt.AlignRight | Qt.AlignVCenter),
                         count)
        painter.restore()


class RoutineList(QWidget):
    """The programs and routines of a Logix comparison (1.24), Controller
    Organizer style. Emits `chosen(key)`: a routine's "Program X / Routine"
    or ALL."""

    chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.tokens: dict[str, str] = {}
        self.tree = QTreeWidget()
        self.tree.setProperty("role", "difflist")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setMouseTracking(True)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.setItemDelegate(_RoutineDelegate(self))
        self.tree.itemClicked.connect(self._clicked)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 0, 6)
        box.setSpacing(0)
        box.addWidget(self.tree, 1)
        self.setMinimumWidth(180)
        self._items: dict[str, QTreeWidgetItem] = {}

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.tree.viewport().update()

    def set_pairs(self, pairs: list[L.RungPair], current: str) -> None:
        counts: dict[str, list[int]] = {}
        for pair in pairs:
            key = L.routine_of(pair)
            entry = counts.setdefault(key, [0, 0])
            entry[1] += 1
            if pair.differs:
                entry[0] += 1
        self.tree.clear()
        self._items = {}
        everything = QTreeWidgetItem(["All routines"])
        everything.setData(0, _ENTRY, (ALL, sum(c[0] for c in counts.values()),
                                       sum(c[1] for c in counts.values())))
        self.tree.addTopLevelItem(everything)
        self._items[ALL] = everything
        # Grouped by program (or AOI), in the order the comparison has them,
        # which is by name: the order the comparers sort them in.
        heading = None
        for key, (differing, total) in counts.items():
            group, _sep, routine = key.partition(" / ")
            if not routine:
                group, routine = "", key or "(no routine)"
            if group != heading:
                heading = group
                if group:
                    head = QTreeWidgetItem([group])
                    head.setFlags(Qt.ItemIsEnabled)
                    self.tree.addTopLevelItem(head)
            item = QTreeWidgetItem([routine])
            item.setData(0, _ENTRY, (key, differing, total))
            item.setToolTip(0, f"{key}\n{differing:,} of {total:,} rungs differ")
            self.tree.addTopLevelItem(item)
            self._items[key] = item
        self.set_current(current)

    def set_current(self, key: str) -> None:
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        item = self._items.get(key) or self._items.get(ALL)
        if item is not None:
            item.setSelected(True)
            self.tree.scrollToItem(item)
        self.tree.blockSignals(False)

    def _clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        entry = item.data(0, _ENTRY)
        if entry is not None:
            self.chosen.emit(entry[0])


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
        #: The routine shown alone, or ALL (1.24).
        self.routine = ALL
        #: Differences the comparison has outside rungs (1.24).
        self.others = 0
        self.routines = RoutineList()
        self.routines.chosen.connect(self.set_routine)
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
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(top)
        column.addWidget(self.canvas, 1)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(1)
        self.split.addWidget(self.routines)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([230, 1000])
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self.split, 1)
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
        self.routines.apply_tokens(tokens)
        self.canvas.relayout()

    def set_pairs(self, pairs: list[L.RungPair], others: int = 0) -> None:
        """A new comparison. Where the reader was is kept by rung, if it is
        still listed, and the routine shown alone stays shown if it is still
        there. `others` is how many differences are not in rungs."""
        before = None
        if 0 <= self.canvas.current < len(self.canvas.shown):
            before = self.canvas.shown[self.canvas.current].pair
        self.pairs = pairs
        self.others = others
        if self.routine != ALL and not any(L.routine_of(p) == self.routine for p in pairs):
            self.routine = ALL
        self.routines.set_pairs(pairs, self.routine)
        self._show(keep=before)

    def set_routine(self, key: str) -> None:
        """One routine's rungs alone, or ALL of them."""
        self.routine = key
        self.routines.set_current(key)
        self._show()
        if self.canvas.current < 0:
            self.go_first()
            if self.canvas.current < 0 and self.canvas.shown:
                self.canvas.go(0)

    def set_all(self, on: bool) -> None:
        self.all = on
        self._buttons()
        before = None
        if 0 <= self.canvas.current < len(self.canvas.shown):
            before = self.canvas.shown[self.canvas.current].pair
        self._show(keep=before)

    def _show(self, keep: L.RungPair | None = None) -> None:
        listed = [p for p in self.pairs if (self.all or p.differs)
                  and (self.routine == ALL or L.routine_of(p) == self.routine)]
        shown = []
        for pair in listed:
            trees = tuple(L.parse(r.text) if r is not None else None
                          for r in (pair.left, pair.right))
            shown.append(_Shown(pair, trees, L.mark(*trees), L.counterparts(*trees)))
        self.canvas.shown = shown
        self.canvas.current = -1
        if keep is not None:
            for index, item in enumerate(shown):
                if item.pair.row == keep.row:
                    self.canvas.current = index
                    break
        scope = [p for p in self.pairs
                 if self.routine == ALL or L.routine_of(p) == self.routine]
        differing = sum(1 for p in scope if p.differs)
        total = len(scope)
        parts = []
        if total:
            parts.append(f"{differing:,} of {total:,} rungs differ")
        if self.others:
            # The rung view draws rungs only; a changed tag value or module
            # is in the text view, and this says so rather than leave the
            # count of rungs looking like the whole answer.
            parts.append(f"{self.others:,} other difference{'s' if self.others != 1 else ''}"
                         " (tags, modules, types) in Text view")
        if total and not self.all:
            parts.append("double-click a rung for its text")
        self.note.setText("  ·  ".join(parts))
        self.canvas.relayout()
        self.currentChanged.emit()

    def empty_text(self) -> str:
        if not self.pairs:
            return "No rungs in these files"
        where = "in this routine" if self.routine != ALL else ""
        tail = (f"  {self.others:,} other difference{'s' if self.others != 1 else ''}"
                " in Text view." if self.others else "")
        return f"No rung differs {where}".rstrip() + ". All rungs lists them." + tail

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
