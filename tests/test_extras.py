"""The 0.9 extras: reports, recent pairs, and a file dropped on one side."""

from app.core import report
from app.core.diff import align


def test_the_html_report_shows_differences_with_context_only():
    left = [f"line {n}" for n in range(40)]
    right = list(left)
    right[20] = "line twenty <changed>"
    result = align.compare(left, right)
    page = report.html_report(result, left, right, names=("a.txt", "b.txt"), rules="Exact")
    assert "line twenty &lt;changed&gt;" in page
    assert "line 17" in page and "line 16" not in page     # three lines of context
    assert page.count('class="chg"') == 1
    assert "<script" not in page


def test_the_patch_is_unified_diff():
    result = align.compare(["a", "b"], ["a", "c"])
    text = report.unified(result, ["a", "b"], ["a", "c"], ("x", "y"))
    assert text.splitlines()[:2] == ["--- x", "+++ y"] and "-b" in text and "+c" in text


def test_recent_pairs_are_remembered_newest_first(qt_app, tmp_path):
    from app.core.config import Config
    from app.ui.window import MainWindow

    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.txt").write_text(name)
    config = Config(path=str(tmp_path / "c.json"))
    window = MainWindow(config, look={}, look_source="own", custom_frame=False)
    a, b, c = (str(tmp_path / f"{n}.txt") for n in "abc")
    window.compare(a, b)
    window.compare(a, c)
    window.compare(a, b)
    assert config.get("recent") == [[a, b], [a, c]]
    start = window.new_tab()
    assert start._recent[0] == (a, b)
    window._may_close = lambda pages: True
    window.close()
