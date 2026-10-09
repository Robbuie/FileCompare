"""The sync list (1.20): defaults from the update plans, choices, totals, and
requests that keep the update's newer-only rule for rows left at default."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication

from app.core import folders as F
from app.core import synclist as L
from app.core import syncplan as S


def _tree():
    left = [F.Entry("a.txt", False, 10, 200.0), F.Entry("b.txt", False, 10, 100.0),
            F.Entry("c.txt", False, 10, 100.0), F.Entry("only-left.txt", False, 5, 100.0),
            F.Entry("Photos", True, 0, 0.0), F.Entry("Photos\\1.jpg", False, 3000, 50.0),
            F.Entry("same.ini", False, 1, 100.0)]
    right = [F.Entry("a.txt", False, 9, 100.0), F.Entry("b.txt", False, 11, 300.0),
             F.Entry("c.txt", False, 12, 100.0), F.Entry("only-right.txt", False, 7, 100.0),
             F.Entry("same.ini", False, 1, 100.0)]
    return F.build(left, right)


def _node(root, rel):
    return next(n for n in root.walk() if n.rel.lower() == rel.lower())


def test_categories_and_words():
    root = _tree()
    assert L.category(_node(root, "a.txt")) == L.LEFT_NEWER
    assert L.category(_node(root, "b.txt")) == L.RIGHT_NEWER
    assert L.category(_node(root, "c.txt")) == L.DIFFERENT
    assert L.category(_node(root, "same.ini")) == L.SAME
    assert L.result(_node(root, "Photos")) == "Folder only on the left"
    assert L.result(_node(root, "c.txt")) == "Same time, different size"


def test_defaults_follow_an_update_each_way():
    root = _tree()
    decisions = L.decide(root)
    assert decisions.action(_node(root, "a.txt")) == L.RIGHT
    assert decisions.action(_node(root, "b.txt")) == L.LEFT
    assert decisions.action(_node(root, "c.txt")) == L.SKIP       # no clock says which
    assert decisions.action(_node(root, "only-left.txt")) == L.RIGHT
    assert decisions.action(_node(root, "only-right.txt")) == L.LEFT
    assert decisions.action(_node(root, "Photos")) == L.RIGHT     # whole
    # Inside a folder copied whole: no choice of its own.
    assert L.choices(_node(root, "Photos\\1.jpg")) == ()
    assert L.choices(_node(root, "same.ini")) == ()


def test_a_click_cycles_and_a_changed_row_survives_a_new_tree():
    root = _tree()
    decisions = L.decide(root)
    c = _node(root, "c.txt")
    assert decisions.cycle(c) == L.RIGHT
    assert decisions.changed(c)
    assert decisions.cycle(c) == L.LEFT
    assert decisions.cycle(c) == L.SKIP and not decisions.changed(c)
    decisions.set(c, L.LEFT)
    again = L.decide(_tree(), decisions)
    assert again.action(_node(_tree(), "c.txt")) == L.LEFT
    # Only-left rows cannot be copied left.
    only = _node(root, "only-left.txt")
    decisions.set(only, L.LEFT)
    assert decisions.action(only) == L.RIGHT


def test_totals_count_a_whole_folder_as_its_files():
    root = _tree()
    totals = L.totals(root, L.decide(root))
    assert totals.files[L.RIGHT] == 2           # a.txt, only-left.txt
    assert totals.folders[L.RIGHT] == 1         # Photos
    assert totals.size[L.RIGHT] == 10 + 5 + 3000
    assert totals.files[L.LEFT] == 2            # b.txt, only-right.txt


def test_requests_keep_newer_only_for_defaults_and_replace_for_choices():
    root = _tree()
    decisions = L.decide(root)
    decisions.set(_node(root, "c.txt"), L.RIGHT)
    made = L.requests(root, decisions, "C:\\Docs", "\\\\nas\\Docs")
    kinds = [(plan.direction, plan.mode) for plan, _r in made]
    assert kinds == [(S.TO_RIGHT, S.UPDATE), (S.TO_RIGHT, S.COPY), (S.TO_LEFT, S.UPDATE)]
    update, picked, back = (request for _plan, request in made)
    assert update["jobs"][0]["conflict"] == "newer"
    assert picked["jobs"][0]["conflict"] == "overwrite"
    assert picked["jobs"][0]["sources"] == ["C:\\Docs\\c.txt"]
    assert sorted(update["jobs"][0]["sources"]) == ["C:\\Docs\\Photos", "C:\\Docs\\a.txt",
                                                    "C:\\Docs\\only-left.txt"]
    assert all(job["kind"] == "copy" for _p, r in made for job in r["jobs"])  # nothing removed
    assert back["target_root"] == "C:\\Docs"


def _wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def test_the_folder_tab_switches_to_the_list_and_sends_in_turn(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.core.config import Config
    from app.ui.window import MainWindow

    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "new.txt").write_text("n")
    (right / "theirs.txt").write_text("t")
    config = Config(path=str(tmp_path / "config.json"))
    window = MainWindow(config, look={"theme": "dark", "accent": "blue", "density": "normal"},
                        look_source="own", custom_frame=False)
    try:
        tab = window.compare(str(left), str(right))
        assert _wait(lambda: tab.folders is not None and tab.folders.session.tree is not None)
        view = tab.folders
        window.run_command("folder-list")
        assert view.layout_name == "list" and config.get("folders.layout") == "list"
        assert window.command_state("cat-lonly").count == 1
        assert not window.command_state("show-diffs").visible
        sent = []
        monkeypatch.setattr(view.session, "send_sync", lambda request: sent.append(request) or True)
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0])
        view.run_list()
        assert len(sent) == 1                    # the right first; the left waits its turn
        assert view._queue and view._queue[0]["target_root"] == str(left)
        window.run_command("folder-trees")
        assert view.layout_name == "trees"
    finally:
        window._may_close = lambda pages: True
        window.close()
