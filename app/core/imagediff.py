"""Image compare: decode two images and find the pixels that differ.

Qt's own image code does the work, so this needs nothing the application does
not already ship: `QImage` decodes every format its plugins read (PNG, JPEG,
BMP, GIF, TIFF, WebP, ICO, SVG...), and the difference is drawn with
`QPainter`'s Difference composition, which is native code, not a Python loop
over pixels. The threshold is `bytes.translate` over the grey difference,
which is native too. A 24-megapixel pair takes a fraction of a second.

`QImage` and `QPainter` on a `QImage` are safe off the UI thread (only
widgets and pixmaps are not), so all of it runs in the loader.

Images of different sizes are compared over the area they share, anchored
top left, and the size difference is reported: the extra area is neither
"the same" nor pixel by pixel "different", it is simply not in the other one.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRect
from PySide6.QtGui import QColor, QImage, QPainter

EXTENSIONS = frozenset({"png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp", "ico",
                        "tga", "ppm", "pgm", "pbm", "xbm", "xpm", "svg", "jfif", "icns"})

#: Default tolerance: a pixel differs when its grey difference is above this
#: (0-255). Low enough that a real edit shows, high enough that re-encoding a
#: JPEG does not light up the whole picture.
TOLERANCE = 16


def is_image(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return "." in name and name.rsplit(".", 1)[-1].lower() in EXTENSIONS


@dataclass
class ImageResult:
    left: QImage
    right: QImage
    #: The differing pixels as an 8-bit alpha mask over the shared area.
    mask: QImage | None
    differing: int
    shared: int
    tolerance: int
    #: Box around every differing pixel, or None.
    bounds: tuple[int, int, int, int] | None = None
    problem: str = ""

    @property
    def same_size(self) -> bool:
        return self.left.size() == self.right.size()

    @property
    def identical(self) -> bool:
        return self.same_size and self.differing == 0 and not self.problem


def decode(data: bytes | None) -> QImage:
    image = QImage()
    if data:
        image.loadFromData(QByteArray(data))
    return image


def compare(left_data: bytes | None, right_data: bytes | None,
            tolerance: int = TOLERANCE) -> ImageResult:
    left, right = decode(left_data), decode(right_data)
    if left.isNull() or right.isNull():
        which = " and ".join(n for n, i in (("left", left), ("right", right)) if i.isNull())
        return ImageResult(left, right, None, 0, 0, tolerance,
                           problem=f"The {which} image could not be decoded")
    return measure(left, right, tolerance)


def measure(left: QImage, right: QImage, tolerance: int = TOLERANCE) -> ImageResult:
    width = min(left.width(), right.width())
    height = min(left.height(), right.height())
    a = left.convertToFormat(QImage.Format_ARGB32).copy(QRect(0, 0, width, height))
    b = right.convertToFormat(QImage.Format_ARGB32).copy(QRect(0, 0, width, height))
    # Transparent pixels composite differently from opaque ones; comparing
    # over an opaque ground makes "the same picture" mean the same thing.
    ground = QImage(width, height, QImage.Format_ARGB32)
    ground.fill(QColor(0, 0, 0))
    for image in (a, b):
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationOver)
        painter.drawImage(0, 0, ground)
        painter.end()
    painter = QPainter(a)
    painter.setCompositionMode(QPainter.CompositionMode_Difference)
    painter.drawImage(0, 0, b)
    painter.end()
    grey = a.convertToFormat(QImage.Format_Grayscale8)
    table = bytes(255 if value > tolerance else 0 for value in range(256))
    stride = grey.bytesPerLine()
    raw = bytes(grey.constBits())[: stride * height]
    marked = raw.translate(table)
    mask = QImage(marked, width, height, stride, QImage.Format_Alpha8).copy()
    differing = 0
    top = bottom = left_edge = right_edge = None
    for y in range(height):
        row = marked[y * stride: y * stride + width]
        count = row.count(255)
        if not count:
            continue
        differing += count
        first = row.find(255)
        last = row.rfind(255)
        top = y if top is None else top
        bottom = y
        left_edge = first if left_edge is None else min(left_edge, first)
        right_edge = last if right_edge is None else max(right_edge, last)
    bounds = None if top is None else (left_edge, top, right_edge - left_edge + 1,
                                       bottom - top + 1)
    return ImageResult(left, right, mask, differing, width * height, tolerance, bounds)
