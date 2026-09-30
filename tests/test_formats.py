"""Format-aware compare: the canonical text each comparer writes, and the
Logix fixture pair whose four real changes must be the only differences."""

import os
import time

from app.core import formats, siblings
from app.core.diff import align
from app.core.formats import inifmt, jsonfmt, l5x, xmlfmt

L5X = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "l5x")


def read(name):
    with open(os.path.join(L5X, name), encoding="utf-8") as handle:
        return handle.read()


def test_detects_by_extension_on_both_sides():
    assert formats.detect("a.L5X", "b.l5x") == "l5x"
    assert formats.detect("a.xml", "b.config") == "xml"
    assert formats.detect("a.json", "b.txt") == formats.PLAIN
    assert formats.detect("a.txt", "b.txt") == formats.PLAIN


def test_the_logix_pair_differs_only_where_the_logic_does():
    a, b = l5x.normalise(read("left.L5X")), l5x.normalise(read("right.L5X"))
    result = align.compare(a.lines, b.lines)
    crumbs = []
    for block in result.differences:
        row = result.rows[block.start]
        crumbs.append(b.crumbs[row[1]] if row[1] != align.NONE else a.crumbs[row[0]])
    # Export date, edit date and tag order all changed too, and are not here.
    assert crumbs == [
        "Module IO_Rack1",
        "Controller tags / Speed",
        "Program MainProgram / MainRoutine / Rung 1",
        "Program MainProgram / MainRoutine / Rung 3",
    ]


def test_an_inserted_rung_is_one_difference_not_a_renumbering():
    a, b = l5x.normalise(read("left.L5X")), l5x.normalise(read("right.L5X"))
    assert not any("Rung 1" in line or "Rung 2" in line for line in a.lines)
    inserted = [line for line in b.lines if "GuardOpen" in line]
    assert inserted == ["    Rung: XIO(GuardOpen)OTE(Permissive);"]


def test_not_an_export_is_compared_as_text():
    out = formats.normalise("l5x", ["<Other/>"])
    assert out.problem and out.lines == ["<Other/>"]


def test_xml_ignores_attribute_order_and_layout():
    a = xmlfmt.normalise('<a x="1" y="2"><b>t</b></a>')
    b = xmlfmt.normalise('<?xml version="1.0" encoding="utf-8"?>\n<a y="2"   x="1">\n'
                         '  <b>\n    t\n  </b>\n</a>')
    assert a.lines == b.lines == ['<a x="1" y="2">', "  <b>t"]


def test_json_ignores_key_order():
    a = jsonfmt.normalise('{"b": 1, "a": {"y": [1, 2], "x": null}}')
    b = jsonfmt.normalise('{"a": {"x": null, "y": [1, 2]}, "b": 1}')
    assert a.lines == b.lines
    assert "a.y[1]" in a.crumbs


def test_ini_sorts_sections_and_keys_and_drops_comments():
    a = inifmt.normalise(["[B]", "z=1", "a = 2", "; note", "[A]", "k=v"])
    b = inifmt.normalise(["[A]", "k = v", "[b]", "A=2", "z=1"])
    assert [l.lower() for l in a.lines] == [l.lower() for l in b.lines]


def test_siblings_by_extension():
    assert siblings.for_pair("a.pdf", "B.PDF") is siblings.REDLINE
    assert siblings.for_pair("a.dwg", "b.dxf") is siblings.DWG_VIEWER
    assert siblings.for_pair("a.pdf", "b.txt") is None


def test_the_session_compares_an_export_by_structure_and_not_as_text(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app.core import session as core
    from app.core.loader import Loader
    from app.core.session import Options, Session

    loader = Loader()
    s = Session(loader, os.path.join(L5X, "left.L5X"), os.path.join(L5X, "right.L5X"),
                options=Options(poll=False))
    s.start()
    end = time.monotonic() + 10
    while s.kind != core.TEXT and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert s.structure and len(s.result.differences) == 4
    assert not s.sides[0].editable and "structure" in s.sides[0].why_not_editable
    s.set_structure(False)
    assert len(s.result.differences) > 4 and s.sides[0].editable


# ------------------------------------------------------------- hex and image

def test_hex_rows_and_blocks():
    from app.core import hexdiff

    a = bytes(range(64))
    b = bytearray(a)
    b[17] = 0xFF
    b[18] = 0xFE
    result = hexdiff.compare(a, bytes(b) + b"\x00" * 20)
    assert result.rows == [1, 4, 5]
    assert result.blocks == [(1, 2), (4, 6)]
    assert result.changed == 2
    assert hexdiff.differing(a, bytes(b), 1)[1:3] == [True, True]
    assert hexdiff.compare(a, a).identical


def test_image_difference_counts_pixels_and_bounds(qt_app):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter

    from app.core import imagediff

    def png(image):
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    a = QImage(50, 30, QImage.Format_RGB32)
    a.fill(QColor(200, 200, 200))
    b = a.copy()
    painter = QPainter(b)
    painter.fillRect(5, 6, 4, 3, QColor(0, 0, 0))
    painter.end()
    result = imagediff.compare(png(a), png(b))
    assert result.differing == 12 and result.bounds == (5, 6, 4, 3)
    assert imagediff.compare(png(a), png(a)).identical
    assert imagediff.compare(b"not an image", png(a)).problem


def test_binary_pairs_open_in_hex_and_images_as_images(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QColor, QImage

    from app import cli
    from app.core.config import Config
    from app.ui.window import MainWindow

    (tmp_path / "a.bin").write_bytes(b"\x00\x00\x01\xff" * 50)
    (tmp_path / "b.bin").write_bytes(b"\x00\x00\x02\xff" * 50)
    for name, colour in (("a.png", 10), ("b.png", 250)):
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor(colour, colour, colour))
        image.save(str(tmp_path / name))
    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    window.open_request(cli.parse([str(tmp_path / "a.bin"), str(tmp_path / "b.bin")]))
    hex_tab = window.pages.currentWidget()
    window.open_request(cli.parse([str(tmp_path / "a.png"), str(tmp_path / "b.png")]))
    image_tab = window.pages.currentWidget()
    end = time.monotonic() + 10
    while time.monotonic() < end and (hex_tab.hex.result is None
                                      or image_tab.images.result is None):
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert hex_tab.stack.currentWidget() is hex_tab.hex
    assert len(hex_tab.hex.result.rows) == 13
    assert image_tab.stack.currentWidget() is image_tab.images
    assert image_tab.images.result.differing == 64
    image_tab.set_mode("hex")
    assert image_tab.stack.currentWidget() is image_tab.hex
    window._may_close = lambda pages: True
    window.close()
