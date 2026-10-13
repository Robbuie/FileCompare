"""1.22: a side that cannot be saved says so when it is read, not at Ctrl+S,
and a refused save says which refusal it was."""

import os
import stat

from app.io import load, save


def test_a_read_only_file_is_found_when_it_is_read(tmp_path):
    path = tmp_path / "locked.txt"
    path.write_bytes(b"one\r\n")
    os.chmod(path, stat.S_IREAD)
    try:
        out = load.load(str(path))
        assert out.ok and out.unwritable == "The file is read-only"
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_a_writable_file_is_not_touched_by_the_check(tmp_path):
    path = tmp_path / "free.txt"
    path.write_bytes(b"one\r\n")
    os.utime(path, (1_000_000, 1_000_000))
    out = load.load(str(path))
    assert out.ok and out.unwritable == ""
    assert path.read_bytes() == b"one\r\n"
    assert os.stat(path).st_mtime == 1_000_000      # opened for writing, not written


def _winerror(code: int, cls=PermissionError) -> OSError:
    exc = cls(13, "Access is denied")
    exc.winerror = code
    return exc


def test_windows_refusals_are_told_apart():
    assert load.refused(_winerror(32)) == "The file is open in another program"
    assert load.refused(_winerror(33)) == "The file is open in another program"
    assert load.refused(_winerror(5)).startswith("Access is denied")
    assert load.refused(OSError(5, "Something else")) == ""


def test_a_refused_rename_names_the_reason(tmp_path, monkeypatch):
    path = tmp_path / "held.txt"
    path.write_bytes(b"old")

    def held(src, dst):
        raise _winerror(32)

    monkeypatch.setattr(save.os, "replace", held)
    out = save.save(str(path), b"new")
    assert not out.ok and out.error == "The file is open in another program"
    assert path.read_bytes() == b"old"
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".fcsave")]


def test_a_folder_that_takes_no_new_files_is_named(tmp_path, monkeypatch):
    path = tmp_path / "f.txt"
    path.write_bytes(b"old")

    def denied(*args, **kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(save.tempfile, "mkstemp", denied)
    out = save.save(str(path), b"new")
    assert not out.ok and "create files in this folder" in out.error
