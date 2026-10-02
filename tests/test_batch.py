"""The report without the window (1.11)."""

import os
import zipfile

from app import batch, cli
from app.core import savedsession
from app.core.config import Config
from app.core.rules import Rules
from app.core.savedsession import Saved
from tests.test_app import DATA

L5K = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "l5k")


def run(tmp_path, *args):
    config = Config(path=str(tmp_path / "settings.json"))
    request = cli.parse(list(args), str(tmp_path))
    return batch.run(request, config)


def test_two_files_that_differ(tmp_path):
    out = tmp_path / "r.html"
    code = run(tmp_path, os.path.join(DATA, "settings.left.ini"),
               os.path.join(DATA, "settings.right.ini"), "--report", str(out))
    assert code == batch.DIFFERENT
    page = out.read_text(encoding="utf-8")
    assert "<table>" in page and "settings.left.ini" in page


def test_the_same_file_is_the_same_and_a_patch_is_a_patch(tmp_path):
    same = os.path.join(DATA, "settings.left.ini")
    assert run(tmp_path, same, same, "--report", "r.html") == batch.SAME
    assert run(tmp_path, os.path.join(DATA, "settings.left.ini"),
               os.path.join(DATA, "settings.right.ini"), "--report", "r.patch") == 1
    assert (tmp_path / "r.patch").read_text().startswith("---")


def test_an_l5k_pair_is_compared_by_structure(tmp_path):
    run(tmp_path, os.path.join(L5K, "left.L5K"), os.path.join(L5K, "right.L5K"),
        "--report", "r.html")
    page = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Logix structure" in page and "Exported" not in page


def test_folders_with_a_zip(tmp_path):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "same.txt").write_text("x")
    (right / "same.txt").write_text("x")
    (left / "gone.txt").write_text("x")
    for root, data in ((left, "one"), (right, "two")):
        with zipfile.ZipFile(root / "b.zip", "w") as z:
            z.writestr("in.txt", data)
    os.utime(right / "same.txt", (1_000_000, 1_000_000))   # time only: read, same
    code = run(tmp_path, str(left), str(right), "--report", "f.html")
    page = (tmp_path / "f.html").read_text(encoding="utf-8")
    assert code == batch.DIFFERENT
    assert "gone.txt" in page and "b.zip\\in.txt" in page and "(inside the zip)" in page
    assert "same.txt" not in page.split("<table")[1]


def test_identical_folders(tmp_path):
    for side in ("L", "R"):
        (tmp_path / side).mkdir()
        (tmp_path / side / "a.txt").write_text("a")
        os.utime(tmp_path / side / "a.txt", (1_000_000, 1_000_000))
    assert run(tmp_path, str(tmp_path / "L"), str(tmp_path / "R"), "--report", "f.html") == 0


def test_a_session_file_supplies_paths_and_rules(tmp_path):
    left, right = tmp_path / "a.txt", tmp_path / "b.txt"
    left.write_text("Hello\n")
    right.write_text("hello\n")
    session = tmp_path / "s.fcsession"
    session.write_text(savedsession.dumps(Saved(left=str(left), right=str(right),
                                                rules=Rules(case=True))))
    assert run(tmp_path, str(session), "--report", "r.html") == batch.SAME
    assert run(tmp_path, str(left), str(right), "--report", "r.html") == batch.DIFFERENT


def test_failures_exit_2_and_say_why_in_the_report(tmp_path):
    assert run(tmp_path, str(tmp_path / "nope.txt"), os.path.join(DATA, "settings.left.ini"),
               "--report", "r.html") == batch.FAILED
    assert "Not found" in (tmp_path / "r.html").read_text(encoding="utf-8")
    assert run(tmp_path, str(tmp_path), os.path.join(DATA, "settings.left.ini"),
               "--report", "r.html") == batch.FAILED
    assert run(tmp_path, "only-one.txt", "--report", "r.html") == batch.FAILED
    assert "two paths" in (tmp_path / "r.html").read_text(encoding="utf-8")


def test_the_command_line_takes_report():
    request = cli.parse(["a", "b", "--report", "out.html"], "C:\\work")
    assert request.report == "C:\\work\\out.html" and not request.error


def test_the_report_path_never_imports_qt(tmp_path):
    import subprocess
    import sys

    left = os.path.join(DATA, "settings.left.ini")
    right = os.path.join(DATA, "settings.right.ini")
    out = str(tmp_path / "r.html")
    code = ("import sys; from app import batch, cli; from app.core.config import Config; "
            f"batch.run(cli.parse([{left!r}, {right!r}, '--report', {out!r}]), "
            f"Config(path={str(tmp_path / 'c.json')!r})); "
            "assert not any(m.startswith('PySide6') for m in sys.modules), "
            "[m for m in sys.modules if m.startswith('PySide6')]")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([sys.executable, "-c", code], cwd=root, check=True)
