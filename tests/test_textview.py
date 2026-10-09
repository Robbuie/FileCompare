"""The text view's show filter, folds and line details (1.18), the path box
over a file, and the two difference palettes."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication

from app.core.diff import align
from app.theme import sheet
from app.ui.diffview import DiffView, ViewState

E, C, D, I = align.EQUAL, align.CHANGED, align.DELETED, align.INSERTED


def _state(kinds, blocks=None):
    state = ViewState()
    rows = []
    left = right = 0
    for kind in kinds:
        li = left if kind != I else align.NONE
        ri = right if kind != D else align.NONE
        rows.append((li, ri, kind))
        left += kind != I
        right += kind != D
    state.rows = rows
    if blocks is None:
        comparison = align.Comparison(rows=rows)
        blocks = comparison.blocks if hasattr(comparison, "blocks") else []
    state.blocks = blocks
    return state


def _blocks(kinds):
    """The difference blocks of a row list, as `align` makes them."""
    from app.core.diff.align import Block

    out = []
    start = None
    for r, kind in enumerate(kinds + [E]):
        if kind != E and start is None:
            start = r
        elif kind == E and start is not None:
            out.append(Block(start=start, end=r, kind=kinds[start], significant=True))
            start = None
    return out


KINDS = [E] * 10 + [C, C] + [E] * 20 + [D] + [E] * 2 + [I] + [E] * 10


def _filtered(show, context=3):
    state = _state(KINDS, _blocks(KINDS))
    state.show = show
    state.context = context
    state.rebuild_order()
    return state


def test_all_lines_costs_nothing():
    state = _filtered("all")
    assert state.order is None
    assert state.count() == len(KINDS)
    assert state.row_of(5) == 5 and state.display_of(5) == 5


def test_differences_only_folds_every_matching_run():
    state = _filtered("diffs")
    shown = [state.row_of(line) for line in range(state.count())]
    rows = [r for r in shown if r is not None]
    assert rows == [10, 11, 32, 35]
    folds = [state.fold_of(line) for line in range(state.count()) if state.row_of(line) is None]
    assert folds == [(0, 10), (12, 32), (33, 35), (36, 46)]
    # Every hidden row maps to the fold that hides it, and back.
    for row in range(len(KINDS)):
        line = state.display_of(row)
        if state.hidden(row):
            first, stop = state.fold_of(line)
            assert first <= row < stop
        else:
            assert state.row_of(line) == row


def test_context_keeps_lines_round_each_difference_and_never_folds_one_line():
    state = _filtered("context", 3)
    kept = {state.row_of(line) for line in range(state.count())} - {None}
    assert {7, 8, 9, 10, 11, 12, 13, 14} <= kept
    assert 6 not in kept and 15 not in kept
    # 32 and 35 are three apart: the two rows between them are context.
    assert {33, 34} <= kept
    # A run of one hidden line is shown rather than folded.
    lone = _state([E, E, E, E, C, E, E, E, E, E, C, E, E, E, E],
                  _blocks([E, E, E, E, C, E, E, E, E, E, C, E, E, E, E]))
    lone.show, lone.context = "context", 2
    lone.rebuild_order()
    assert all(lone.row_of(line) is not None
               for line in range(lone.display_of(4), lone.display_of(10) + 1))


def test_same_only_hides_the_differences():
    state = _filtered("same")
    kept = {state.row_of(line) for line in range(state.count())} - {None}
    assert 10 not in kept and 32 not in kept and 0 in kept


def test_an_opened_fold_stays_open_until_the_filter_changes():
    state = _filtered("diffs")
    state.opened.add((12, 32))
    state.rebuild_order()
    kept = {state.row_of(line) for line in range(state.count())} - {None}
    assert set(range(12, 32)) <= kept


def _wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def test_the_view_steps_and_moves_over_folds(qt_app):
    view = DiffView()
    view.apply_tokens(sheet.tokens("dark", "blue", "normal"))
    view.resize(900, 400)
    left = [f"line {i}" for i in range(60)]
    right = list(left)
    right[20] = "changed 20"
    right[45] = "changed 45"
    comparison = align.compare(left, right)
    view.set_comparison(comparison, left, right, "char")
    view.set_show("diffs")
    s = view.state
    assert s.count() < len(s.rows)
    view.first_difference()
    assert s.cursor == 20
    view.next_difference()
    assert s.cursor == 45
    # Down from the first difference lands on the next shown row, not in
    # the fold between them.
    view.first_difference()
    view.move_cursor(1, False)
    assert s.cursor == 45
    # Selecting a hidden row (find does) opens its fold.
    view.select_rows(0, 30, 31)
    assert not s.hidden(30)
    view.set_show("all")
    assert s.order is None


def test_classic_puts_every_difference_in_one_red_and_family_does_not():
    classic = sheet.tokens("dark", "blue", "normal", "classic")
    family = sheet.tokens("dark", "blue", "normal", "family")
    assert classic["diff_palette"] == "classic" and family["diff_palette"] == "family"
    assert classic["diff_add_bar"] == classic["diff_del_bar"] == classic["diff_chg_bar"]
    assert len({family["diff_add_bar"], family["diff_del_bar"], family["diff_chg_bar"]}) == 3
    # Folders: a file on one side only is violet in Classic, whichever side.
    assert classic["dir_left_bar"] == classic["dir_right_bar"] == classic["diff_moved_bar"]
    assert family["dir_left_bar"] == family["diff_del_bar"]
    # A merge's taken lines are green either way.
    assert classic["merge_taken_row"] == family["merge_taken_row"]


def test_the_path_box_points_one_side_at_another_file(qt_app, tmp_path):
    from app.core import session as core
    from app.core.loader import Loader
    from app.ui.comparetab import CompareTab

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    a.write_text("one\ntwo\n")
    b.write_text("one\nTWO\n")
    c.write_text("one\ntwo\n")
    loader = Loader()
    session = core.Session(loader, str(a), str(b), options=core.Options(poll=False))
    tab = CompareTab(session, sheet.tokens("dark", "blue", "normal"))
    remembered = []
    tab.pairChanged.connect(lambda l, r: remembered.append((l, r)))
    session.start()
    try:
        assert _wait(lambda: session.kind == core.TEXT)
        assert tab.heads[1].field.text().endswith("b.txt")
        assert session.result.differences
        tab.heads[1].field.setText(str(c))
        tab.heads[1].field.returnPressed.emit()
        assert _wait(lambda: session.kind == core.TEXT and session.sides[1].path == str(c))
        assert not session.result.differences
        assert remembered == [(str(a), str(c))]
        assert session.sides[0].doc is not None        # the left was not read again
    finally:
        tab.stop()
        loader.shutdown()
