"""Typing straight into a side (1.23): the caret and the splices keys make."""

from app.core import caret as C
from app.core.document import Document


def apply(lines, edit):
    out = list(lines)
    out[edit.start:edit.end] = list(edit.lines)
    return out


def test_typing_inserts_at_the_caret_and_moves_it_on():
    lines = ["hello world"]
    edit = C.insert(lines, C.Caret(0, 0, 5), ",")
    assert apply(lines, edit) == ["hello, world"]
    assert edit.caret == C.Caret(0, 0, 6) and edit.group


def test_enter_splits_the_line_and_keeps_the_indent():
    lines = ["    if x: y"]
    edit = C.newline(lines, C.Caret(0, 0, 9))
    assert apply(lines, edit) == ["    if x:", "     y"]
    assert edit.caret == C.Caret(0, 1, 4)


def test_backspace_at_the_start_joins_the_line_above():
    lines = ["abc", "def"]
    edit = C.backspace(lines, C.Caret(0, 1, 0))
    assert apply(lines, edit) == ["abcdef"] and edit.caret == C.Caret(0, 0, 3)
    assert C.backspace(lines, C.Caret(0, 0, 0)) is None


def test_delete_at_the_end_joins_the_next_line():
    lines = ["abc", "def"]
    edit = C.delete(lines, C.Caret(0, 0, 3))
    assert apply(lines, edit) == ["abcdef"]
    assert C.delete(lines, C.Caret(0, 1, 3)) is None


def test_a_fresh_caret_on_a_filler_row_makes_its_line_on_the_first_key():
    lines = ["one", "three"]
    edit = C.insert(lines, C.Caret(1, 1, 0, fresh=True), "two")
    assert apply(lines, edit) == ["one", "two", "three"]
    assert edit.caret == C.Caret(1, 1, 3)
    back = C.backspace(lines, C.Caret(1, 1, 0, fresh=True))
    assert back == C.Caret(1, 0, 3)          # moves, removes nothing


def test_a_paste_with_newlines_splits_where_they_are():
    lines = ["ab"]
    edit = C.insert(lines, C.Caret(0, 0, 1), "1\r\n2\n3")
    assert apply(lines, edit) == ["a1", "2", "3b"]
    assert edit.caret == C.Caret(0, 2, 1)


def test_columns_count_tabs_as_the_panes_draw_them():
    assert C.display_col("\tx", 1) == 4
    assert C.char_col("\tx", 4) == 1
    assert C.char_col("\tx", 1) == 0           # nearer the tab's start
    assert C.char_col("\tx", 3) == 1           # nearer its end
    assert C.char_col("abc", 99) == 3


def test_moves_cross_line_ends_and_home_goes_to_the_indent_first():
    lines = ["  ab", "cd"]
    assert C.move(lines, C.Caret(0, 0, 4), "right") == C.Caret(0, 1, 0)
    assert C.move(lines, C.Caret(0, 1, 0), "left") == C.Caret(0, 0, 4)
    assert C.move(lines, C.Caret(0, 0, 4), "home") == C.Caret(0, 0, 2)
    assert C.move(lines, C.Caret(0, 0, 2), "home") == C.Caret(0, 0, 0)
    assert C.move(["foo bar"], C.Caret(0, 0, 0), "word-right").col == 4


def test_a_caret_past_the_text_is_brought_back_inside_it():
    assert C.clamp(C.Caret(0, 9, 9), ["ab"]) == C.Caret(0, 0, 2)
    assert C.clamp(C.Caret(0, 0, 0), []) == C.Caret(0, 0, 0, True)


def test_keys_on_one_line_are_one_undo_step_and_a_save_starts_another():
    doc = Document.from_lines(["x"], ["\n"])
    caret = C.Caret(0, 0, 1)
    for ch in "yz":
        edit = C.insert(doc.lines, caret, ch)
        assert doc.replace(edit.start, edit.end, list(edit.lines), group=edit.group + "#1")
        caret = edit.caret
    assert doc.lines == ["xyz"]
    doc.undo()
    assert doc.lines == ["x"] and not doc.can_undo
    doc.redo()
    doc.mark_saved()
    edit = C.insert(doc.lines, C.Caret(0, 0, 3), "!")
    doc.replace(edit.start, edit.end, list(edit.lines), group=edit.group + "#1")
    assert doc.dirty
    doc.undo()
    assert doc.lines == ["xyz"] and not doc.dirty


def test_a_different_group_is_a_different_undo_step():
    doc = Document.from_lines(["a"], [""])
    doc.replace(0, 1, ["ab"], group="0:0#1")
    doc.replace(0, 1, ["abc"], group="0:0#2")
    doc.undo()
    assert doc.lines == ["ab"]
