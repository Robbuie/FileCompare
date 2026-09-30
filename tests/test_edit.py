"""Editing and saving: the document, the writer, and the session between them.

The part of 0.2 that can be proved without a window: that an edit lands on the
right lines with the right endings, that undo puts back exactly what was
there, and that a save writes the bytes it read back unchanged everywhere it
was not asked to change them.
"""

import os
import time

from app.core.diff import align
from app.core.document import Document
from app.io import load as io_load
from app.io import save as io_save


def doc(text: str) -> Document:
    lines, endings = io_load.split(text)
    return Document.from_lines(lines, endings)


# ------------------------------------------------------------------ document

def test_replace_keeps_the_endings_it_replaces():
    d = doc("a\r\nb\nc\r\n")
    d.replace(1, 2, ["B"])
    assert d.text() == "a\r\nB\nc\r\n"


def test_new_lines_take_the_files_own_ending():
    d = doc("a\nb\nc\n")
    d.replace(1, 2, ["x", "y", "z"])
    assert d.text() == "a\nx\ny\nz\nc\n"


def test_a_file_without_a_final_newline_does_not_grow_one():
    d = doc("a\r\nb")
    d.insert(2, ["c"])
    assert d.text() == "a\r\nb\r\nc"
    d.undo()
    assert d.text() == "a\r\nb"


def test_deleting_the_tail_keeps_the_file_ending_as_it_was():
    d = doc("a\nb\nc")
    d.delete(1, 3)
    assert d.text() == "a"
    d.undo()
    assert d.text() == "a\nb\nc"
    d2 = doc("a\nb\nc\n")
    d2.delete(2, 3)
    assert d2.text() == "a\nb\n"


def test_undo_redo_and_dirty():
    d = doc("one\ntwo\n")
    assert not d.dirty
    d.replace(0, 1, ["ONE"])
    assert d.dirty and d.can_undo
    d.undo()
    assert not d.dirty and d.text() == "one\ntwo\n"
    d.redo()
    assert d.dirty
    d.mark_saved()
    assert not d.dirty
    d.undo()
    assert d.dirty


def test_an_edit_that_changes_nothing_is_not_an_undo_step():
    d = doc("x\n")
    assert not d.replace(0, 1, ["x"])
    assert not d.can_undo


def test_a_mixed_file_stays_mixed_outside_the_edit():
    raw = "a\r\nb\nc\r\nd\n"
    d = doc(raw)
    d.replace(1, 2, ["b"])
    assert d.text() == raw and not d.can_undo


# --------------------------------------------------------------------- range

def test_side_range_of_a_block_on_one_side_only():
    result = align.compare(["a", "b", "c"], ["a", "x", "b", "c"])
    block = result.differences[0]
    assert align.side_range(result.rows, block.start, block.end, 1) == (1, 2)
    # Nothing on the left: the place it would go, after "a".
    assert align.side_range(result.rows, block.start, block.end, 0) == (1, 1)


# -------------------------------------------------------------------- saving

def test_encode_round_trips_every_ladder_rung():
    for raw in (b"plain\r\ntext\r\n", "café\n".encode("utf-8"),
                b"\xef\xbb\xbfbom\r\n", "café".encode("cp1252"),
                "﻿wide\r\n".encode("utf-16-le")):
        loaded = io_load.Loaded(path="x")
        io_load.decode_into(loaded, raw)
        again = io_save.encode(loaded.lines, loaded.endings, loaded.encoding, loaded.bom)
        assert again == raw, (raw, loaded.encoding)


def test_text_the_encoding_cannot_hold_is_refused():
    try:
        io_save.encode(["fine", "snow ☃"], ["\r\n", ""], "cp1252", False)
    except UnicodeEncodeError as exc:
        assert "line 2" in exc.reason
    else:
        raise AssertionError("should have refused")


def test_save_writes_beside_then_renames(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"old\r\n")
    info = os.stat(path)
    out = io_save.save(str(path), b"new\r\n", expect_size=info.st_size,
                       expect_mtime=info.st_mtime)
    assert out.ok and path.read_bytes() == b"new\r\n"
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]


def test_save_refuses_a_file_changed_since_it_was_read(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"old\r\n")
    info = os.stat(path)
    path.write_bytes(b"somebody else\r\n")
    out = io_save.save(str(path), b"mine\r\n", expect_size=info.st_size,
                       expect_mtime=info.st_mtime)
    assert not out.ok and out.conflict
    assert path.read_bytes() == b"somebody else\r\n"
    forced = io_save.save(str(path), b"mine\r\n", expect_size=info.st_size,
                          expect_mtime=info.st_mtime, force=True)
    assert forced.ok and path.read_bytes() == b"mine\r\n"


def test_save_refuses_a_read_only_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"old")
    os.chmod(path, 0o444)
    try:
        out = io_save.save(str(path), b"new")
        assert not out.ok and "read-only" in out.error
        assert path.read_bytes() == b"old"
    finally:
        os.chmod(path, 0o644)


def test_backup_is_made_once(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"first")
    assert io_save.save(str(path), b"second", backup=True).ok
    assert io_save.save(str(path), b"third", backup=True).ok
    assert (tmp_path / "a.txt.orig").read_bytes() == b"first"


# ------------------------------------------------------------------- session

def wait_for(predicate, seconds=10.0):
    from PySide6.QtCore import QCoreApplication

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def session_for(tmp_path, left: bytes, right: bytes, **options):
    from app.core.loader import Loader
    from app.core.session import Options, Session

    a, b = tmp_path / "left.txt", tmp_path / "right.txt"
    a.write_bytes(left)
    b.write_bytes(right)
    loader = Loader()
    s = Session(loader, str(a), str(b), options=Options(poll=False, **options))
    s._keep = loader
    s.start()
    from app.core import session as core

    assert wait_for(lambda: s.kind == core.TEXT)
    return s, a, b


def test_copy_a_block_across_and_save_it(qt_app, tmp_path):
    s, a, b = session_for(tmp_path, b"one\r\ntwo\r\nthree\r\n", b"one\nTWO\nthree\n")
    assert len(s.result.differences) == 1
    assert s.copy_block(s.result.blocks.index(s.result.differences[0]), 1)
    assert s.result.identical and s.sides[1].dirty
    saved = []
    s.saved.connect(lambda i, r: saved.append(r))
    assert s.save(1)
    assert wait_for(lambda: saved)
    assert saved[0].ok, saved[0].error
    # The right side keeps its own LF endings; only the line changed.
    assert b.read_bytes() == b"one\ntwo\nthree\n"
    assert not s.sides[1].dirty


def test_copy_an_insertion_across_puts_it_in_the_right_place(qt_app, tmp_path):
    s, a, b = session_for(tmp_path, b"a\nb\nc\n", b"a\nnew\nb\nc\n")
    index = s.result.blocks.index(s.result.differences[0])
    assert s.copy_block(index, 0)
    assert s.sides[0].lines == ["a", "new", "b", "c"]
    assert s.undo(0)
    assert s.sides[0].lines == ["a", "b", "c"] and not s.sides[0].dirty


def test_a_save_over_a_changed_file_is_a_conflict(qt_app, tmp_path):
    s, a, b = session_for(tmp_path, b"x\n", b"y\n")
    s.replace_lines(0, 0, 1, ["z"])
    time.sleep(0.02)
    a.write_bytes(b"somebody else wrote this\n")
    saved = []
    s.saved.connect(lambda i, r: saved.append(r))
    s.save(0)
    assert wait_for(lambda: saved)
    assert saved[0].conflict and a.read_bytes() == b"somebody else wrote this\n"
    assert s.sides[0].dirty


def test_readonly_sides_are_not_edited(qt_app, tmp_path):
    from app.core.loader import Loader
    from app.core.session import Options, Session
    from app.core import session as core

    a, b = tmp_path / "l.txt", tmp_path / "r.txt"
    a.write_bytes(b"1\n")
    b.write_bytes(b"2\n")
    loader = Loader()
    s = Session(loader, str(a), str(b), options=Options(poll=False), readonly={"left"})
    s.start()
    assert wait_for(lambda: s.kind == core.TEXT)
    assert not s.replace_lines(0, 0, 1, ["x"])
    assert s.copy_all(1) and s.sides[1].lines == ["1"]


def test_line_endings_convert_as_an_undoable_edit(qt_app, tmp_path):
    s, a, b = session_for(tmp_path, b"a\r\nb\r\n", b"a\nb\n")
    assert s.set_line_endings(0, "LF")
    assert s.sides[0].doc.text() == "a\nb\n"
    s.undo(0)
    assert s.sides[0].doc.text() == "a\r\nb\r\n"


def test_the_poll_notices_a_change_on_disk(qt_app, tmp_path):
    s, a, b = session_for(tmp_path, b"x\n", b"y\n")
    time.sleep(0.02)
    b.write_bytes(b"changed underneath\n")
    s._look_at_disk()
    assert wait_for(lambda: s.sides[1].stale)


# -------------------------------------------------------------------- window

def test_the_tab_copies_edits_finds_and_saves(qt_app, tmp_path):
    from app import cli
    from app.core import session as core
    from app.core.config import Config
    from app.ui.window import MainWindow

    a, b = tmp_path / "a.ini", tmp_path / "b.ini"
    a.write_bytes(b"[x]\r\nkey=1\r\nsame=yes\r\n")
    b.write_bytes(b"[x]\r\nkey=2\r\nsame=yes\r\n")
    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    window.resize(1000, 600)
    window.open_request(cli.parse([str(a), str(b)]))
    window.show()
    tab = window.pages.currentWidget()
    assert wait_for(lambda: tab.session.kind == core.TEXT)
    wait_for(lambda: False, 0.05)

    tab._command("copy-left")
    assert tab.session.sides[0].lines[1] == "key=2"
    assert tab.title().startswith("* ")
    assert tab.count.text() == "Same text" or "Identical" in tab.count.text()

    tab._command("undo")
    tab.view.select_rows(1, 1, 2)
    tab._edited(1, 1, 2, "key=3\nadded=1")
    assert tab.session.sides[1].lines == ["[x]", "key=3", "added=1", "same=yes"]

    tab.open_find()
    tab.find.field.setText("same")
    assert tab.find.count.text() == "2 matches"
    tab._find_step(1)
    assert tab.find.count.text().endswith("of 2")

    tab._command("save-all")
    assert wait_for(lambda: not tab.session.dirty)
    assert b.read_bytes() == b"[x]\r\nkey=3\r\nadded=1\r\nsame=yes\r\n"
    assert a.read_bytes() == b"[x]\r\nkey=1\r\nsame=yes\r\n"
    window.close()
