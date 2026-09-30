"""The diff engine: matching, the row model, the rules, intraline marks.

Most of what this application does that can go wrong quietly is here, and all
of it runs without a window.
"""

import random
import time

import pytest

from app.core.diff import align, intraline, lines
from app.core.diff.align import CHANGED, DELETED, EQUAL, IGNORED, INSERTED, NONE
from app.core.rules import Rules, normaliser


# ------------------------------------------------------------------- helpers

def check_rows(result, left, right):
    """Every line of each side appears exactly once, in order, and every
    row's kind agrees with what is in it."""
    seen_left = [row[0] for row in result.rows if row[0] != NONE]
    seen_right = [row[1] for row in result.rows if row[1] != NONE]
    assert seen_left == list(range(len(left)))
    assert seen_right == list(range(len(right)))
    for i, j, kind in result.rows:
        if kind == EQUAL:
            assert left[i] == right[j]
        elif kind == DELETED:
            assert i != NONE and j == NONE
        elif kind == INSERTED:
            assert i == NONE and j != NONE
        elif kind == CHANGED:
            assert i != NONE and j != NONE


def pairs(result, left, right):
    return [(left[i] if i != NONE else None, right[j] if j != NONE else None, kind)
            for i, j, kind in result.rows]


# --------------------------------------------------------------- lines.py

def test_runs_are_real_matches_in_order():
    rng = random.Random(7)
    for _ in range(200):
        a = [rng.randrange(6) for _ in range(rng.randrange(40))]
        b = [rng.randrange(6) for _ in range(rng.randrange(40))]
        last_i = last_j = -1
        for i, j, n in lines.matches(a, b):
            assert n > 0
            assert i > last_i and j > last_j
            assert a[i:i + n] == b[j:j + n]
            last_i, last_j = i + n - 1, j + n - 1


def test_identical_and_empty():
    assert lines.matches([1, 2, 3], [1, 2, 3]) == [(0, 0, 3)]
    assert lines.matches([], [1]) == []
    assert lines.matches([1], []) == []


def test_a_function_inserted_above_does_not_steal_the_braces():
    """Myers pairs the new function's closing brace with the old one's."""
    left = ["int a() {", "  return 1;", "}"]
    right = ["int z() {", "  return 0;", "}", "int a() {", "  return 1;", "}"]
    result = align.compare(left, right)
    check_rows(result, left, right)
    assert pairs(result, left, right)[3:] == [
        ("int a() {", "int a() {", EQUAL),
        ("  return 1;", "  return 1;", EQUAL),
        ("}", "}", EQUAL),
    ]
    assert [kind for _l, _r, kind in pairs(result, left, right)[:3]] == [INSERTED] * 3


def test_large_file_with_scattered_edits_is_fast():
    rng = random.Random(1)
    left = [f"line {i} {rng.random()}" for i in range(100_000)]
    right = list(left)
    for k in range(0, 100_000, 997):
        right[k] = f"edited {k}"
    right.insert(5000, "new")
    del right[70000:70010]
    began = time.perf_counter()
    result = align.compare(left, right)
    assert time.perf_counter() - began < 5.0
    check_rows(result, left, right)
    assert len(result.differences) >= 100


def test_only_common_lines_still_align():
    left = ["{", "}", ""] * 2000
    right = list(left)
    right[3001] = "x"
    result = align.compare(left, right)
    check_rows(result, left, right)
    assert len(result.differences) == 1


# ---------------------------------------------------------------- align.py

def test_identical_files_are_exact():
    text = ["a", "b", "c"]
    result = align.compare(text, list(text))
    assert result.exact and result.identical
    assert result.blocks == []


def test_edited_lines_are_paired_by_likeness_not_position():
    left = ["header", "Address = 192.168.1.20", "Gateway = 192.168.1.1", "footer"]
    right = ["header", "Comment = new", "Address = 192.168.1.21", "footer"]
    result = align.compare(left, right)
    check_rows(result, left, right)
    rows = pairs(result, left, right)
    assert ("Address = 192.168.1.20", "Address = 192.168.1.21", CHANGED) in rows


def test_a_line_replaced_by_something_unrecognisable_is_still_an_edit():
    result = align.compare(["a", "b", "c"], ["a", "X", "c"])
    assert result.rows[1] == (1, 1, CHANGED)


def test_blocks_group_consecutive_differences():
    left = ["a", "b", "c", "d", "e"]
    right = ["a", "B", "c", "d", "E", "f"]
    result = align.compare(left, right)
    assert [(b.start, b.end) for b in result.blocks] == [(1, 2), (4, 6)]
    assert all(b.significant for b in result.blocks)


def test_whitespace_rules():
    left = ["x = 1", "y=2   ", "  z  =  3"]
    right = ["x = 1", "y=2", "z = 3"]
    exact = align.compare(left, right)
    assert len(exact.differences) == 1
    trailing = align.compare(left, right, Rules(whitespace="trailing"))
    kinds = [k for _l, _r, k in trailing.rows]
    assert kinds[1] == IGNORED and kinds[2] == CHANGED
    change = align.compare(left, right, Rules(whitespace="change"))
    assert [k for _l, _r, k in change.rows][2] == IGNORED   # runs of spaces collapse
    assert not align.compare(["a b"], ["ab"], Rules(whitespace="change")).identical
    everything = align.compare(left, right, Rules(whitespace="all"))
    assert everything.identical and not everything.exact


def test_ignored_differences_are_shown_not_hidden():
    result = align.compare(["Hello"], ["hello"], Rules(case=True))
    assert result.identical
    assert result.rows == [(0, 0, IGNORED)]
    assert len(result.blocks) == 1 and not result.blocks[0].significant


def test_blank_lines_rule():
    left = ["a", "", "b", "c"]
    right = ["a", "b", "", "", "c"]
    exact = align.compare(left, right)
    assert not exact.identical
    loose = align.compare(left, right, Rules(blank_lines=True))
    check_rows(loose, left, right)
    assert loose.identical


def test_unimportant_patterns():
    left = ['<Controller ExportDate="Mon Sep 01 10:00:00 2026">', "<Tag/>"]
    right = ['<Controller ExportDate="Tue Sep 02 11:30:00 2026">', "<Tag/>"]
    rules = Rules(patterns=(r'ExportDate="[^"]*"',))
    assert align.compare(left, right, rules).identical
    assert not align.compare(left, right).identical


def test_a_bad_pattern_is_skipped_not_raised():
    key = normaliser(Rules(patterns=("([unclosed",)))
    assert key("text") == "text"


def test_rules_off_compares_raw_text():
    rules = Rules(whitespace="all", case=True).toggled()
    assert not align.compare(["A B"], ["ab"], rules).identical
    assert rules.describe() == "Rules off"


def test_navigation_helpers():
    left = ["a", "b", "c", "d", "e", "f"]
    right = ["a", "X", "c", "d", "Y", "f"]
    result = align.compare(left, right)
    assert result.next_difference(-1) == 0
    assert result.next_difference(1) == 1
    assert result.previous_difference(4) == 0
    assert result.block_at(4) == 1 and result.block_at(2) is None


# ------------------------------------------------------------ intraline.py

def test_char_marks_the_changed_digit():
    a, b = intraline.spans("Address = 192.168.1.20", "Address = 192.168.1.21")
    assert a == [(21, 22)] and b == [(21, 22)]


def test_word_marks_whole_words():
    a, b = intraline.spans("Tool = Sander 150", "Tool = Sander 180", "word")
    assert a == [(14, 17)] and b == [(14, 17)]


def test_unrelated_lines_are_marked_whole():
    a, b = intraline.spans("completely different", "xyz 123 qq")
    assert a == [(0, 20)] and b == [(0, 10)]


def test_equal_lines_have_no_marks():
    assert intraline.spans("same", "same") == ([], [])


@pytest.mark.parametrize("mode", ["char", "word"])
def test_marks_stay_inside_the_lines(mode):
    rng = random.Random(3)
    alphabet = "ab =.1\t"
    for _ in range(300):
        x = "".join(rng.choice(alphabet) for _ in range(rng.randrange(30)))
        y = "".join(rng.choice(alphabet) for _ in range(rng.randrange(30)))
        sa, sb = intraline.spans(x, y, mode)
        for start, end in sa:
            assert 0 <= start < end <= len(x)
        for start, end in sb:
            assert 0 <= start < end <= len(y)


def test_comments_are_looked_past_when_asked():
    from app.core.rules import Rules, comment_markers

    left = ["x = 1  # old note", "# a whole comment", "y = 2"]
    right = ["x = 1  # new note", "y = 2"]
    plain = align.compare(left, right)
    assert len(plain.differences) == 1
    rules = Rules(comments=True, markers=comment_markers("a.py"))
    looked = align.compare(left, right, rules)
    assert looked.identical and not looked.exact
    assert comment_markers("prog.vb") == ("'", "REM ")
    assert comment_markers("notes.txt") == ()
