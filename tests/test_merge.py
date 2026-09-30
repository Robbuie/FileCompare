"""Three-way merge: which changes are taken on their own and which conflict."""

from app.core.diff import merge3 as M


def test_one_sided_changes_merge_themselves():
    base = ["a", "b", "c", "d", "e"]
    mine = ["a", "B", "c", "d", "e"]
    theirs = ["a", "b", "c", "d", "E", "f"]
    result = M.merge(base, mine, theirs)
    assert not result.conflicts
    out, _ = result.output()
    assert out == ["a", "B", "c", "d", "E", "f"]
    kinds = [c.kind for c in result.chunks]
    assert M.MINE in kinds and M.THEIRS in kinds


def test_the_same_change_on_both_sides_is_not_a_conflict():
    result = M.merge(["x", "y"], ["x", "Y"], ["x", "Y"])
    assert [c.kind for c in result.chunks] == [M.EQUAL, M.BOTH]
    assert result.output()[0] == ["x", "Y"]


def test_a_conflict_is_marked_until_resolved():
    base = ["one", "two", "three"]
    mine = ["one", "TWO", "three"]
    theirs = ["one", "deux", "three"]
    result = M.merge(base, mine, theirs)
    assert len(result.conflicts) == 1
    out, spans = result.output(labels=("L", "B", "R"))
    assert out == ["one", "<<<<<<< L", "TWO", "||||||| B", "two", "=======", "deux",
                   ">>>>>>> R", "three"]
    chunk = result.chunks[result.conflicts[0]]
    assert spans[result.conflicts[0]] == (1, 8)
    chunk.resolution = M.THEIRS_THEN_MINE
    assert result.output()[0] == ["one", "deux", "TWO", "three"]
    assert not result.unresolved
    chunk.resolution = M.CUSTOM
    chunk.custom = ["dos"]
    assert result.output()[0] == ["one", "dos", "three"]


def test_insertions_at_the_same_place_conflict_and_elsewhere_do_not():
    base = ["a", "b"]
    result = M.merge(base, ["a", "m", "b"], ["a", "t", "b"])
    assert len(result.conflicts) == 1
    result = M.merge(base, ["m", "a", "b"], ["a", "b", "t"])
    assert not result.conflicts and result.output()[0] == ["m", "a", "b", "t"]


def test_empty_files():
    assert M.merge([], [], []).output()[0] == []
    assert M.merge([], ["x"], []).output()[0] == ["x"]


def test_the_merge_tab_resolves_and_saves(qt_app, tmp_path):
    import time

    from PySide6.QtCore import QCoreApplication

    from app import cli
    from app.core.config import Config
    from app.ui.mergetab import MergeTab
    from app.ui.window import MainWindow

    (tmp_path / "base.txt").write_bytes(b"one\r\ntwo\r\nthree\r\nfour\r\n")
    (tmp_path / "mine.txt").write_bytes(b"one\r\nTWO\r\nthree\r\nfour\r\n")
    (tmp_path / "theirs.txt").write_bytes(b"one\r\ndeux\r\nthree\r\nFOUR\r\n")
    out = tmp_path / "merged.txt"
    out.write_bytes(b"<<<<<<< git's own markers\r\n")
    request = cli.parse(["--merge", str(tmp_path / "mine.txt"), str(tmp_path / "theirs.txt"),
                         str(tmp_path / "base.txt"), "-o", str(out)])
    assert request.wait and not request.error
    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    window.open_request(request)
    tab = window.pages.currentWidget()
    assert isinstance(tab, MergeTab)
    end = time.monotonic() + 10
    while tab.session.merge is None and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert tab.session.unresolved == 1
    assert "Conflict 1 of 1" in tab.count.text()
    tab.take(M.MINE_THEN_THEIRS)
    assert tab.session.unresolved == 0
    assert tab.save()
    end = time.monotonic() + 10
    while tab.session.saving and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert out.read_bytes() == b"one\r\nTWO\r\ndeux\r\nthree\r\nFOUR\r\n"
    assert window.merge_ok
    window.close()
