"""Renaming a side's file (1.23)."""

from app.io import save as io_save


def test_a_rename_moves_the_file_and_never_onto_another(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("x")
    (tmp_path / "taken.txt").write_text("keep")
    refused = io_save.rename(str(a), "taken.txt")
    assert not refused.ok and "already there" in refused.error
    assert (tmp_path / "taken.txt").read_text() == "keep"
    done = io_save.rename(str(a), "b.txt")
    assert done.ok and done.path == str(tmp_path / "b.txt")
    assert (tmp_path / "b.txt").read_text() == "x" and not a.exists()


def test_names_windows_refuses_are_refused_before_the_disk():
    for bad in ("", "a/b", "a:b", "x.", "CON.txt", 'q"'):
        assert io_save.name_problem(bad)
    assert io_save.name_problem("report v2.txt") == ""
