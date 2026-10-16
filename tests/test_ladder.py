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
        # 1.24: a Logix pair opens as ladder without being asked.
        assert tab.shown_mode() == "rungs"
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
        # The routine list: one routine alone, then all of them again.
        key = L.routine_of(tab.rungs.canvas.shown[0].pair)
        tab.rungs.set_routine(key)
        assert all(L.routine_of(item.pair) == key for item in tab.rungs.canvas.shown)
        tab.rungs.set_routine("")
        assert len(tab.rungs.canvas.shown) > total
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


def test_boxes_are_labelled_as_logix_designer_labels_them():
    ton = L.instructions(L.parse("TON(RunTimer,5000,0)"))[0]
    assert L.box_lines(ton) == [("Timer", "RunTimer"), ("Preset", "5000"), ("Accum", "0")]
    assert L.spec("ton").pins == ("EN", "DN")
    # An instruction it does not know (an AOI) is drawn, unlabelled.
    aoi = L.instructions(L.parse("Motor_AOI(M1,Start,Stop)"))[0]
    assert aoi.shape == "box" and L.box_lines(aoi) == [("", "M1"), ("", "Start"), ("", "Stop")]
    # Past its labels, an operand is unlabelled rather than dropped.
    jsr = L.instructions(L.parse("JSR(Sub,1,In1)"))[0]
    assert L.box_lines(jsr)[-1] == ("", "In1")
    assert L.instructions(L.parse("RES(T)"))[0].shape == "coil"
    # A box with status bits takes the rows they need.
    msg = L.layout(L.parse("MSG(M)")).placed[0]
    assert msg.h >= 2


def test_a_changed_box_names_the_operand_that_changed():
    left = L.parse("XIC(A)TON(T,5000,0)")
    right = L.parse("XIC(A)TON(T,7500,0)")
    assert L.mark(left, right) == ([L.SAME, L.CHANGED], [L.SAME, L.CHANGED])
    opposite_left, opposite_right = L.counterparts(left, right)
    ton = L.instructions(left)[1]
    assert L.changed_operands(ton, opposite_left[1]) == {1}
    assert L.changed_operands(L.instructions(right)[1], opposite_right[1]) == {1}
    # A different instruction, or a different count: nothing singled out.
    assert L.changed_operands(L.instructions(L.parse("GRT(A,B)"))[0],
                              L.instructions(L.parse("GEQ(A,B)"))[0]) == set()


def test_differences_outside_rungs_are_counted_for_the_rung_view():
    left = ["Tag Speed : REAL = 1.5", "Routine R (RLL)", "  Rung: XIC(A)OTE(B);"]
    right = ["Tag Speed : REAL = 2.25", "Routine R (RLL)", "  Rung: XIC(A)OTE(C);"]
    result = align.compare(left, right, Rules())
    assert len(result.differences) == 2
    assert L.other_differences(result.rows, result.differences, left, right) == 1
    crumbs = ["Tags", "Program P / R", "Program P / R / Rung 0"]
    pairs = L.pairs(result.rows, left, right, crumbs, crumbs)
    assert L.routine_of(pairs[0]) == "Program P / R"


def test_layout_takes_the_views_sizes():
    rung = L.parse("XIC(A)MOV(Source,Dest)OTE(B)")
    sized = L.layout(rung, size=lambda i: (3.5, 2) if i.shape == "box" else (1.5, 1))
    assert [p.w for p in sized.placed] == [1.5, 3.5, 1.5]
    assert sized.height == 2 and sized.width == 6.5
    assert L.layout(rung).placed[1].w == L.BOX_WIDTH      # the default


def test_long_tags_are_drawn_whole(qt_app):
    """1.26: an instruction is as wide as its text, a long tag is broken at a
    `.` or `_` and not cut, and a box past the half's width wraps."""
    from PySide6.QtGui import QFontMetricsF

    from app.ui import rungview as R

    view = R.RungView()
    view.resize(1400, 700)
    canvas = view.canvas
    canvas._metrics()
    canvas._cap = 6.0
    long = "Line4_Station03_Robot_Interface.Output_Data.Pass_Count"
    contact = L.instructions(L.parse(f"XIC({long})"))[0]
    w, _h = canvas._size(contact)
    lines = R._wrap(long, canvas.fm, w * canvas.cell_w - 6)
    assert "".join(lines) == long and len(lines) <= 2
    assert all(line.endswith(("_", ".")) for line in lines[:-1])
    box = L.instructions(L.parse(f"MOV(Short,{long})"))[0]
    bw, _bh = canvas._size(box)
    assert bw > L.BOX_WIDTH
    rows = canvas._box_rows(box, bw * canvas.cell_w - 16)
    assert ["".join(v) for _l, v in rows] == ["Short", long]
    # Narrower than the value: wrapped, nothing lost.
    canvas._cap = 2.5
    bw2, bh2 = canvas._size(L.instructions(L.parse(f"CPT(Dest,{long}*{long})"))[0])
    assert bw2 == 2.5
    rows = canvas._box_rows(L.instructions(L.parse(f"CPT(Dest,{long}*{long})"))[0],
                            bw2 * canvas.cell_w - 16)
    assert "".join(rows[1][1]) == f"{long}*{long}" and len(rows[1][1]) > 1
    assert QFontMetricsF(view.mono)            # fonts exist
    tip = R.describe(L.instructions(L.parse("TON(T,5000,0)"))[0])
    assert tip.splitlines() == ["TON  Timer On Delay", "Timer:  T", "Preset:  5000",
                                "Accum:  0"]
    assert R.describe(contact).splitlines() == ["XIC  Examine If Closed", long]


def test_the_routine_list_lists_what_changed_and_folds_the_rest(qt_app):
    from app.ui import rungview as R

    def pair(where, differs):
        rung = L.Rung("Rung: XIC(A);", f"{where} / Rung 0")
        return L.RungPair(rung, rung, differs)

    pairs = [pair(f"Program P{n} / R{k}", n == 3 and k == 1)
             for n in range(8) for k in range(4)] + [pair("AOI Valve / Logic", True)]
    listing = R.RoutineList()
    listing.set_pairs(pairs, R.ALL, changed_only=True)
    keys = set(listing._items)
    assert keys == {R.ALL, "Program P3", "Program P3 / R1", "AOI Valve / Logic"}
    assert "31 unchanged routines" in listing.summary.text()
    listing.set_changed_only(False)
    assert len([k for k in listing._items if " / " in k]) == 33
    program = listing._items["Program P5"]
    assert not program.isExpanded()            # a long list starts folded
    listing.filter.setText("p5 r2")
    shown = [k for k, item in listing._items.items() if not item.isHidden()]
    assert set(shown) == {R.ALL, "Program P5", "Program P5 / R2"}
    assert R.in_routine(pairs[0], "Program P0") and not R.in_routine(pairs[0], "Program P1")
