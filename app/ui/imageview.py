"""The image compare view: side by side, overlay, swipe, blink and difference.

The same five ways of looking as Redline PDF's compare panel, under the same
chip control, so the two read as one tool:

  * **Side by side** -- both images, one zoom and one pan between them, with
    the differing pixels outlined when "Mark differences" is on;
  * **Overlay** -- the right image over the left, its opacity on the slider;
  * **Swipe** -- the left image left of the slider's line, the right image
    right of it; drag the slider across a change;
  * **Blink** -- the two alternating, which is how the eye finds a small move;
  * **Difference** -- the left image dimmed, with every pixel that differs by
    more than the tolerance painted in the deletion red.

Fit to the window by default. Ctrl+wheel, + and - zoom; 0 fits and 1 is
actual size; dragging pans. Nothing here reads a file or decodes an image:
both arrive decoded from `core/imagediff.py`, off the UI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import imagediff
from app.ui.diffview import parse_colour

SIDE, OVERLAY, SWIPE, BLINK, DIFFERENCE = "side", "overlay", "swipe", "blink", "difference"
MODES = ((SIDE, "Side by side"), (OVERLAY, "Overlay"), (SWIPE, "Swipe"), (BLINK, "Blink"),
         (DIFFERENCE, "Difference"))

BLINK_MS = 650


class Canvas(QWidget):
    """One drawing surface. Which image, and how, is the view's decision."""

    def __init__(self, view: "ImageView", side: int) -> None:
        super().__init__(view)
        self.view = view
        self.side = side
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMouseTracking(False)
        self._drag: QPointF | None = None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), parse_colour(self.view.tokens.get("bg_1")))
        self.view.paint(painter, self)
        painter.end()

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.view.zoom_by(1.25 ** steps, event.position(), self)
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            delta = event.position() - self._drag
            self._drag = event.position()
            self.view.pan_by(delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None
        self.unsetCursor()


class ImageView(QWidget):
    """Emits `toleranceChanged` when the tolerance should be measured again."""

    toleranceChanged = Signal(int)
    command = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tokens: dict[str, str] = {}
        self.result: imagediff.ImageResult | None = None
        self.mode = SIDE
        self.scale: float | None = None       # None: fit
        self.center = QPointF(0, 0)           # image point at the canvas centre
        self.phase = 0
        self._coloured: QImage | None = None
        self.left_canvas = Canvas(self, 0)
        self.right_canvas = Canvas(self, 1)

        self.chips: dict[str, QPushButton] = {}
        segments = QWidget()
        segments.setProperty("role", "segments")
        segments.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(segments)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(2)
        for mode, label in MODES:
            chip = QPushButton(label)
            chip.setProperty("role", "segment")
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.NoFocus)
            chip.clicked.connect(lambda _c=False, m=mode: self.set_mode(m))
            seg.addWidget(chip)
            self.chips[mode] = chip
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.slider.setFixedWidth(160)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.valueChanged.connect(lambda _v: self.update_canvases())
        self.marks = QPushButton("Mark differences")
        self.marks.setProperty("role", "segment")
        self.marks.setCheckable(True)
        self.marks.setChecked(True)
        self.marks.setFocusPolicy(Qt.NoFocus)
        self.marks.toggled.connect(lambda _c: self.update_canvases())
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 254)
        self.tolerance.setValue(imagediff.TOLERANCE)
        self.tolerance.setPrefix("Tolerance ")
        self.tolerance.setToolTip("How far apart two pixels' grey levels may be and still "
                                  "count as the same (0-254)")
        self._tolerance_timer = QTimer(self)
        self._tolerance_timer.setSingleShot(True)
        self._tolerance_timer.setInterval(350)
        self._tolerance_timer.timeout.connect(
            lambda: self.toleranceChanged.emit(self.tolerance.value()))
        self.tolerance.valueChanged.connect(lambda _v: self._tolerance_timer.start())
        fit = QPushButton("Fit")
        fit.setProperty("role", "segment")
        fit.setFocusPolicy(Qt.NoFocus)
        fit.clicked.connect(lambda _c=False: self.fit())
        actual = QPushButton("1:1")
        actual.setProperty("role", "segment")
        actual.setFocusPolicy(Qt.NoFocus)
        actual.clicked.connect(lambda _c=False: self.actual())
        self.info = QLabel()
        self.info.setProperty("role", "count")

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(6)
        bar.addWidget(segments)
        bar.addWidget(self.slider)
        bar.addWidget(self.marks)
        bar.addWidget(self.tolerance)
        bar.addStretch(1)
        bar.addWidget(fit)
        bar.addWidget(actual)
        top = QWidget()
        top.setProperty("role", "folderbar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setLayout(bar)
        canvases = QHBoxLayout()
        canvases.setContentsMargins(0, 0, 0, 0)
        canvases.setSpacing(2)
        canvases.addWidget(self.left_canvas, 1)
        canvases.addWidget(self.right_canvas, 1)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(top)
        box.addWidget(self.info)
        box.addLayout(canvases, 1)

        self._blink = QTimer(self)
        self._blink.setInterval(BLINK_MS)
        self._blink.timeout.connect(self._blinked)
        self.setFocusPolicy(Qt.StrongFocus)
        self.set_mode(SIDE)

    # ------------------------------------------------------------ content

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self._coloured = None
        self.update_canvases()

    def set_result(self, result: imagediff.ImageResult) -> None:
        first = self.result is None
        self.result = result
        self._coloured = None
        if first:
            self.scale = None
            self.center = QPointF(result.left.width() / 2, result.left.height() / 2)
        self.info.setText(self.describe())
        self.update_canvases()

    def describe(self) -> str:
        r = self.result
        if r is None:
            return ""
        if r.problem:
            return r.problem
        sizes = f"{r.left.width()}x{r.left.height()}"
        if not r.same_size:
            sizes += f" vs {r.right.width()}x{r.right.height()} (compared where they overlap)"
        if r.differing == 0:
            return f"No pixels differ  ·  {sizes}" if r.same_size else sizes
        share = r.differing / max(1, r.shared) * 100
        box = r.bounds
        where = f"  ·  within {box[2]}x{box[3]} at {box[0]},{box[1]}" if box else ""
        return f"{r.differing:,} pixels differ ({share:.2f}%){where}  ·  {sizes}"

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        for value, chip in self.chips.items():
            chip.setChecked(value == mode)
        self.right_canvas.setVisible(mode == SIDE)
        self.slider.setVisible(mode in (OVERLAY, SWIPE))
        self.slider.setToolTip("Opacity of the right image" if mode == OVERLAY
                               else "Where the right image starts")
        if mode == BLINK:
            self._blink.start()
        else:
            self._blink.stop()
        self.update_canvases()

    # -------------------------------------------------------------- moving

    def _scale_for(self, canvas: Canvas) -> float:
        if self.scale is not None:
            return self.scale
        r = self.result
        if r is None:
            return 1.0
        w = max(r.left.width(), r.right.width())
        h = max(r.left.height(), r.right.height())
        if not w or not h:
            return 1.0
        return min(1.0 * max(1, canvas.width() - 16) / w,
                   1.0 * max(1, canvas.height() - 16) / h, 8.0)

    def fit(self) -> None:
        self.scale = None
        if self.result is not None:
            self.center = QPointF(self.result.left.width() / 2, self.result.left.height() / 2)
        self.update_canvases()

    def actual(self) -> None:
        self.scale = 1.0
        self.update_canvases()

    def zoom_by(self, factor: float, at: QPointF | None = None,
                canvas: Canvas | None = None) -> None:
        canvas = canvas or self.left_canvas
        old = self._scale_for(canvas)
        new = max(0.02, min(64.0, old * factor))
        if at is not None:
            # Keep the image point under the cursor where it is.
            mid = QPointF(canvas.width() / 2, canvas.height() / 2)
            point = self.center + (at - mid) / old
            self.center = point - (at - mid) / new
        self.scale = new
        self.update_canvases()

    def pan_by(self, delta: QPointF) -> None:
        self.center -= delta / self._scale_for(self.left_canvas)
        self.update_canvases()

    def _blinked(self) -> None:
        self.phase = 1 - self.phase
        self.left_canvas.update()

    def update_canvases(self) -> None:
        self.left_canvas.update()
        self.right_canvas.update()

    # ------------------------------------------------------------ painting

    def _target(self, canvas: Canvas, image: QImage) -> QRectF:
        scale = self._scale_for(canvas)
        mid = QPointF(canvas.width() / 2, canvas.height() / 2)
        origin = mid - self.center * scale
        return QRectF(origin.x(), origin.y(), image.width() * scale, image.height() * scale)

    def _mask(self) -> QImage | None:
        r = self.result
        if r is None or r.mask is None:
            return None
        if self._coloured is None:
            coloured = QImage(r.mask.size(), QImage.Format_ARGB32_Premultiplied)
            coloured.fill(parse_colour(self.tokens.get("diff_del_bar")))
            painter = QPainter(coloured)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawImage(0, 0, r.mask)
            painter.end()
            self._coloured = coloured
        return self._coloured

    def paint(self, painter: QPainter, canvas: Canvas) -> None:
        r = self.result
        if r is None or r.left.isNull() or r.right.isNull():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._scale_for(canvas) < 1)
        left, right = r.left, r.right
        mode = self.mode
        if mode == SIDE:
            image = left if canvas.side == 0 else right
            painter.drawImage(self._target(canvas, image), image)
            if self.marks.isChecked():
                self._draw_mask(painter, canvas, 0.55)
        elif mode == OVERLAY:
            painter.drawImage(self._target(canvas, left), left)
            painter.setOpacity(self.slider.value() / 100)
            painter.drawImage(self._target(canvas, right), right)
            painter.setOpacity(1.0)
        elif mode == SWIPE:
            painter.drawImage(self._target(canvas, left), left)
            x = canvas.width() * self.slider.value() / 100
            painter.save()
            painter.setClipRect(QRectF(x, 0, canvas.width() - x, canvas.height()))
            painter.drawImage(self._target(canvas, right), right)
            painter.restore()
            painter.setPen(QPen(parse_colour(self.tokens.get("accent")), 2))
            painter.drawLine(int(x), 0, int(x), canvas.height())
        elif mode == BLINK:
            image = left if self.phase == 0 else right
            painter.drawImage(self._target(canvas, image), image)
            painter.setPen(parse_colour(self.tokens.get("txt_0")))
            painter.drawText(QRectF(10, 8, 200, 20), Qt.AlignLeft | Qt.AlignTop,
                             "Left" if self.phase == 0 else "Right")
        elif mode == DIFFERENCE:
            painter.drawImage(self._target(canvas, left), left)
            dim = QColor(parse_colour(self.tokens.get("bg_0")))
            dim.setAlphaF(0.72)
            painter.fillRect(self._target(canvas, left), dim)
            self._draw_mask(painter, canvas, 1.0)
        if r.bounds and mode != BLINK and (mode != SIDE or self.marks.isChecked()):
            x, y, w, h = r.bounds
            box = self._target(canvas, left)
            scale = self._scale_for(canvas)
            painter.setPen(QPen(parse_colour(self.tokens.get("accent")), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(box.x() + x * scale - 3, box.y() + y * scale - 3,
                                    w * scale + 6, h * scale + 6))

    def _draw_mask(self, painter: QPainter, canvas: Canvas, opacity: float) -> None:
        mask = self._mask()
        if mask is None:
            return
        painter.setOpacity(opacity)
        painter.drawImage(self._target(canvas, mask), mask)
        painter.setOpacity(1.0)

    # ---------------------------------------------------------------- keys

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif key == Qt.Key_Minus:
            self.zoom_by(0.8)
        elif key == Qt.Key_0:
            self.fit()
        elif key == Qt.Key_1:
            self.actual()
        elif key == Qt.Key_B and mods == Qt.NoModifier:
            self.set_mode(BLINK if self.mode != BLINK else SIDE)
        elif mods == Qt.ControlModifier and key == Qt.Key_U:
            self.command.emit("swap")
        elif mods == Qt.ControlModifier and key == Qt.Key_R:
            self.command.emit("reload")
        else:
            super().keyPressEvent(event)
            return
        event.accept()
