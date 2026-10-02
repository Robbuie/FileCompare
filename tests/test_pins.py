"""Manual alignment (1.6): a pin holds a left line opposite a right line, the
diff runs separately on each side of it, and edits carry it along."""

from app.core.diff import align
from app.core.diff.align import CHANGED, EQUAL, NONE

from tests.test_edit import session_for


def row_of(result, i, j):
    return next(r for r, row in enumerate(result.rows) if row[0] == i and row[1] == j)


def test_a_pin_puts_two_lines_on_one_row():
    left = ["header", "Speed := 10;", "a", "b", "c"]
    right = ["header", "a", "b", "c", "Speed := 20;"]
    result = align.compare(left, right, pins=[(1, 4)])
    assert result.rows[row_of(result, 1, 4)][2] == CHANGED
    # Nothing matches across it: a, b, c are below it on the left and above
    # it on the right, so they cannot pair up.
    assert not any(k == EQUAL and left[i] in ("a", "b", "c") for i, _j, k in result.rows)
    seen_left = [i for i, _j, _k in result.rows if i != NONE]
    seen_right = [j for _i, j, _k in result.rows if j != NONE]
    assert seen_left == list(range(len(left))) and seen_right == list(range(len(right)))


def test_without_a_pin_the_same_pair_lines_up_differently():
    left = ["header", "Speed := 10;", "a", "b", "c"]
    right = ["header", "a", "b", "c", "Speed := 20;"]
    rows = align.compare(left, right).rows
    assert (1, 4, CHANGED) not in rows


def test_identical_pinned_lines_are_equal():
    left = ["x", "same", "y"]
    right = ["same", "p", "q"]
    result = align.compare(left, right, pins=[(1, 0)])
    assert result.rows[row_of(result, 1, 0)][2] == EQUAL


def test_crossing_and_out_of_range_pins_are_dropped_newest_first_wins():
    assert align.valid_pins([(5, 1), (1, 5)], 10, 10) == [(5, 1)]
    assert align.valid_pins([(1, 1), (3, 4), (99, 2)], 10, 10) == [(1, 1), (3, 4)]
    assert align.valid_pins([(2, 2), (2, 7)], 10, 10) == [(2, 2)]


def test_several_pins_hold_in_order():
    left = [f"L{k}" for k in range(10)]
    right = [f"R{k}" for k in range(10)]
    result = align.compare(left, right, pins=[(2, 7), (8, 9)])
    assert (2, 7, CHANGED) in result.rows and (8, 9, CHANGED) in result.rows


def test_shift_pins_moves_them_with_their_lines():
    pins = [(2, 2), (10, 12)]
    assert align.shift_pins(pins, 0, 0, 1, 3) == [(4, 2), (12, 12)]
    assert align.shift_pins(pins, 1, 2, 1, 0) == [(10, 11)]
    assert align.shift_pins(pins, 0, 20, 0, 5) == pins


def test_session_pins_survive_an_edit_above_them(qt_app, tmp_path):
    s, _a, _b = session_for(tmp_path, b"h\nSpeed := 10;\na\nb\nc\n",
                            b"h\na\nb\nc\nSpeed := 20;\n")
    s.pin(1, 4)
    assert (1, 4, CHANGED) in s.result.rows
    assert s.replace_lines(0, 0, 1, ["h", "new line"])
    assert s.pins == [(2, 4)]
    assert (2, 4, CHANGED) in s.result.rows
    assert s.undo(0)
    assert s.pins == [(1, 4)]
    s.swap()
    assert s.pins == [(4, 1)]
    assert s.unpin()
    assert s.pins == []


def test_a_new_pin_replaces_one_it_crosses(qt_app, tmp_path):
    s, _a, _b = session_for(tmp_path, b"1\n2\n3\n4\n5\n", b"a\nb\nc\nd\ne\n")
    s.pin(0, 3)
    s.pin(3, 0)
    assert s.pins == [(3, 0)]
    s.pin(4, 4)
    assert s.pins[0] == (4, 4) and (3, 0) in s.pins
