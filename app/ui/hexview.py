"""The hex view: both files as rows of sixteen bytes, aligned by offset.

Painted like the text view, for the same reasons -- only the rows on screen,
both panes on one scroll position, the overview map down the right. Each row
is the offset, the bytes in hex with a gap after the eighth, and the same
bytes as characters. A byte that differs is marked amber on both sides; a
byte that exists on one side only (the file is longer) is marked red on the
left or green on the right, as in the text view.

Nothing here reads a file: the bytes arrive with the side (`Loaded.data`) and
the comparison is `core/hexdiff.py`'s.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core import hexdiff
from app.core.diff import align
from app.ui.diffview import WHEEL_ROWS, DiffMap, ViewState, mono_font, parse_colour


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: int = align.CHANGED
    significant: bool = True


class HexPane(QWidget):
    wheeled = Signal(int)

    def __init__(self, owner: "HexView", side: int) -> None:
        super().__init__(owner)
        self.owner = owner
        self.side = side
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMinimumWidth(200)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.wheeled.emit(int(-steps * WHEEL_ROWS) or (-1 if steps > 0 else 1))
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        o = self.owner
        tokens = o.tokens
        colour = lambda name: parse_colour(tokens.get(name))  # noqa: E731
        painter = QPainter(self)
        painter.fillRect(self.rect(), colour("bg_2"))
        painter.setFont(o.font_)
        mine = o.data[self.side]
        other = o.data[1 - self.side]
        cw, rh = o.char_w, o.row_h
        offset_w = cw * 10
        painter.fillRect(QRectF(0, 0, offset_w, self.height()), colour("bg_1"))
        hex_x = offset_w + cw
        text_x = hex_x + cw * (3 * hexdiff.WIDTH + 1) + cw * 2
        only = colour("diff_del_mark" if self.side == 0 else "diff_add_mark")
        changed = colour("diff_chg_mark")
        wash = colour("diff_chg_row")
        filler = colour("diff_filler")
        ink, dim = colour("txt_0"), colour("txt_2")
        diff_rows = o.diff_rows
        for n in range(o.visible_rows() + 1):
            row = o.first + n
            if row >= o.total_rows:
                break
            y = n * rh
            base = row * hexdiff.WIDTH
            if base >= len(mine):
                painter.fillRect(QRectF(offset_w, y, self.width() - offset_w, rh), filler)
                continue
            differs = row in diff_rows
            if differs:
                painter.fillRect(QRectF(offset_w, y, self.width() - offset_w, rh), wash)
            painter.setPen(dim)
            painter.drawText(QRectF(0, y, offset_w - cw * 0.5, rh),
                             Qt.AlignRight | Qt.AlignVCenter, f"{base:08X}")
            chunk = mine[base:base + hexdiff.WIDTH]
            marks = hexdiff.differing(mine, other, row) if differs else None
            for column, value in enumerate(chunk):
                gap = cw if column >= 8 else 0
                x = hex_x + column * 3 * cw + gap
                ax = text_x + column * cw
                if marks is not None and marks[column]:
                    fill = only if base + column >= len(other) else changed
                    painter.fillRect(QRectF(x - cw * 0.25, y + 1, cw * 2.5, rh - 2), fill)
                    painter.fillRect(QRectF(ax, y + 1, cw, rh - 2), fill)
                painter.setPen(ink if value else dim)
                painter.drawText(QRectF(x, y, cw * 2, rh), Qt.AlignLeft | Qt.AlignVCenter,
                                 f"{value:02X}")
                painter.setPen(ink if 32 <= value < 127 else dim)
                painter.drawText(QRectF(ax, y, cw, rh), Qt.AlignLeft | Qt.AlignVCenter,
                                 chr(value) if 32 <= value < 127 else ".")
        if o.current is not None and o.current < len(o.blocks):
            start, stop = o.blocks[o.current]
            top, bottom = (start - o.first) * rh, (stop - o.first) * rh
            painter.setPen(QPen(colour("accent_line"), 1))
            painter.drawLine(0, int(top), self.width(), int(top))
            painter.drawLine(0, int(bottom) - 1, self.width(), int(bottom) - 1)
        painter.setPen(QPen(colour("line_soft"), 1))
        painter.drawLine(int(offset_w), 0, int(offset_w), self.height())
        painter.drawLine(int(text_x - cw), 0, int(text_x - cw), self.height())
        painter.end()


class HexView(QWidget):
    """Emits `currentChanged` when the difference in view moves on."""

    currentChanged = Signal()
    command = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tokens: dict[str, str] = {}
        self.font_ = mono_font({})
        self.char_w, self.row_h = 8.0, 20
        self.data: tuple[bytes, bytes] = (b"", b"")
        self.result: hexdiff.HexResult | None = None
        self.diff_rows: set[int] = set()
        self.blocks: list[tuple[int, int]] = []
        self.first = 0
        self.total_rows = 0
        self.current: int | None = None
        self.left = HexPane(self, 0)
        self.right = HexPane(self, 1)
        self._map_state = ViewState()
        self.map = DiffMap(self._map_state)
        self.map.moved.connect(lambda f: self.scroll_to(int(f * self.total_rows)
                                                        - self.visible_rows() // 2))
        for pane in (self.left, self.right, self.map):
            pane.wheeled.connect(lambda n: self.scroll_to(self.first + n))
        self.note = QLabel()
        self.note.setProperty("role", "count")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(self.left, 1)
        row.addWidget(self.right, 1)
        row.addWidget(self.map)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addLayout(row, 1)
        self.setFocusPolicy(Qt.StrongFocus)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.font_ = mono_font(tokens)
        metrics = QFontMetricsF(self.font_)
        self.char_w = metrics.horizontalAdvance("0")
        self.row_h = int(metrics.height() + 4)
        width = int(self.char_w * (10 + 1 + 3 * hexdiff.WIDTH + 1 + 2 + hexdiff.WIDTH + 2))
        self.left.setMinimumWidth(width)
        self.right.setMinimumWidth(width)
        self.map.apply_tokens(tokens)
        self.update_all()

    def set_data(self, left: bytes, right: bytes, result: hexdiff.HexResult) -> None:
        self.data = (left, right)
        self.result = result
        self.diff_rows = set(result.rows)
        self.blocks = result.blocks
        self.total_rows = result.total_rows
        self._map_state.rows = range(self.total_rows)  # type: ignore[assignment]
        self._map_state.blocks = [_Block(a, b) for a, b in self.blocks]
        self.current = None
        self.first = 0
        if self.blocks:
            self.go(0)
        self.update_all()

    def visible_rows(self) -> int:
        return max(1, self.left.height() // max(1, self.row_h))

    def scroll_to(self, first: int) -> None:
        first = max(0, min(first, max(0, self.total_rows - self.visible_rows() + 1)))
        if first != self.first:
            self.first = first
            self.update_all()

    def go(self, index: int | None) -> None:
        if index is None or not self.blocks:
            return
        index = max(0, min(index, len(self.blocks) - 1))
        self.current = index
        start, stop = self.blocks[index]
        visible = self.visible_rows()
        if start < self.first or stop > self.first + visible:
            self.scroll_to(start - visible // 3)
        self.update_all()
        self.currentChanged.emit()

    def step(self, direction: int) -> None:
        if not self.blocks:
            return
        if self.current is None:
            self.go(0 if direction > 0 else len(self.blocks) - 1)
        else:
            self.go(self.current + direction)

    def position(self) -> tuple[int, int]:
        return ((self.current + 1) if self.current is not None else 0), len(self.blocks)

    def update_all(self) -> None:
        self._map_state.first = self.first
        self.map.visible = self.visible_rows()
        for widget in (self.left, self.right, self.map):
            widget.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update_all()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        page = max(1, self.visible_rows() - 1)
        if mods == Qt.AltModifier and key == Qt.Key_Down:
            self.step(1)
        elif mods == Qt.AltModifier and key == Qt.Key_Up:
            self.step(-1)
        elif mods == Qt.NoModifier and key == Qt.Key_Home:
            self.go(0)
        elif mods == Qt.NoModifier and key == Qt.Key_End:
            self.go(len(self.blocks) - 1)
        elif mods == Qt.ControlModifier and key == Qt.Key_Home:
            self.scroll_to(0)
        elif mods == Qt.ControlModifier and key == Qt.Key_End:
            self.scroll_to(self.total_rows)
        elif key == Qt.Key_Down:
            self.scroll_to(self.first + 1)
        elif key == Qt.Key_Up:
            self.scroll_to(self.first - 1)
        elif key == Qt.Key_PageDown:
            self.scroll_to(self.first + page)
        elif key == Qt.Key_PageUp:
            self.scroll_to(self.first - page)
        elif mods == Qt.ControlModifier and key == Qt.Key_U:
            self.command.emit("swap")
        elif mods == Qt.ControlModifier and key == Qt.Key_R:
            self.command.emit("reload")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

