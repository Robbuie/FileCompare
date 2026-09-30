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
