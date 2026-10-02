"""Moved blocks (1.5): a run removed in one place and added in another is one
difference with two ends, not a removal and an unrelated addition."""

import random

from app.core.diff import align
from app.core.diff.align import DELETED, INSERTED
from app.core.rules import Rules

RUNG_A = "XIC(Start)XIO(Stop)OTE(Motor_Run);"
RUNG_B = "XIC(Motor_Run)TON(Run_Timer,5000,0);"


def test_a_block_moved_down_is_one_move():
    left = ["header", RUNG_A, RUNG_B, "a1 = 1", "a2 = 2", "a3 = 3", "a4 = 4", "tail"]
    right = ["header", "a1 = 1", "a2 = 2", "a3 = 3", "a4 = 4", RUNG_A, RUNG_B, "tail"]
    result = align.compare(left, right)
    assert len(result.moves) == 1
    move = result.moves[0]
    assert move.left == (1, 3) and move.right == (5, 7)
    assert result.partner(move.left_block) == move.right_block
    assert result.partner(move.right_block) == move.left_block
    counts = result.counts()
    assert counts["moved"] == 2 and counts["deleted"] == 0 and counts["inserted"] == 0
    # The rows keep their kinds: copying the left end across still inserts.
    left_block = result.blocks[move.left_block]
    assert all(result.rows[r][2] == DELETED for r in range(left_block.start, left_block.end))
    right_block = result.blocks[move.right_block]
    assert all(result.rows[r][2] == INSERTED for r in range(right_block.start, right_block.end))
    assert result.moved_rows() == set(range(left_block.start, left_block.end)) | set(
        range(right_block.start, right_block.end))


def test_one_long_line_is_enough():
    left = ["h", RUNG_A, "x1", "x2", "x3", "t"]
    right = ["h", "x1", "x2", "x3", RUNG_A, "t"]
    assert len(align.compare(left, right).moves) == 1


def test_short_lines_are_coincidence_not_a_move():
    left = ["begin", "}", "aaaa", "bbbb", "cccc", "end"]
    right = ["begin", "aaaa", "bbbb", "cccc", "}", "end"]
    result = align.compare(left, right)
    assert result.moves == []
    assert all(block.move == -1 for block in result.blocks)


def test_a_move_beside_an_unrelated_removal_is_cut_out_of_it():
    left = ["h", "something else removed entirely", RUNG_A, RUNG_B, "a", "b", "c", "t"]
    right = ["h", "a", "b", "c", RUNG_A, RUNG_B, "t"]
    result = align.compare(left, right)
    assert len(result.moves) == 1
    plain = [b for b in result.blocks if b.move < 0 and b.significant]
    assert len(plain) == 1
    assert result.counts()["deleted"] == 1


def test_an_edited_copy_is_not_a_move():
    left = ["h", RUNG_A, "a", "b", "c", "t"]
    right = ["h", "a", "b", "c", RUNG_A.replace("Stop", "Halt"), "t"]
    assert align.compare(left, right).moves == []


def test_moves_follow_the_rules():
    left = ["h", "    " + RUNG_A, "a", "b", "c", "t"]
    right = ["h", "a", "b", "c", RUNG_A, "t"]
    assert align.compare(left, right).moves == []
    assert len(align.compare(left, right, Rules(whitespace="all")).moves) == 1


def test_two_blocks_swapped():
    one = [f"first block line {k} with enough text" for k in range(4)]
    two = [f"second block line {k} with enough text" for k in range(6)]
    result = align.compare(["h"] + one + two + ["t"], ["h"] + two + one + ["t"])
    assert len(result.moves) == 1
    assert result.moves[0].size == 4


def test_repeated_lines_stay_bounded_and_correct():
    rng = random.Random(5)
    left = [f"line {rng.randrange(40)} of a long and repetitive log" for _ in range(4000)]
    right = left[2000:] + left[:2000]
    result = align.compare(left, right)
    assert result.elapsed < 10
    for move in result.moves:
        assert left[move.left[0]:move.left[1]] == right[move.right[0]:move.right[1]]
    taken = [i for m in result.moves for i in range(*m.left)]
    assert len(taken) == len(set(taken))


def test_no_moves_leaves_the_blocks_as_they_were():
    left = ["a", "b", "c"]
    right = ["a", "B", "c", "d"]
    result = align.compare(left, right)
    assert result.moves == [] and "moved" in result.counts()
    assert result.partner(0) is None
