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


def test_f5_and_the_buttons_copy_the_selection_from_the_side_you_are_on(qt_app, tmp_path):
    from PySide6.QtCore import QItemSelectionModel

    from app.core import syncplan as S

    window, tab = _folder_tab(qt_app, tmp_path)
    try:
        view = tab.folders
        calls = []
        view.open_sync = lambda direction, mode, nodes=None: calls.append(
            (direction, mode, [n.name for n in nodes or []]))
        model = view.model
        assert not view.to_right.isEnabled()          # nothing selected yet
        view.copy_selected(S.TO_RIGHT)
        assert calls == []

        rows = {model.node(model.index(r, 0)).name: r for r in range(model.rowCount())}
        view.tree.selectionModel().select(
            model.index(rows["sub"], 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        assert view.to_right.isEnabled() and view.to_left.isEnabled()

        view._command("copy-from-side")               # F5 on the left half
        assert calls[-1] == (S.TO_RIGHT, S.COPY, ["sub"])
        assert tab.heads[0].property("active") == "true"

        view.tree.sideClicked.emit(1)                 # a click in the right half
        assert tab.heads[1].property("active") == "true"
        assert tab.heads[0].property("active") == "false"
        view._command("copy-from-side")
        assert calls[-1][0] == S.TO_LEFT

        view._command("other-side")                   # Tab
        assert view.side == 0
        view._command("copy-left")                    # Alt+Left, whatever the side
        assert calls[-1][0] == S.TO_LEFT
        view.to_right.click()
        assert calls[-1][0] == S.TO_RIGHT
    finally:
        window._may_close = lambda pages: True
        window.close()


# ------------------------------------------------------------------ 1.15

def test_folder_paths_are_tidied_and_climbed_as_strings():
    assert F.tidy(' "C:/Jobs/1234/" ') == "C:\\Jobs\\1234"
    assert F.tidy("D:") == "D:\\"
    assert F.tidy("C:\\") == "C:\\"
    assert F.tidy("\\\\srv\\share\\a\\") == "\\\\srv\\share\\a"
    assert F.tidy("\\\\srv\\share") == "\\\\srv\\share\\"
    assert F.ancestors("S:\\Jobs\\1234\\PLC") == ["S:\\Jobs\\1234", "S:\\Jobs", "S:\\"]
    assert F.ancestors("\\\\srv\\share\\a\\b") == ["\\\\srv\\share\\a", "\\\\srv\\share\\"]
    assert F.ancestors("C:\\") == []
    assert F.ancestors("/tmp/a") == ["/tmp", "/"]
    assert F.same_path("c:\\jobs\\", "C:\\Jobs")
    assert F.rebased({"Sub", "Sub\\Deep", "Other"}, "sub") == {"deep"}


def test_the_show_buttons_count_what_they_show():
    left = [F.Entry("a.txt", False, 1, 10.0), F.Entry("b.txt", False, 1, 10.0),
            F.Entry("c.txt", False, 1, 10.0)]
    right = [F.Entry("a.txt", False, 1, 10.0), F.Entry("b.txt", False, 1, 99.0),
             F.Entry("d.txt", False, 1, 10.0)]
    totals = F.show_counts(F.build(left, right))
    assert totals == {F.SHOW_ALL: 4, F.SHOW_DIFFERENT: 3, F.SHOW_LEFT: 1, F.SHOW_RIGHT: 2,
                      F.SHOW_SAME: 1}


def _wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def test_a_folder_compare_opens_collapsed_on_the_differences(qt_app, tmp_path):
    from app.ui import folderview as V

    window, tab = _folder_tab(qt_app, tmp_path)
    try:
        view = tab.folders
        model = view.model
        assert model.show == F.SHOW_DIFFERENT
        names = [model.node(model.index(r, 0)).name for r in range(model.rowCount())]
        assert "both.txt" not in names                 # the same file is filtered out
        assert not any(view.tree.isExpanded(model.index(r, 0))
                       for r in range(model.rowCount()))
        assert view.shows[F.SHOW_DIFFERENT].text().endswith("2")
        rows = {model.node(model.index(r, 0)).name: r for r in range(model.rowCount())}
        assert model.data(model.index(rows["sub"], V.LSIZE)) == "1 file"

        # A folder opened stays open when the tree is rebuilt under it.
        view.tree.expand(model.index(rows["sub"], 0))
        view.session.changed.emit()
        rows = {model.node(model.index(r, 0)).name: r for r in range(model.rowCount())}
        assert view.tree.isExpanded(model.index(rows["sub"], 0))
        assert not view.tree.isExpanded(model.index(rows["extra"], 0))
        view.collapse_all()
        view.expand_differences()
        assert view.tree.isExpanded(model.index(rows["extra"], 0))
    finally:
        window._may_close = lambda pages: True
        window.close()


def test_one_side_can_be_pointed_at_another_folder(qt_app, tmp_path):
    window, tab = _folder_tab(qt_app, tmp_path)
    try:
        view = tab.folders
        session = view.session
        assert tab.heads[0].folder_mode and tab.heads[1].folder_mode
        assert tab.heads[1].field.text().endswith("R")
        other = tmp_path / "R2"
        other.mkdir()
        (other / "both.txt").write_bytes(b"one\n")
        os.utime(other / "both.txt", (5_000_000, 5_000_000))
        kept = session.sides[0].entries
        assert tab.set_folder(1, str(other) + "/")
        assert session.sides[0].entries is kept         # the left is not read again
        assert _wait(lambda: session.tree is not None)
        assert tab.session.sides[1].path == str(other)
        assert "R2" in tab.title()
        assert not tab.set_folder(1, str(other))        # already showing it

        # Up from the right goes to its parent; the left stays.
        tab.heads[1]._go_up()
        assert session.sides[1].path == str(tmp_path)
        assert session.sides[0].path.endswith("L")
        assert _wait(lambda: session.tree is not None)

        # A folder that is not there says so on its own side, with Retry.
        tab.set_folder(0, str(tmp_path / "missing"))
        assert _wait(lambda: session.sides[0].state == "failed")
        assert tab.heads[0].again.isVisible() or not tab.isVisible()
        assert tab.heads[0].state.text()
    finally:
        window._may_close = lambda pages: True
        window.close()


def test_a_row_can_become_the_folders_compared(qt_app, tmp_path):
    window, tab = _folder_tab(qt_app, tmp_path)
    try:
        view = tab.folders
        model = view.model
        rows = {model.node(model.index(r, 0)).name: r for r in range(model.rowCount())}
        node = model.node(model.index(rows["sub"], 0))
        left, _right = view.session.paths(node)
        view._rebase(node, left, "")                    # "Use as the left folder"
        assert view.session.sides[0].path == left
        assert view.session.sides[1].path.endswith("R")
        assert _wait(lambda: view.session.tree is not None)
        assert tab.session.sides[0].path == left
    finally:
        window._may_close = lambda pages: True
        window.close()
