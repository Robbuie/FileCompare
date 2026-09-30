"""Folder compare: the merged tree and its verdicts, the walk, the contents."""

import os
import time

from app.core import folders as F
from app.core.folders import Entry, Mask
from app.io import walk


def e(rel, size=10, mtime=1000.0, is_dir=False):
    return Entry(rel=rel, is_dir=is_dir, size=size, mtime=mtime)


def d(rel):
    return Entry(rel=rel, is_dir=True)


def find(root, rel):
    for node in root.walk():
        if node.rel.lower() == rel.lower():
            return node
    raise KeyError(rel)


def test_verdicts_follow_file_managers_rules():
    root = F.build(
        [e("same.txt"), e("newer.txt", mtime=2000), e("size.txt", size=5),
         e("left.txt"), e("Case.TXT"), e("rounded.txt", mtime=1001.5), d("clash")],
        [e("same.txt"), e("newer.txt"), e("size.txt", size=6),
         e("right.txt"), e("case.txt"), e("rounded.txt"), e("clash")])
    assert find(root, "same.txt").status == F.SAME
    assert find(root, "newer.txt").status == F.NEWER_LEFT
    assert find(root, "size.txt").status == F.DIFFERENT
    assert find(root, "left.txt").status == F.ONLY_LEFT
    assert find(root, "right.txt").status == F.ONLY_RIGHT
    assert find(root, "case.txt").status == F.SAME       # names ignore case
    assert find(root, "rounded.txt").status == F.SAME    # within two seconds
    assert find(root, "clash").status == F.CLASH


def test_folders_carry_what_is_under_them():
    root = F.build([d("a"), e("a\\x.txt"), d("b"), e("b\\y.txt"), d("only")],
                   [d("a"), e("a\\x.txt", mtime=5000), d("b"), e("b\\y.txt")])
    assert find(root, "a").status == F.DIFFERENT and find(root, "a").differing == 1
    assert find(root, "b").status == F.SAME
    assert find(root, "only").status == F.ONLY_LEFT
    assert root.files == 2 and root.differing >= 1


def test_masks_include_files_and_exclude_anything():
    mask = Mask.parse("*.ini; -.git; -*.bak")
    assert mask.include == ("*.ini",) and mask.exclude == (".git", "*.bak")
    root = F.build([d(".git"), e(".git\\config"), e("a.ini"), e("a.txt"), e("x.bak"),
                    d("sub"), e("sub\\b.INI"), d("empty"), e("empty\\z.txt")],
                   [], mask=mask)
    names = sorted(n.rel for n in root.walk())
    assert names == ["a.ini", "sub", "sub\\b.INI"]


def test_show_filter_keeps_a_folder_when_something_under_it_shows():
    root = F.build([d("a"), e("a\\x.txt"), e("same.txt")],
                   [d("a"), e("a\\x.txt", mtime=9000), e("same.txt")])
    assert F.shown(find(root, "a"), F.SHOW_DIFFERENT)
    assert not F.shown(find(root, "same.txt"), F.SHOW_DIFFERENT)
    assert F.shown(find(root, "a\\x.txt"), F.SHOW_RIGHT)
    assert not F.shown(find(root, "a\\x.txt"), F.SHOW_LEFT)


def test_content_compare_settles_the_undecided():
    root = F.build([e("moved.txt", mtime=1000), e("edited.txt", mtime=1000)],
                   [e("moved.txt", mtime=9000), e("edited.txt", mtime=9000)])
    candidates = F.content_candidates(root)
    assert {n.rel for n in candidates} == {"moved.txt", "edited.txt"}
    F.settle(find(root, "moved.txt"), True)
    F.settle(find(root, "edited.txt"), False)
    assert find(root, "moved.txt").status == F.CONTENT_SAME
    assert find(root, "edited.txt").status == F.CONTENT_DIFF
    assert root.differing == 1
    assert "1 of 2 differ" in F.summary(root)


def test_walk_and_same_bytes(tmp_path):
    (tmp_path / "a" / "sub").mkdir(parents=True)
    (tmp_path / "a" / "one.txt").write_bytes(b"x" * 100)
    (tmp_path / "a" / "sub" / "two.txt").write_bytes(b"y")
    entries = walk.walk(str(tmp_path / "a"))
    rels = sorted((en.rel.replace("\\", "/"), en.is_dir) for en in entries)
    assert rels == [("one.txt", False), ("sub", True), ("sub/two.txt", False)]
    (tmp_path / "b.bin").write_bytes(b"x" * 100)
    (tmp_path / "c.bin").write_bytes(b"x" * 99 + b"z")
    assert walk.same_bytes(str(tmp_path / "a" / "one.txt"), str(tmp_path / "b.bin"))
    assert not walk.same_bytes(str(tmp_path / "b.bin"), str(tmp_path / "c.bin"))


def test_a_cancelled_walk_stops(tmp_path):
    progress = walk.Progress()
    progress.cancel.set()
    try:
        walk.walk(str(tmp_path), progress)
    except walk.Cancelled:
        pass
    else:
        raise AssertionError("should have stopped")


def test_the_folder_session_walks_both_sides_and_compares_contents(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app.core.folderdiff import FolderSession
    from app.core.loader import Loader

    left, right = tmp_path / "L", tmp_path / "R"
    for root in (left, right):
        (root / "sub").mkdir(parents=True)
        (root / "same.txt").write_bytes(b"same")
    (left / "sub" / "touched.txt").write_bytes(b"12345")
    (right / "sub" / "touched.txt").write_bytes(b"12345")
    os.utime(right / "sub" / "touched.txt", (1_000_000, 1_000_000))
    (left / "gone.txt").write_bytes(b"x")

    loader = Loader()
    session = FolderSession(loader, str(left), str(right))
    session.start()
    end = time.monotonic() + 10
    while session.tree is None and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert session.tree is not None
    assert find(session.tree, "gone.txt").status == F.ONLY_LEFT
    assert find(session.tree, "sub\\touched.txt").status in (F.NEWER_LEFT, F.NEWER_RIGHT)

    session.compare_contents()
    end = time.monotonic() + 10
    while session.busy and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert find(session.tree, "sub\\touched.txt").status == F.CONTENT_SAME
    loader.shutdown()


def test_the_window_shows_two_folders_and_opens_a_pair(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app import cli
    from app.core import session as core
    from app.core.config import Config
    from app.ui.comparetab import CompareTab
    from app.ui.window import MainWindow

    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a.txt").write_bytes(b"one\n")
    (right / "a.txt").write_bytes(b"two\n")
    os.utime(right / "a.txt", (5_000_000, 5_000_000))
    (left / "only.txt").write_bytes(b"x\n")

    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    window.open_request(cli.parse([str(left), str(right)]))
    window.show()
    tab = window.pages.currentWidget()

    def ready():
        QCoreApplication.processEvents()
        return tab.folders is not None and tab.folders.session.tree is not None

    end = time.monotonic() + 10
    while not ready() and time.monotonic() < end:
        time.sleep(0.01)
    assert tab.session.kind == core.FOLDERS
    view = tab.folders
    assert view.model.rowCount() == 2
    view._step(1)
    assert view.selected()[0].rel == "a.txt"
    view._open()
    end = time.monotonic() + 5
    while window.pages.count() < 2 and time.monotonic() < end:
        QCoreApplication.processEvents()
    opened = window.pages.currentWidget()
    assert isinstance(opened, CompareTab) and opened is not tab
    view.set_show(F.SHOW_RIGHT)
    assert view.model.rowCount() == 0
    view.set_show(F.SHOW_SAME)
    assert view.model.rowCount() == 0
    view.set_show(F.SHOW_LEFT)
    assert view.model.rowCount() == 2
    window._may_close = lambda pages: True
    window.close()


def test_a_file_only_on_one_side_opens_against_nothing(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app.core import session as core
    from app.core.loader import Loader
    from app.core.session import Options, Session

    (tmp_path / "x.txt").write_bytes(b"a\nb\n")
    loader = Loader()
    s = Session(loader, str(tmp_path / "x.txt"), "", options=Options(poll=False))
    s.start()
    end = time.monotonic() + 5
    while s.kind != core.TEXT and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert s.kind == core.TEXT and s.result.counts()["deleted"] == 2
