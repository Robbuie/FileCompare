"""The side-by-side text view: two painted panes, a gutter, an overview map.

Painted rather than built from two `QPlainTextEdit`s, for the reason CLAUDE.md
gives: two independent documents cannot be kept aligned with filler rows, and
neither survives a 200 MB log. Here both panes draw the same row list from
`core/diff/align.py`, starting at the same row, so they cannot drift -- the
synchronised scroll is not a feature that was added, it is the absence of a
second scroll position.

Only the rows on screen are painted, and the intraline marks are worked out
for those rows only, on first paint, and cached until the comparison changes.

Everything is in one module because the four widgets share one state object
(`ViewState`) and have no life apart from each other. None of them touches a
file.

The text is assumed to be monospaced for placing marks and for horizontal
scrolling -- the width of "0" times the column. That is true of Cascadia Mono
and Consolas for everything a source file or a log usually holds; a line of
wide East Asian characters will have its marks drift. Measuring every prefix
instead would be correct and would cost a font measurement per mark per paint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.diff import align, intraline

TAB = 4

#: Rows the wheel moves per notch.
WHEEL_ROWS = 3

#: Where a difference lands when stepped to, as a share of the view's height
#: from the top. A third leaves room to see what comes before it.
LANDING = 0.3


@dataclass
class ViewState:
    rows: list = field(default_factory=list)
    lines: tuple[list[str], list[str]] = ((), ())  # type: ignore[assignment]
    blocks: list = field(default_factory=list)
    first: int = 0
    x: int = 0
    current: int | None = None          # index into blocks
    mode: str = "char"
    marks: dict = field(default_factory=dict)  # row -> (left spans, right spans)
    #: The selection: rows `anchor` to `cursor`, on the focused side.
    cursor: int = 0
    anchor: int = 0
    side: int = 0
    #: Which sides can be edited, so the gutter offers only real copies.
    editable: tuple[bool, bool] = (False, False)
    #: What the find bar is looking for, compiled; None when it is closed.
    find: re.Pattern | None = None
    #: 1.1: per side, `(lines, spans per line)` from `core/syntax.py`, or
    #: None. Held with the very list it was lexed from, and used only while
    #: that is still the list being drawn -- after an edit the rows move on
    #: before a new lexing arrives, and old colours on new lines would be
    #: colours on the wrong words.
    syntax: list = field(default_factory=lambda: [None, None])
    #: 1.5: rows that are one end of a move, and the comparison that says
    #: where the other end is.
    moved: set = field(default_factory=set)
    comparison: object = None
    #: 1.6: rows held by a pin, and the half-made pin -- `(side, row)` of the
    #: line picked first -- while the other line is being chosen.
    pinned: set = field(default_factory=set)
    pending: tuple | None = None

    def syntax_spans(self, side: int, index: int):
        held = self.syntax[side]
        if held is None or held[0] is not self.lines[side]:
            return None
        spans = held[1]
        return spans[index] if 0 <= index < len(spans) else None

    def selection(self) -> tuple[int, int]:
        """Rows selected, as `(first, stop)`."""
        lo, hi = sorted((self.anchor, self.cursor))
        return lo, hi + 1

    def copyable(self) -> tuple[int, int] | None:
        """The selected rows, when they are worth copying across on their own
        (1.13): two or more rows, at least one of them not equal. A single
        row is where the cursor is, not a choice, and copies its whole
        difference as it always has."""
        if not self.rows:
            return None
        lo, hi = self.selection()
        hi = min(hi, len(self.rows))
        if hi - lo < 2:
            return None
        if any(self.rows[r][2] != align.EQUAL for r in range(lo, hi)):
            return lo, hi
        return None

    def display(self, side: int, index: int) -> str:
        if index == align.NONE:
            return ""
        return self.lines[side][index].expandtabs(TAB)

    def spans(self, row: int) -> tuple[list, list]:
        hit = self.marks.get(row)
        if hit is not None:
            return hit
        left, right, kind = self.rows[row]
        if kind in (align.CHANGED, align.IGNORED) and left != align.NONE and right != align.NONE:
            hit = intraline.spans(self.display(0, left), self.display(1, right), self.mode)
        else:
            hit = ([], [])
        self.marks[row] = hit
        return hit


def parse_colour(value: str | None) -> QColor:
    """A token as a `QColor`. The derived tints are written `rgba(r, g, b, a)`
    for the stylesheet, which `QColor` does not read -- given one it comes back
    invalid and paints black, which is how the current-difference outline
    first rendered on the light theme."""
    if not value:
        return QColor()
    text = value.strip()
    if text.startswith("rgba(") and text.endswith(")"):
        try:
            r, g, b, a = (part.strip() for part in text[5:-1].split(","))
            colour = QColor(int(r), int(g), int(b))
            colour.setAlphaF(float(a))
            return colour
        except ValueError:
            return QColor()
    return QColor(text)


def mono_font(tokens: dict[str, str]) -> QFont:
    font = QFont()
    font.setFamilies(["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
    font.setStyleHint(QFont.Monospace)
    size = float(str(tokens.get("ui_font", "13px")).rstrip("px") or 13)
    font.setPixelSize(max(9, round(size)))
    return font


class _Painted(QWidget):
    """Shared plumbing: the state, the tokens, the metrics."""

    wheeled = Signal(int)
    clicked = Signal(int)
    #: (row, extend): a press, and whether Shift was held.
    pressed = Signal(int, bool)
    dragged = Signal(int)
    doubleClicked = Signal(int)
    #: 1.13: (row, global position) of a right-click.
    menuAt = Signal(int, object)

    def __init__(self, state: ViewState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.tokens: dict[str, str] = {}
        self.row_h = 20
        self.char_w = 8.0
        self.ascent = 14.0
        # Kept apart from `self.font()` on purpose: the application stylesheet
        # sets the UI family on every QWidget, and a stylesheet font beats
        # `setFont`, so `self.font()` is Segoe UI however often it is set.
        # Every column is placed by the width of "0" in this font, so painting
        # in any other one puts colours and marks beside the text they belong
        # to (1.11.1).
        self.mono = mono_font({})
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def apply_tokens(self, tokens: dict[str, str], font: QFont) -> None:
        self.tokens = tokens
        self.mono = QFont(font)
        self.setFont(font)
        metrics = QFontMetricsF(font)
        self.row_h = int(metrics.height() + 5)
        self.char_w = metrics.horizontalAdvance("0")
        self.ascent = metrics.ascent()
        self.update()

    def colour(self, name: str) -> QColor:
        return parse_colour(self.tokens.get(name))

    def syntax_colours(self) -> list[QColor]:
        """Index by `syntax.CATEGORIES`; 0 is the ordinary ink."""
        cached = getattr(self, "_syntax_colours", None)
        if cached is not None and cached[0] is self.tokens:
            return cached[1]
        from app.core.syntax import CATEGORIES

        colours = [self.colour("txt_0")] + [
            self.colour(f"syn_{name}") if self.tokens.get(f"syn_{name}")
            else self.colour("txt_0") for name in CATEGORIES[1:]]
        self._syntax_colours = (self.tokens, colours)
        return colours

    def visible_rows(self) -> int:
        return max(1, self.height() // max(1, self.row_h))

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.wheeled.emit(int(-steps * WHEEL_ROWS) or (-1 if steps > 0 else 1))
        event.accept()

    def row_at(self, y: float) -> int:
        return self.state.first + int(y // max(1, self.row_h))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            row = self.row_at(event.position().y())
            self.pressed.emit(row, bool(event.modifiers() & Qt.ShiftModifier))
            self.clicked.emit(row)
        elif event.button() == Qt.RightButton:
            self.menuAt.emit(self.row_at(event.position().y()),
                             event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.dragged.emit(self.row_at(event.position().y()))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.row_at(event.position().y()))


class TextPane(_Painted):
    """One side's rows: line numbers, washes, marks, text."""

    def __init__(self, state: ViewState, side: int, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self.side = side
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumWidth(120)

    def number_width(self) -> float:
        count = max(1, len(self.state.lines[self.side]))
        return self.char_w * (len(str(count)) + 2)

    def text_columns(self) -> int:
        return max(1, int((self.width() - self.number_width() - 8) // max(1.0, self.char_w)))

    def longest(self) -> int:
        """Widest line on this side, in columns. Cached per comparison."""
        cached = getattr(self, "_longest", None)
        key = id(self.state.lines[self.side])
        if cached is not None and cached[0] == key:
            return cached[1]
        widest = max((len(line.expandtabs(TAB)) for line in self.state.lines[self.side]),
                     default=0)
        self._longest = (key, widest)
        return widest

    def paintEvent(self, event) -> None:  # noqa: N802
        s = self.state
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.colour("bg_2"))
        numbers = self.number_width()
        text_x = numbers + 8
        painter.fillRect(QRectF(0, 0, numbers, self.height()), self.colour("bg_1"))

        side = self.side
        own_only = align.DELETED if side == 0 else align.INSERTED
        washes = {
            align.CHANGED: self.colour("diff_chg_row"),
            align.DELETED: self.colour("diff_del_row"),
            align.INSERTED: self.colour("diff_add_row"),
            align.IGNORED: self.colour("diff_ignored_row"),
        }
        mark_colours = {
            align.CHANGED: self.colour("diff_chg_mark"),
            align.IGNORED: self.colour("diff_ignored_mark"),
        }
        moved_wash = self.colour("diff_moved_row")
        filler = self.colour("diff_filler")
        ink = self.colour("txt_0")
        muted = self.colour("txt_2")
        dim = self.colour("txt_1")
        first_col = int(s.x // max(1.0, self.char_w))
        cols = self.text_columns() + 2
        offset = s.x - first_col * self.char_w

        select_edge = self.colour("accent")
        select = QColor(select_edge)
        select.setAlphaF(0.16)
        selected_lo, selected_hi = s.selection() if s.side == side else (0, 0)
        found = self.colour("find_mark")

        painter.setFont(self.mono)
        end = min(len(s.rows), s.first + self.visible_rows() + 1)
        for row in range(s.first, end):
            y = (row - s.first) * self.row_h
            index = s.rows[row][side]
            if index == align.NONE and selected_lo <= row < selected_hi:
                painter.fillRect(QRectF(0, y, self.width(), self.row_h), filler)
                painter.fillRect(QRectF(numbers, y, self.width() - numbers, self.row_h), select)
                continue
            kind = s.rows[row][2]
            band = QRectF(0, y, self.width(), self.row_h)
            text_band = QRectF(numbers, y, self.width() - numbers, self.row_h)
            if index == align.NONE:
                painter.fillRect(band, filler)
                continue
            if kind != align.EQUAL:
                moved = row in s.moved
                wash = moved_wash if moved else washes.get(kind)
                if kind in (align.DELETED, align.INSERTED) and kind != own_only:
                    wash = None
                if wash is not None:
                    painter.fillRect(text_band, wash)
                    # The line number column carries the colour too, so a
                    # change is visible with the text scrolled away from it.
                    painter.fillRect(QRectF(0, y, 3, self.row_h), self.colour(
                        "diff_moved_bar" if moved else _bar_name(kind)))
            if kind in mark_colours:
                spans = s.spans(row)[side]
                if spans:
                    colour = mark_colours[kind]
                    for start, stop in spans:
                        if stop <= first_col or start >= first_col + cols:
                            continue
                        x0 = text_x + (max(start, first_col) - first_col) * self.char_w - offset
                        x1 = text_x + (min(stop, first_col + cols) - first_col) * self.char_w - offset
                        painter.fillRect(QRectF(x0, y + 1, max(2.0, x1 - x0), self.row_h - 2),
                                         colour)
            if selected_lo <= row < selected_hi:
                painter.fillRect(text_band, select)
                painter.fillRect(QRectF(numbers, y, 2, self.row_h), select_edge)
            if s.pending == (side, row):
                # The first half of a pin: outlined in the accent until the
                # line for the other side is chosen.
                painter.setPen(QPen(select_edge, 1, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(QRectF(numbers + 1, y + 0.5, self.width() - numbers - 2,
                                        self.row_h - 1))
            if s.find is not None:
                line = s.display(side, index)
                for match in s.find.finditer(line):
                    start, stop = match.span()
                    if stop == start or stop <= first_col or start >= first_col + cols:
                        continue
                    x0 = text_x + (max(start, first_col) - first_col) * self.char_w - offset
                    x1 = text_x + (min(stop, first_col + cols) - first_col) * self.char_w - offset
                    painter.fillRect(QRectF(x0, y + 1, x1 - x0, self.row_h - 2), found)
            painter.setPen(dim if kind != align.EQUAL else muted)
            painter.drawText(QRectF(0, y, numbers - self.char_w, self.row_h),
                             Qt.AlignRight | Qt.AlignVCenter, str(index + 1))
            text = s.display(side, index)[first_col:first_col + cols]
            if text:
                painter.setClipRect(text_band)
                spans = s.syntax_spans(side, index)
                if not spans:
                    painter.setPen(ink)
                    painter.drawText(QRectF(text_x - offset, y, self.width(), self.row_h),
                                     Qt.AlignLeft | Qt.AlignVCenter | Qt.TextDontClip, text)
                else:
                    self._paint_coloured(painter, text, spans, first_col, text_x - offset, y)
                painter.setClipping(False)

        if s.rows and end <= s.first + self.visible_rows():
            # Past the last row: the pane's own surface, nothing else.
            pass
        self._paint_current(painter)
        painter.setPen(QPen(self.colour("line_soft"), 1))
        painter.drawLine(int(numbers), 0, int(numbers), self.height())
        painter.end()

    def _paint_coloured(self, painter: QPainter, text: str, spans, first_col: int,
                        x: float, y: float) -> None:
        """One line in pieces, each in its category's colour. The pieces are
        placed by column, which is the monospace assumption the marks already
        make; a piece is never measured."""
        colours = self.syntax_colours()
        flags = Qt.AlignLeft | Qt.AlignVCenter | Qt.TextDontClip
        end = first_col + len(text)
        pos = first_col

        def draw(start: int, stop: int, colour: QColor) -> None:
            painter.setPen(colour)
            painter.drawText(QRectF(x + (start - first_col) * self.char_w, y,
                                    (stop - start + 1) * self.char_w, self.row_h),
                             flags, text[start - first_col:stop - first_col])

        for start, stop, cat in spans:
            if stop <= pos:
                continue
            if start >= end:
                break
            if start > pos:
                draw(pos, start, colours[0])
            a, b = max(start, pos), min(stop, end)
            draw(a, b, colours[cat] if cat < len(colours) else colours[0])
            pos = b
        if pos < end:
            draw(pos, end, colours[0])

    def _paint_current(self, painter: QPainter) -> None:
        s = self.state
        if s.current is None or s.current >= len(s.blocks):
            return
        block = s.blocks[s.current]
        top = (block.start - s.first) * self.row_h
        bottom = (block.end - s.first) * self.row_h
        if bottom < 0 or top > self.height():
            return
        pen = QPen(self.colour("accent_line"), 1)
        painter.setPen(pen)
        painter.drawLine(0, top, self.width(), top)
        painter.drawLine(0, bottom - 1, self.width(), bottom - 1)


def _triangle(x_tip: float, x_base: float, y: float, half: float) -> QPolygonF:
    return QPolygonF([QPointF(x_tip, y), QPointF(x_base, y - half), QPointF(x_base, y + half)])


def _bar_name(kind: int) -> str:
    return {align.CHANGED: "diff_chg_bar", align.DELETED: "diff_del_bar",
            align.INSERTED: "diff_add_bar", align.IGNORED: "diff_ignored_bar"}[kind]


def _block_bar(block) -> str:
    """A block's colour: its kind's, or the move colour for either end of a
    move. Hex view blocks have no `move`, hence the default."""
    if getattr(block, "move", -1) >= 0:
        return "diff_moved_bar"
    return _bar_name(block.kind)


class Gutter(_Painted):
    """Between the panes: which rows differ, and the arrows that copy across.

    Each difference on screen has a strip in its colour down the middle and,
    at its top, an arrow toward each side that can be edited: the left arrow
    copies the right side's lines over the left's, and the other way round.
    The same as Alt+Left and Alt+Right on the current difference.
    """

    WIDTH = 30
    #: (block index, side to copy to)
    copyRequested = Signal(int, int)
    #: 1.13: (first row, stop row, side to copy to), from the selection's arrows.
    copyRowsRequested = Signal(int, int, int)

    def __init__(self, state: ViewState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self.setFixedWidth(self.WIDTH)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def _selection_arrow_at(self, x: float, y: float) -> tuple[int, int, int] | None:
        picked = self.state.copyable()
        if picked is None or self.row_at(y) != picked[0]:
            return None
        to_side = 0 if x < self.width() / 2 else 1
        if self.state.editable[to_side]:
            return picked[0], picked[1], to_side
        return None

    def _arrow_at(self, x: float, y: float) -> tuple[int, int] | None:
        row = self.row_at(y)
        picked = self.state.copyable()
        if picked is not None and row == picked[0]:
            return None             # the selection's arrows are drawn there
        for index, block in enumerate(self.state.blocks):
            if block.start == row and block.significant:
                to_side = 0 if x < self.width() / 2 else 1
                if self.state.editable[to_side]:
                    return index, to_side
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            x, y = event.position().x(), event.position().y()
            picked = self._selection_arrow_at(x, y)
            if picked is not None:
                self.copyRowsRequested.emit(*picked)
                event.accept()
                return
            hit = self._arrow_at(x, y)
            if hit is not None:
                self.copyRequested.emit(*hit)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        picked = self._selection_arrow_at(x, y)
        if picked is not None:
            count = picked[1] - picked[0]
            self.setToolTip(f"Copy the {count} selected rows to the "
                            + ("left (Alt+Left)" if picked[2] == 0 else "right (Alt+Right)"))
            return
        hit = self._arrow_at(x, y)
        if hit is None:
            self.setToolTip("")
        else:
            self.setToolTip("Copy to the left (Alt+Left)" if hit[1] == 0
                            else "Copy to the right (Alt+Right)")

    def paintEvent(self, event) -> None:  # noqa: N802
        s = self.state
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.colour("bg_1"))
        end = min(len(s.rows), s.first + self.visible_rows() + 1)
        mid = self.width() / 2
        picked = s.copyable()
        for block_index, block in enumerate(s.blocks):
            if block.end <= s.first or block.start >= end:
                continue
            top = (max(block.start, s.first) - s.first) * self.row_h
            bottom = (min(block.end, end) - s.first) * self.row_h
            colour = self.colour(_block_bar(block))
            current = block_index == s.current
            width = 6 if current else 4
            painter.fillRect(QRectF(mid - width / 2, top + 1, width, max(2, bottom - top - 2)),
                             colour)
            if current:
                painter.setPen(QPen(self.colour("accent"), 1.5))
                painter.drawLine(2, int(top), 2, int(bottom))
                painter.drawLine(self.width() - 3, int(top), self.width() - 3, int(bottom))
            if block.significant and s.first <= block.start < end:
                if picked is None or block.start != picked[0]:
                    self._arrows(painter, top, current)
        if picked is not None:
            # The selection's own bracket and arrows, in the accent: these are
            # the rows the arrows will copy, whichever differences they cut.
            lo, hi = max(picked[0], s.first), min(picked[1], end)
            if lo < hi:
                top = (lo - s.first) * self.row_h
                bottom = (hi - s.first) * self.row_h
                wash = QColor(self.colour("accent"))
                wash.setAlphaF(0.16)
                painter.fillRect(QRectF(1, top, self.width() - 2, bottom - top), wash)
                painter.setPen(QPen(self.colour("accent"), 1.5))
                painter.drawLine(QPointF(2, top + 1), QPointF(2, bottom - 1))
                painter.drawLine(QPointF(self.width() - 3, top + 1),
                                 QPointF(self.width() - 3, bottom - 1))
            if s.first <= picked[0] < end:
                self._arrows(painter, (picked[0] - s.first) * self.row_h, True,
                             colour=self.colour("accent"))
        if s.pinned:
            # A pin is a bar straight across, in the accent: these two lines
            # are opposite each other because somebody said so.
            pen = QPen(self.colour("accent"), 2)
            for row in s.pinned:
                if s.first <= row < end:
                    y = (row - s.first) * self.row_h + self.row_h / 2
                    painter.setPen(pen)
                    painter.drawLine(QPointF(1, y), QPointF(self.width() - 1, y))
        painter.setPen(QPen(self.colour("line_soft"), 1))
        painter.drawLine(0, 0, 0, self.height())
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        painter.end()

    def _arrows(self, painter: QPainter, top: float, current: bool,
                colour: QColor | None = None) -> None:
        y = top + self.row_h / 2
        colour = colour if colour is not None else self.colour("txt_0" if current else "txt_1")
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        half = min(5.0, self.row_h / 3)
        if self.state.editable[0]:
            painter.drawPolygon(_triangle(4, 11, y, half))
        if self.state.editable[1]:
            painter.drawPolygon(_triangle(self.width() - 4, self.width() - 11, y, half))
        painter.setBrush(Qt.NoBrush)


class DiffMap(QWidget):
    """The whole comparison in one strip: every difference, and the view.

    Two columns, left side and right side, so a block only on one side is
    visibly on that side. Click or drag to move the view there; the wheel
    scrolls. It replaces the vertical scrollbar rather than sitting beside
    one: two controls that both mean "where am I" is one too many.
    """

    WIDTH = 18
    moved = Signal(float)       # the fraction of the rows to centre on
    wheeled = Signal(int)

    def __init__(self, state: ViewState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.tokens: dict[str, str] = {}
        self.visible = 1
        self.setFixedWidth(self.WIDTH)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Every difference in the file. Click or drag to go there.")

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        s = self.state
        painter = QPainter(self)
        painter.fillRect(self.rect(), parse_colour(self.tokens.get("bg_1")))
        total = max(1, len(s.rows))
        height = self.height() - 4
        column = (self.width() - 6) / 2
        for block in s.blocks:
            y0 = 2 + block.start / total * height
            y1 = 2 + block.end / total * height
            box_h = max(2.0, y1 - y0)
            colour = parse_colour(self.tokens.get(_block_bar(block)))
            left, right = self._sides(block)
            if left:
                painter.fillRect(QRectF(2, y0, column, box_h), colour)
            if right:
                painter.fillRect(QRectF(4 + column, y0, column, box_h), colour)
        # The view.
        if s.rows:
            v0 = 2 + s.first / total * height
            v1 = 2 + min(total, s.first + self.visible) / total * height
            frame = parse_colour(self.tokens.get("txt_1"))
            fill = QColor(frame)
            fill.setAlphaF(0.12)
            painter.fillRect(QRectF(1, v0, self.width() - 2, max(4.0, v1 - v0)), fill)
            pen = QPen(frame, 1)
            painter.setPen(pen)
            painter.drawRect(QRectF(1, v0, self.width() - 3, max(4.0, v1 - v0)))
        painter.end()

    def _sides(self, block) -> tuple[bool, bool]:
        if block.kind == align.DELETED:
            return True, False
        if block.kind == align.INSERTED:
            return False, True
        return True, True

    def _jump(self, y: float) -> None:
        height = max(1, self.height() - 4)
        self.moved.emit(max(0.0, min(1.0, (y - 2) / height)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._jump(event.position().y())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self._jump(event.position().y())

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.wheeled.emit(int(-steps * WHEEL_ROWS) or (-1 if steps > 0 else 1))
        event.accept()


class LineEditor(QPlainTextEdit):
    """Editing a run of lines in place, over the pane that shows them.

    The panes are painted, so they cannot take a caret. Instead, Enter (or a
    double-click) opens this over the selected rows of the focused side with
    their text in it; Ctrl+Enter or clicking away puts the text back as one
    edit, Escape leaves the lines as they were. The block it replaces is
    exactly the lines that were selected, so adding or removing lines inside
    it is an ordinary edit and the diff runs again when it lands.
    """

    #: (side, first row, stop row, text)
    committed = Signal(int, int, int, str)
    cancelled = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("role", "lineeditor")
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabChangesFocus(False)
        self.side = 0
        self.rows = (0, 0)
        self._done = True
        self.hide()

    def begin(self, side: int, rows: tuple[int, int], text: str, font: QFont) -> None:
        self.side = side
        self.rows = rows
        self._done = False
        self.setFont(font)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * TAB)
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    def finish(self, keep: bool) -> None:
        if self._done:
            return
        self._done = True
        self.hide()
        if keep:
            self.committed.emit(self.side, self.rows[0], self.rows[1], self.toPlainText())
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.finish(False)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.finish(True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if event.reason() != Qt.PopupFocusReason:
            self.finish(True)


class DiffView(QWidget):
    """The four painted widgets and the keys that move them.

    `command` carries the keys that belong to the tab rather than the view --
    swap, compare again, the rules switch -- so that they work whichever child
    has the keyboard.
    """

    currentChanged = Signal()
    command = Signal(str)
    #: (block index, side to copy to), from the gutter's arrows.
    copyBlock = Signal(int, int)
    #: 1.13: (first row, stop row, side to copy to), from the selection's arrows.
    copyRows = Signal(int, int, int)
    #: 1.13: a right-click on a pane, at this global position; the selection
    #: has already been moved to the row clicked if it was outside it.
    menuRequested = Signal(object)
    #: (side, first row, stop row, new text), from the line editor.
    edited = Signal(int, int, int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = ViewState()
        self.left = TextPane(self.state, 0)
        self.right = TextPane(self.state, 1)
        self.gutter = Gutter(self.state)
        self.map = DiffMap(self.state)
        self.hbar = QScrollBar(Qt.Horizontal)
        self.hbar.setFocusPolicy(Qt.NoFocus)
        self.hbar.valueChanged.connect(self._set_x)
        self.editor = LineEditor(self)
        self.editor.committed.connect(self._editor_done)
        self.editor.cancelled.connect(lambda: self.setFocus(Qt.OtherFocusReason))
        self._font = QFont()

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.left, 1)
        body.addWidget(self.gutter)
        body.addWidget(self.right, 1)
        body.addWidget(self.map)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(body, 1)
        outer.addWidget(self.hbar)

        for pane in (self.left, self.right, self.gutter):
            pane.wheeled.connect(self.scroll_by)
            pane.clicked.connect(self._clicked)
        for side, pane in enumerate((self.left, self.right)):
            pane.pressed.connect(lambda row, extend, sd=side: self._press(sd, row, extend))
            pane.dragged.connect(lambda row, sd=side: self._press(sd, row, True))
            pane.doubleClicked.connect(lambda row, sd=side: self._double(sd, row))
        self.gutter.copyRequested.connect(self.copyBlock)
        self.gutter.copyRowsRequested.connect(self.copyRows)
        for side, pane in enumerate((self.left, self.right)):
            pane.menuAt.connect(lambda row, point, sd=side: self._menu(sd, row, point))
        self.map.moved.connect(self._centre_on)
        self.map.wheeled.connect(self.scroll_by)
        self.setFocusPolicy(Qt.StrongFocus)

    # -------------------------------------------------------------- content

    @property
    def focused_side(self) -> int:
        return self.state.side

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        font = mono_font(tokens)
        self._font = font
        for widget in (self.left, self.right, self.gutter):
            widget.apply_tokens(tokens, font)
        self.map.apply_tokens(tokens)
        self._layout_changed()

    def set_comparison(self, comparison: align.Comparison, left: list[str],
                       right: list[str], mode: str,
                       pins: list[tuple[int, int]] | tuple = ()) -> None:
        keep = self.state.first if self.state.rows else 0
        keep_current = self.state.current if self.state.rows else None
        had = bool(self.state.rows)
        self.editor.finish(True) if not self.editor.isHidden() else None
        self.state.rows = comparison.rows
        self.state.blocks = comparison.blocks
        self.state.moved = comparison.moved_rows()
        self.state.comparison = comparison
        held = set(pins)
        self.state.pinned = ({r for r, (i, j, _k) in enumerate(comparison.rows) if (i, j) in held}
                             if held else set())
        self.state.pending = None
        self.state.lines = (left, right)
        self.state.mode = mode
        self.state.marks = {}
        self.state.current = None
        self.state.first = 0
        last = max(0, len(comparison.rows) - 1)
        self.state.cursor = min(self.state.cursor, last)
        self.state.anchor = min(self.state.anchor, last)
        self._layout_changed()
        self.scroll_to(min(keep, self._max_first()))
        if not had and comparison.differences:
            self.go(self._index_of_nth_difference(0))
        else:
            # After an edit: stay where the eye is. The difference that was
            # current is the one at the cursor now, if there still is one.
            at = comparison.block_at(self.state.cursor)
            self.state.current = at if at is not None else (
                keep_current if keep_current is not None
                and keep_current < len(comparison.blocks) else None)
            self._sync_current()
        self.update_all()

    def set_editable(self, left: bool, right: bool) -> None:
        self.state.editable = (left, right)
        self.gutter.update()

    def set_syntax(self, side: int, lines: list[str] | None, spans) -> None:
        """Colour for one side: the spans `core/syntax.highlight` made from
        exactly `lines`, or None to draw that side in plain ink."""
        self.state.syntax[side] = (lines, spans) if lines is not None and spans else None
        (self.left, self.right)[side].update()

    def set_find(self, pattern: re.Pattern | None) -> None:
        self.state.find = pattern
        self.update_all()

    def set_mode(self, mode: str) -> None:
        self.state.mode = mode
        self.state.marks = {}
        self.update_all()

    # --------------------------------------------------------------- moving

    def _max_first(self) -> int:
        return max(0, len(self.state.rows) - self.left.visible_rows() + 1)

    def scroll_to(self, first: int) -> None:
        first = max(0, min(first, self._max_first()))
        if first != self.state.first and not self.editor.isHidden():
            self.editor.finish(True)
        if first != self.state.first:
            self.state.first = first
            self.update_all()

    def scroll_by(self, rows: int) -> None:
        self.scroll_to(self.state.first + rows)

    def _centre_on(self, fraction: float) -> None:
        row = int(fraction * len(self.state.rows))
        self.scroll_to(row - self.left.visible_rows() // 2)

    def _set_x(self, value: int) -> None:
        self.state.x = int(value * self.left.char_w)
        self.update_all()

    def go(self, block_index: int | None) -> None:
        """Make `block_index` current and bring it into view."""
        if block_index is None or not self.state.blocks:
            return
        self.state.current = block_index
        block = self.state.blocks[block_index]
        self.state.cursor = self.state.anchor = block.start
        visible = self.left.visible_rows()
        if block.start < self.state.first or block.end > self.state.first + visible:
            self.scroll_to(block.start - int(visible * LANDING))
        self.update_all()
        self.currentChanged.emit()

    def go_to_partner(self) -> bool:
        """Ctrl+M: from one end of a move to the other. False when the
        current difference is not part of a move."""
        comparison = self.state.comparison
        if comparison is None or self.state.current is None:
            return False
        other = comparison.partner(self.state.current)
        if other is None:
            return False
        self.go(other)
        return True

    def _index_of_nth_difference(self, n: int) -> int | None:
        found = [i for i, b in enumerate(self.state.blocks) if b.significant]
        if not found:
            return None
        return found[n] if n >= 0 else found[n]

    def next_difference(self) -> None:
        anchor = self._anchor_row()
        for index, block in enumerate(self.state.blocks):
            if block.significant and block.start > anchor:
                self.go(index)
                return

    def previous_difference(self) -> None:
        anchor = self._anchor_row(previous=True)
        for index in range(len(self.state.blocks) - 1, -1, -1):
            block = self.state.blocks[index]
            if block.significant and block.start < anchor:
                self.go(index)
                return

    def first_difference(self) -> None:
        self.go(self._index_of_nth_difference(0))

    def last_difference(self) -> None:
        self.go(self._index_of_nth_difference(-1))

    def _anchor_row(self, previous: bool = False) -> int:
        """Where next/previous count from: the current difference if it is on
        screen, otherwise the top of the view -- so stepping after scrolling
        away continues from what is being looked at, not from where it was."""
        s = self.state
        if s.current is not None:
            block = s.blocks[s.current]
            if s.first <= block.start < s.first + self.left.visible_rows():
                return block.start
        return s.first if previous else s.first - 1

    def _clicked(self, row: int) -> None:
        index = None
        for i, block in enumerate(self.state.blocks):
            if block.start <= row < block.end:
                index = i
                break
        if index is not None and index != self.state.current:
            self.state.current = index
            self.update_all()
            self.currentChanged.emit()
        self.setFocus(Qt.MouseFocusReason)

    def _focus_side(self, side: int) -> None:
        if side != self.state.side:
            self.state.side = side
            self.update_all()
            self.currentChanged.emit()

    # ------------------------------------------------------------ selection

    def _press(self, side: int, row: int, extend: bool) -> None:
        if not self.state.rows:
            return
        row = max(0, min(row, len(self.state.rows) - 1))
        if side != self.state.side:
            self.state.side = side
            extend = False
            self.currentChanged.emit()
        self.state.cursor = row
        if not extend:
            self.state.anchor = row
        self.update_all()

    def _menu(self, side: int, row: int, point) -> None:
        """Right-click: on a row outside the selection, select that row first,
        as a list does; inside it, keep the selection to act on."""
        if not self.state.rows:
            return
        row = max(0, min(row, len(self.state.rows) - 1))
        lo, hi = self.state.selection()
        if side != self.state.side or not lo <= row < hi:
            self._press(side, row, False)
            self._clicked(row)
        self.setFocus(Qt.MouseFocusReason)
        self.menuRequested.emit(point)

    def _double(self, side: int, row: int) -> None:
        self._press(side, row, False)
        self.command.emit("edit")

    def move_cursor(self, rows: int, extend: bool) -> None:
        s = self.state
        if not s.rows:
            return
        s.cursor = max(0, min(len(s.rows) - 1, s.cursor + rows))
        if not extend:
            s.anchor = s.cursor
        self.reveal(s.cursor)
        at = align.Comparison(blocks=s.blocks).block_at(s.cursor)
        if at is not None and at != s.current:
            s.current = at
            self.currentChanged.emit()
        self.update_all()

    def select_rows(self, side: int, first: int, stop: int) -> None:
        self.state.side = side
        self.state.anchor = first
        self.state.cursor = max(first, stop - 1)
        self.reveal(first)
        self.update_all()
        self.currentChanged.emit()

    def reveal(self, row: int) -> None:
        visible = self.left.visible_rows()
        if row < self.state.first:
            self.scroll_to(row)
        elif row >= self.state.first + visible - 1:
            self.scroll_to(row - visible + 2)

    def selected_lines(self, side: int | None = None) -> tuple[int, list[int]]:
        """The focused side and the line numbers in the selection."""
        side = self.state.side if side is None else side
        lo, hi = self.state.selection()
        rows = self.state.rows[lo:hi]
        return side, [r[side] for r in rows if r[side] != align.NONE]

    def selected_text(self) -> str:
        side, lines = self.selected_lines()
        return "\n".join(self.state.lines[side][i] for i in lines)

    # -------------------------------------------------------------- editing

    def begin_edit(self) -> bool:
        """Open the line editor over the selection on the focused side."""
        s = self.state
        if not s.rows or not s.editable[s.side]:
            return False
        lo, hi = s.selection()
        side, lines = self.selected_lines()
        text = "\n".join(s.lines[side][i] for i in lines)
        pane = self.left if side == 0 else self.right
        numbers = pane.number_width()
        self.reveal(lo)
        top = pane.y() + (lo - s.first) * pane.row_h
        height = (max(1, hi - lo) + 1) * pane.row_h + 6
        height = min(height, pane.height() - max(0, top - pane.y()))
        self.editor.setGeometry(int(pane.x() + numbers), int(top),
                                int(pane.width() - numbers), int(max(height, pane.row_h * 2)))
        self.editor.begin(side, (lo, hi), text, self._font)
        return True

    def _editor_done(self, side: int, lo: int, hi: int, text: str) -> None:
        self.setFocus(Qt.OtherFocusReason)
        self.edited.emit(side, lo, hi, text)

    def _sync_current(self) -> None:
        if self.state.current is not None and self.state.current >= len(self.state.blocks):
            self.state.current = None
        self.currentChanged.emit()

    def position(self) -> tuple[int, int]:
        """(current difference number, how many), 1-based; 0 when none."""
        significant = [i for i, b in enumerate(self.state.blocks) if b.significant]
        if self.state.current in significant:
            return significant.index(self.state.current) + 1, len(significant)
        return 0, len(significant)

    # --------------------------------------------------------------- layout

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_changed()

    def _layout_changed(self) -> None:
        widest = max(self.left.longest(), self.right.longest()) if self.state.rows else 0
        columns = min(self.left.text_columns(), self.right.text_columns())
        self.hbar.setRange(0, max(0, widest - columns + 2))
        self.hbar.setPageStep(columns)
        self.hbar.setVisible(widest > columns)
        self.map.visible = self.left.visible_rows()
        self.scroll_to(self.state.first)
        self.update_all()

    def update_all(self) -> None:
        for widget in (self.left, self.right, self.gutter, self.map):
            widget.update()

    # ----------------------------------------------------------------- keys

    #: Keys that belong to the tab, not the view: (modifiers, key) -> command.
    COMMANDS = {
        (Qt.ControlModifier, Qt.Key_U): "swap",
        (Qt.ControlModifier, Qt.Key_R): "reload",
        (Qt.ControlModifier, Qt.Key_I): "rules",
        (Qt.AltModifier, Qt.Key_Right): "copy-right",
        (Qt.AltModifier, Qt.Key_Left): "copy-left",
        (Qt.ControlModifier | Qt.AltModifier, Qt.Key_Right): "copy-all-right",
        (Qt.ControlModifier | Qt.AltModifier, Qt.Key_Left): "copy-all-left",
        (Qt.ControlModifier, Qt.Key_Z): "undo",
        (Qt.ControlModifier, Qt.Key_Y): "redo",
        (Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_Z): "redo",
        (Qt.ControlModifier, Qt.Key_S): "save",
        (Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_S): "save-all",
        (Qt.ControlModifier, Qt.Key_F): "find",
        (Qt.ControlModifier, Qt.Key_G): "find-next",
        (Qt.NoModifier, Qt.Key_F3): "find-next",
        (Qt.ShiftModifier, Qt.Key_F3): "find-previous",
        (Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_G): "find-previous",
        (Qt.ControlModifier, Qt.Key_C): "copy-text",
        (Qt.ControlModifier, Qt.Key_Insert): "copy-text",
        (Qt.ControlModifier, Qt.Key_A): "select-all",
        (Qt.NoModifier, Qt.Key_Delete): "delete-lines",
        (Qt.NoModifier, Qt.Key_Return): "edit",
        (Qt.NoModifier, Qt.Key_Enter): "edit",
        (Qt.NoModifier, Qt.Key_F2): "edit",
        (Qt.ShiftModifier, Qt.Key_Return): "insert-line",
        (Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_H): "report",
        (Qt.ControlModifier, Qt.Key_M): "move-partner",
        (Qt.ControlModifier, Qt.Key_L): "align",
        (Qt.ControlModifier | Qt.AltModifier, Qt.Key_S): "save-session",
        (Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_L): "unalign",
    }

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        shift = bool(mods & Qt.ShiftModifier)
        plain = mods & ~Qt.ShiftModifier
        page = max(1, self.left.visible_rows() - 1)
        command = self.COMMANDS.get((mods, key))
        if command is not None:
            self.command.emit(command)
        elif mods == Qt.AltModifier and key == Qt.Key_Down:
            self.next_difference()
        elif mods == Qt.AltModifier and key == Qt.Key_Up:
            self.previous_difference()
        elif mods == Qt.NoModifier and key == Qt.Key_Home:
            self.first_difference()
        elif mods == Qt.NoModifier and key == Qt.Key_End:
            self.last_difference()
        elif plain == Qt.ControlModifier and key == Qt.Key_Home:
            self.move_cursor(-len(self.state.rows), shift)
        elif plain == Qt.ControlModifier and key == Qt.Key_End:
            self.move_cursor(len(self.state.rows), shift)
        elif plain == Qt.NoModifier and key == Qt.Key_Down:
            self.move_cursor(1, shift)
        elif plain == Qt.NoModifier and key == Qt.Key_Up:
            self.move_cursor(-1, shift)
        elif plain == Qt.ControlModifier and key == Qt.Key_Down:
            self.scroll_by(1)
        elif plain == Qt.ControlModifier and key == Qt.Key_Up:
            self.scroll_by(-1)
        elif plain == Qt.NoModifier and key == Qt.Key_PageDown:
            self.scroll_by(page)
            self.move_cursor(page, shift)
        elif plain == Qt.NoModifier and key == Qt.Key_PageUp:
            self.scroll_by(-page)
            self.move_cursor(-page, shift)
        elif mods == Qt.NoModifier and key == Qt.Key_Right:
            self.hbar.setValue(self.hbar.value() + 4)
        elif mods == Qt.NoModifier and key == Qt.Key_Left:
            self.hbar.setValue(self.hbar.value() - 4)
        elif mods == Qt.NoModifier and key == Qt.Key_Tab:
            self._focus_side(1 - self.state.side)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def focusNextPrevChild(self, forward: bool) -> bool:  # noqa: N802
        # Tab is "the other side" here, as it is "the other pane" in File
        # Manager; without this Qt takes it to move focus out of the view.
        return False
