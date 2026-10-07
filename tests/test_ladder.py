"""1.16: rungs from neutral text -- parsed, laid out, compared -- and the
rung view over a real Logix comparison."""

import os
import time

from app.core import formats
from app.core import ladder as L
from app.core.diff import align
from app.core.rules import Rules

DATA = os.path.join(os.path.dirname(__file__), "data")


def _names(series):
    return [i.name for i in L.instructions(series)]


def test_a_rung_parses_into_series_and_branches():
    rung = L.parse("Rung: XIC(Start)[XIO(Stop),XIC(Jog)[XIC(A),]]CMP(A[1]+B>C)"
                   "TON(T,?,?)OTE(Motor);")
    assert _names(rung) == ["XIC", "XIO", "XIC", "XIC", "CMP", "TON", "OTE"]
    branch = rung.items[1]
    assert isinstance(branch, L.Branch) and len(branch.legs) == 2
    inner = branch.legs[1].items[1]
    assert isinstance(inner, L.Branch) and inner.legs[1].items == []   # an empty leg
    cmp = L.instructions(rung)[4]
    assert cmp.operands == ("A[1]+B>C",)        # an index is not a branch
    assert L.instructions(rung)[5].operands == ("T", "?", "?")
    assert L.parse("Rung (D): NOP();").items[0].name == "NOP"
    assert L.parse("Rung: ;").items == []


def test_text_that_is_not_an_instruction_is_kept_not_dropped():
    rung = L.parse("XIC(A) garbage OTE(B)")
    keys = [i.key for i in L.instructions(rung)]
    assert keys[0] == "XIC(A)" and keys[-1] == "OTE(B)"
    assert any("garbage" in k for k in keys)


def test_layout_places_branches_and_wraps_the_top_level():
    rung = L.parse("XIC(A)[XIO(B),XIC(C)XIC(D)]MOV(Speed,Dest)OTE(E);")
    lay = L.layout(rung)
    by = {p.instr.operands[0]: p for p in lay.placed}
    assert by["A"].x == 0 and by["A"].y == 0
    assert by["B"].y == 0 and by["C"].y == 1 and by["D"].x > by["C"].x
    assert len(lay.rails) == 2
    assert by["Speed"].w == L.BOX_WIDTH
    assert lay.lines == [0]
    narrow = L.layout(rung, max_width=4)
    assert len(narrow.lines) > 1                 # wrapped
    assert all(p.x + p.w <= 4 or p.instr.name == "XIC" for p in narrow.placed
               if p.y == 0)


def test_marks_name_the_instruction_that_changed():
    left = L.parse("XIC(A)XIC(B)OTE(C)")
    right = L.parse("XIC(A)XIO(B)OTE(C)OTE(D)")
    assert L.mark(left, right) == ([L.SAME, L.CHANGED, L.SAME],
                                   [L.SAME, L.CHANGED, L.SAME, L.ONLY])
    assert L.mark(None, right) == ([], [L.ONLY] * 4)


def _pairs(kind, name):
    sides = []
    for side in ("left", "right"):
        path = os.path.join(DATA, kind, f"{side}.{name}")
        with open(path, encoding="utf-8-sig") as handle:
            sides.append(formats.normalise(kind, handle.read().splitlines()))
    a, b = sides
    result = align.compare(a.lines, b.lines, Rules())
    return L.pairs(result.rows, a.lines, b.lines, a.crumbs, b.crumbs)


def test_the_rungs_of_a_logix_comparison_pair_up():
    pairs = _pairs("l5k", "L5K")
    differing = [p for p in pairs if p.differs]
    added = [p for p in differing if p.left is None]
    assert added and added[0].right.text == "Rung: XIC(Estop_OK)OTE(Safety_OK);"
    edited = [p for p in differing if p.left is not None and p.right is not None]
    assert edited[0].left.label == "Rung 0" and edited[0].right.label == "Rung 1"
    assert edited[0].right.comments == ["Start the conveyor", "Stop wins over start"]
    assert edited[0].right.where.endswith("MainRoutine")
    # A renumbered rung that did not change is listed and does not differ.
    assert any(not p.differs and p.left.label != p.right.label for p in pairs)
    assert _pairs("l5x", "L5X")


def test_a_removed_and_added_rung_in_one_place_are_one_pair():
    left = ["  Routine R (RLL)", "    Rung: XIC(A)OTE(B);"]
    right = ["  Routine R (RLL)", "    Rung: XIO(Q)TON(T,?,?);"]
    rows = [(0, 0, align.EQUAL), (1, -1, align.DELETED), (-1, 1, align.INSERTED)]
    pairs = L.pairs(rows, left, right)
    assert len(pairs) == 1 and pairs[0].left and pairs[0].right and pairs[0].differs


def test_the_tab_draws_a_logix_pair_as_rungs(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app import cli
    from app.core.config import Config
    from app.ui.window import MainWindow

    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    try:
        window.resize(1400, 800)
        window.open_request(cli.parse([os.path.join(DATA, "l5k", "left.L5K"),
                                       os.path.join(DATA, "l5k", "right.L5K")]))
        window.show()
        tab = window.pages.currentWidget()
        end = time.monotonic() + 10
        while tab.session.result is None and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert "rungs" in tab.available_modes()
        tab.set_mode("rungs")
        QCoreApplication.processEvents()
        assert tab.stack.currentWidget() is tab.rungs
        current, total = tab.rungs.position()
        assert total >= 2 and current == 1
        assert "Rung" in tab.count.text()
        tab._navigate("next")
        assert tab.rungs.position()[0] == 2
        tab.rungs.set_all(True)
        assert len(tab.rungs.canvas.shown) > total
        tab.rungs.canvas.viewport().grab()          # paints without raising
        row = tab.rungs.current_pair().row
        tab._rung_to_text(row)
        assert tab.stack.currentWidget() is tab.view
        tab.session.set_structure(False)
        end = time.monotonic() + 5
        while tab.session.result is None and time.monotonic() < end:
            QCoreApplication.processEvents()
        assert "rungs" not in tab.available_modes()
    finally:
        window._may_close = lambda pages: True
        window.close()
