"""1.12: the folder compare as two mirrored halves, and its icons by kind."""

import os
import time

from PySide6.QtCore import QCoreApplication, Qt

from app.core import folders as F
from app.io import shellicons


def test_icons_are_asked_for_by_kind_never_by_path():
    assert shellicons.key_for("Cell4.L5X", False) == ".l5x"
    assert shellicons.key_for("Line 3", True) == shellicons.FOLDER
    assert shellicons.key_for("README", False) == shellicons.FILE
    assert shellicons.key_for(".gitignore", False) == shellicons.FILE
    assert shellicons.key_for("trailing.", False) == shellicons.FILE
    assert shellicons.key_for("a." + "x" * 20, False) == shellicons.FILE


def test_alpha_comes_from_drawing_over_black_and_white():
    # One opaque red pixel, one half-transparent white one, one empty one.
    black = bytes([0, 0, 255, 0, 128, 128, 128, 0, 0, 0, 0, 0])
    white = bytes([0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255])
    out = shellicons.alpha_from(black, white)
    assert out[0:4] == bytes([0, 0, 255, 255])
    assert out[4:8] == bytes([128, 128, 128, 128])
    assert out[8:12] == bytes([0, 0, 0, 0])


def test_off_windows_there_is_no_shell_icon(monkeypatch):
    monkeypatch.setattr(shellicons.sys, "platform", "linux")
    assert shellicons.pixels(".txt", 16) is None


def test_the_icon_cache_answers_at_once_and_fills_in_later(qt_app):
    from app.ui.fileicons import FileIcons

    asked = []

    def fetch(key, size):
        asked.append(key)
        return bytes([10, 20, 30, 255]) * (size * size) if key == ".txt" else None

    icons = FileIcons(fetch=fetch)
    changed = []
    icons.changed.connect(lambda: changed.append(1))
    first = icons.icon("a.txt", False, "#888888", "#444444")
    icons.icon("b.txt", False, "#888888", "#444444")
    icons.icon("c.xyz", False, "#888888", "#444444")
    assert not first.isNull()          # the drawn stand-in, straight away
    icons.flush()
    end = time.monotonic() + 5
    while not changed and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert changed
    assert sorted(asked) == [".txt", ".xyz"]   # one request per kind
    assert icons.icon("d.txt", False, "#888888", "#444444") is not first
    icons.icon("e.xyz", False, "#888888", "#444444")
    icons.flush()
    assert sorted(asked) == [".txt", ".xyz"]   # a kind with no icon is not asked twice


def _folder_tab(qt_app, tmp_path):
    from app import cli
    from app.core.config import Config
    from app.ui.window import MainWindow

    left, right = tmp_path / "L", tmp_path / "R"
    (left / "sub").mkdir(parents=True)
    (right / "extra").mkdir(parents=True)
    (left / "both.txt").write_bytes(b"one\n")
    (right / "both.txt").write_bytes(b"one\n")
    os.utime(left / "both.txt", (5_000_000, 5_000_000))
    os.utime(right / "both.txt", (5_000_000, 5_000_000))
    (left / "sub" / "gone.txt").write_bytes(b"x\n")
    (right / "extra" / "new.txt").write_bytes(b"y\n")

    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    window.resize(1400, 700)
    window.open_request(cli.parse([str(left), str(right)]))
    window.show()
    tab = window.pages.currentWidget()
    end = time.monotonic() + 10
    while not (tab.folders is not None and tab.folders.session.tree is not None) \
            and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return window, tab


def test_each_side_has_its_own_names_and_only_its_side_is_washed(qt_app, tmp_path):
    from app.ui import folderview as V

    window, tab = _folder_tab(qt_app, tmp_path)
    model = tab.folders.model
    assert model.columnCount() == 7
    rows = {model.node(model.index(r, 0)).name: r for r in range(model.rowCount())}

    gone = model.index(rows["sub"], 0)
    node = model.node(gone)
    assert node.status == F.ONLY_LEFT
    assert model.data(model.index(rows["sub"], V.LNAME)) == "sub"
    assert model.data(model.index(rows["sub"], V.RNAME)) == ""
    assert model.data(model.index(rows["sub"], V.LSIZE), Qt.BackgroundRole) is not None
    assert model.data(model.index(rows["sub"], V.RSIZE), Qt.BackgroundRole) is None
    assert model.data(model.index(rows["sub"], V.LNAME), Qt.DecorationRole) is not None
    assert model.data(model.index(rows["sub"], V.RNAME), Qt.DecorationRole) is None

    extra = rows["extra"]
    assert model.data(model.index(extra, V.LNAME)) == ""
    assert model.data(model.index(extra, V.RNAME)) == "extra"
    assert model.data(model.index(extra, V.LTIME), Qt.BackgroundRole) is None

    # A child is indented one level on the right as on the left.
    child = model.index(0, 0, model.index(extra, 0))
    assert model.depth(model.node(child)) == 1

    # The right-hand chevron toggles the same row the left arrow does.
    tab.folders.tree.collapseAll()
    first = model.index(extra, V.LNAME)
    assert not tab.folders.tree.isExpanded(first)

    # Both halves the same width, the verdict between them, and the headers
    # over their own halves.
    header = tab.folders.tree.header()
    assert header.sectionSize(V.LNAME) == header.sectionSize(V.RNAME)
    assert header.sectionSize(V.LTIME) == header.sectionSize(V.RTIME)
    left = sum(header.sectionSize(c) for c in V.LEFT_COLUMNS)
    assert abs(tab.heads[0].width() - left) <= 2
    assert tab._head_spacer.width() == header.sectionSize(V.VERDICT)

    tab.folders.tree.viewport().grab()        # every delegate paints without raising
    window._may_close = lambda pages: True
    window.close()
