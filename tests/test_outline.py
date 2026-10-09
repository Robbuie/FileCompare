"""Where each line is in its file, difference summaries, the differences list,
and the Fluid and Unified layouts (1.19)."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication

from app.core import outline
from app.core.diff import align
from app.theme import sheet
from app.ui.diffview import DiffView


def test_python_sections_follow_indentation():
    lines = ["import os", "", "class Job:", "    def run(self, x):", "        return x",
             "", "    def stop(self):", "        pass", "", "def main():", "    Job()"]
    names = outline.sections(lines, "python")
    assert names[0] == ""
    assert names[4] == "class Job › def run(self, x)"
    assert names[7] == "class Job › def stop(self)"
    assert names[10] == "def main()"


def test_brace_languages_close_their_sections():
    lines = ["namespace Plant", "{", "    class Cell", "    {", "        int Add(int a, int b)",
             "        {", "            if (a > 0) { return a; }", '            var s = "}";',
             "            return a + b;", "        }", "    }", "}"]
    names = outline.sections(lines, "csharp")
    assert names[6] == "namespace Plant › class Cell › Add(int a, int b)"
    assert names[8] == names[6]                 # a brace in a string is not a brace
    assert names[10] == "namespace Plant › class Cell"
    assert names[11] == "namespace Plant"


def test_vb_structured_text_and_flat_files():
    vb = ["Public Class Form1", "    Private Sub Go(x As Integer)", "        y = 1",
          "    End Sub", "End Class"]
    assert outline.sections(vb, "vb.net")[2] == "Class Form1 › Sub Go"
    st = ["FUNCTION_BLOCK Fill", "VAR", "END_VAR", "x := 1;", "END_FUNCTION_BLOCK", "y := 2;"]
    names = outline.sections(st, "iec-st")
    assert names[3] == "FUNCTION_BLOCK Fill" and names[5] == ""
    assert outline.sections(["[A]", "x=1", "[B]", "y=2"], "ini") == ["[A]", "[A]", "[B]", "[B]"]
    md = ["# Plan", "a", "## Risks", "b", "# Next"]
    assert outline.sections(md, "markdown") == ["Plan", "Plan", "Plan › Risks",
                                                "Plan › Risks", "Next"]
    assert outline.sections(["x"], "") is None
    assert outline.sections(["x"], "nonsense") is None


def test_a_summary_says_what_changed_in_words():
    left = ["a", "shutil.copy(src, dst)", "keep", "gone"]
    right = ["a", "shutil.copy2(src, dst)", "keep", "new line"]
    comparison = align.compare(left, right)
    summaries = [outline.summary(comparison, i, left, right)
                 for i in range(len(comparison.blocks))]
    assert summaries[0][0] == "Line 2"
    assert "copy" in summaries[0][1] and "copy2" in summaries[0][1]
    only = align.compare(["a", "b", "c"], ["a", "c"])
    assert outline.summary(only, 0, ["a", "b", "c"], ["a", "c"]) == ("Left 2", "Only on the left: b")


def _view(left, right, layout):
    view = DiffView()
    view.apply_tokens(sheet.tokens("dark", "blue", "normal"))
    view.resize(900, 400)
    view.set_comparison(align.compare(left, right), left, right, "char")
    view.set_layout(layout)
    return view


def test_fluid_draws_each_side_without_fillers():
    left = [f"line {i}" for i in range(40)]
    right = left[:10] + ["new a", "new b", "new c"] + left[10:]
    view = _view(left, right, "fluid")
    s = view.state
    assert len(s.line_row[0]) == 40 and len(s.line_row[1]) == 43
    assert s.order is None and s.uni is None
    # The left side's 11th line comes straight after its 10th: no gap rows.
    assert s.line_row[0][10] == s.line_row[0][9] + 1 + 3
    view.scroll_to(12)
    assert view.left.top_line() == 10              # waits for the insertion to pass
    assert view.right.top_line() == 12
    view.set_layout("sbs")
    assert s.layout == "sbs"


def test_unified_lists_old_lines_then_new_under_a_heading():
    left = ["a", "one", "two", "z"]
    right = ["a", "ONE", "TWO", "z"]
    view = _view(left, right, "unified")
    s = view.state
    parts = [part for _row, part in s.uni]
    assert parts == [-1, -3, 0, 0, 1, 1, -1]
    view.first_difference()
    assert s.cursor == 1
    # Down from the first "-" line skips the heading and lands on the next row.
    view.move_cursor(1, False)
    assert s.cursor == 2
    view.set_show("diffs")
    assert any(part == -2 for _row, part in s.uni)


def _wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def test_the_differences_list_groups_by_section(qt_app, tmp_path):
    from app.core import session as core
    from app.core.loader import Loader
    from app.ui.comparetab import CompareTab

    a = tmp_path / "jobs.py"
    b = tmp_path / "jobs2.py"
    a.write_text("RETRIES = 3\n\ndef copy(n):\n    shutil.copy(n)\n    return n\n")
    b.write_text("RETRIES = 5\n\ndef copy(n):\n    shutil.copy2(n)\n    return n\n")
    loader = Loader()
    session = core.Session(loader, str(a), str(b), options=core.Options(poll=False))
    tab = CompareTab(session, sheet.tokens("dark", "blue", "normal"))
    tab.resize(1200, 600)
    tab.show()
    session.start()
    try:
        assert _wait(lambda: session.kind == core.TEXT)
        tab.refresh()
        assert tab.sidebar.count() == 2
        headings = [tab.sidebar.tree.topLevelItem(i).text(0)
                    for i in range(tab.sidebar.tree.topLevelItemCount())
                    if tab.sidebar.tree.topLevelItem(i).data(0, 257).block < 0]
        assert headings == ["Top of file", "def copy(n)"]
        tab.sidebar.goTo.emit(1)
        assert tab.view.state.current == 1
        assert "def copy(n)" in tab.location.text()
        tab.run_command("layout-unified")
        assert tab.view.state.layout == "unified"
        assert any("def copy(n)" in text for text in tab.view.state.headings.values())
        assert not tab.command_state("edit").enabled
    finally:
        tab.stop()
        loader.shutdown()
