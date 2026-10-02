"""Zip contents in folder compare (1.9): members listed under their zip,
judged by size and CRC, never counted, synced or read as files on disk."""

import os
import time
import zipfile

from app.core import folders as F
from app.core import syncplan as S
from app.io import archive, walk
from tests.test_folders import find


def make_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 1, 12, 0, 0))
            z.writestr(info, data)


def two_sides(tmp_path, left_files, right_files):
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    make_zip(left / "backup.zip", left_files)
    make_zip(right / "backup.zip", right_files)
    return left, right


def test_members_are_listed_under_the_zip_with_their_folders(tmp_path):
    make_zip(tmp_path / "a.zip", {"prog/main.st": "x := 1;", "readme.txt": "hi",
                                  "../escape.txt": "no", "C:/abs.txt": "no"})
    entries = walk.walk(str(tmp_path), archives=True)
    rels = {e.rel for e in entries}
    assert {"a.zip", "a.zip\\prog", "a.zip\\prog\\main.st", "a.zip\\readme.txt"} <= rels
    assert not any("escape" in r or "abs" in r for r in rels)
    assert all(e.archive == "a.zip" for e in entries if e.rel.startswith("a.zip\\"))
    assert {e.rel for e in walk.walk(str(tmp_path))} == {"a.zip"}


def test_members_are_judged_by_crc_and_not_counted(tmp_path):
    left, right = two_sides(tmp_path, {"same.txt": "abc", "changed.txt": "one",
                                       "gone.txt": "x"},
                            {"same.txt": "abc", "changed.txt": "two", "new.txt": "y"})
    root = F.build(walk.walk(str(left), archives=True), walk.walk(str(right), archives=True))
    zip_node = find(root, "backup.zip")
    assert not zip_node.member and zip_node.children
    assert find(root, "backup.zip\\same.txt").status == F.SAME
    assert find(root, "backup.zip\\changed.txt").status == F.CONTENT_DIFF
    assert find(root, "backup.zip\\gone.txt").status == F.ONLY_LEFT
    assert find(root, "backup.zip\\new.txt").status == F.ONLY_RIGHT
    # The folder holds one file, the zip, whatever is inside it.
    assert sum(F.counts(root).values()) == 1
    assert root.files == 1
    assert not [n for n in F.content_candidates(root, all_pairs=True) if n.member]


def test_a_member_is_never_synced_the_zip_is(tmp_path):
    left, right = two_sides(tmp_path, {"a.txt": "one"}, {"a.txt": "two"})
    os.utime(left / "backup.zip", (2_000_000_000, 2_000_000_000))
    root = F.build(walk.walk(str(left), archives=True), walk.walk(str(right), archives=True))
    plan = S.plan(root, S.TO_RIGHT, S.COPY, nodes=[find(root, "backup.zip\\a.txt")])
    assert not plan.of(S.ACT_COPY) and plan.of(S.ACT_SKIP)[0].why == S.INSIDE_ZIP
    plan = S.plan(root, S.TO_RIGHT, S.UPDATE)
    assert [a.rel for a in plan.of(S.ACT_COPY)] == ["backup.zip"]


def test_a_broken_zip_is_just_a_file(tmp_path):
    (tmp_path / "bad.zip").write_bytes(b"not a zip at all")
    assert [e.rel for e in walk.walk(str(tmp_path), archives=True)] == ["bad.zip"]


def test_a_masked_zip_takes_its_members_with_it(tmp_path):
    make_zip(tmp_path / "a.zip", {"x.txt": "1"})
    (tmp_path / "keep.txt").write_text("k")
    entries = walk.walk(str(tmp_path), archives=True)
    root = F.build(entries, entries, mask=F.Mask.parse("-*.zip"))
    assert [n.rel for n in root.walk()] == ["keep.txt"]
    assert root.masked == (False, False)


def test_extract_pair(tmp_path):
    make_zip(tmp_path / "a.zip", {"dir/same name.txt": "left"})
    make_zip(tmp_path / "b.zip", {"dir/same name.txt": "right"})
    left, right = archive.extract_pair((str(tmp_path / "a.zip"), "dir\\same name.txt"),
                                       (str(tmp_path / "b.zip"), "dir\\same name.txt"))
    assert open(left).read() == "left" and open(right).read() == "right"
    assert os.path.basename(left) == "same name.txt"
    assert archive.extract_pair(None, (str(tmp_path / "b.zip"), "dir\\same name.txt"))[0] == ""


def test_the_session_opens_a_member_pair(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app.core.folderdiff import FolderSession
    from app.core.loader import Loader

    left, right = two_sides(tmp_path, {"a.txt": "one"}, {"a.txt": "two"})
    loader = Loader()
    session = FolderSession(loader, str(left), str(right))
    got = []
    session.extracted.connect(lambda l, r, t: got.append((l, r, t)))
    session.start()
    end = time.monotonic() + 10
    while (session.tree is None or session.busy) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert session.open_member(find(session.tree, "backup.zip\\a.txt"))
    end = time.monotonic() + 10
    while not got and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    l, r, titles = got[0]
    assert open(l).read() == "one" and open(r).read() == "two"
    assert titles == ("backup.zip\\a.txt", "backup.zip\\a.txt")
    session.set_archives(False)
    end = time.monotonic() + 10
    while (session.tree is None or session.busy) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not find(session.tree, "backup.zip").children
    loader.shutdown()
