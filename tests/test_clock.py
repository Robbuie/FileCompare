"""Folder compare and the clock (1.8): an hour's shift is a clock change, and
"always compare contents" judges same-size pairs by their bytes."""

import os
import time

from app.core import folders as F
from app.core import syncplan as S
from tests.test_folders import e, find


def test_an_exact_hour_apart_is_a_clock_change_when_asked():
    left = [e("dst.txt", mtime=10_000), e("dst-size.txt", size=5, mtime=10_000),
            e("near.txt", mtime=10_000), e("rounded.txt", mtime=10_000)]
    right = [e("dst.txt", mtime=13_600), e("dst-size.txt", size=6, mtime=13_600),
             e("near.txt", mtime=13_000), e("rounded.txt", mtime=6_401.5)]
    off = F.build(left, right)
    assert find(off, "dst.txt").status == F.NEWER_RIGHT
    on = F.build(left, right, hour=True)
    assert find(on, "dst.txt").status == F.HOUR_APART
    assert find(on, "rounded.txt").status == F.HOUR_APART      # within two seconds
    assert find(on, "dst-size.txt").status == F.NEWER_RIGHT    # sizes differ: an edit
    assert find(on, "near.txt").status == F.NEWER_RIGHT        # ten minutes is not an hour
    assert not find(on, "dst.txt").differs
    assert "an hour apart" in F.summary(on)


def test_an_hour_apart_is_read_by_a_content_compare_and_not_synced():
    root = F.build([e("dst.txt", mtime=10_000)], [e("dst.txt", mtime=13_600)], hour=True)
    node = find(root, "dst.txt")
    assert node in F.content_candidates(root)
    F.settle(node, False)
    assert node.status == F.CONTENT_DIFF
    root = F.build([e("dst.txt", mtime=10_000)], [e("dst.txt", mtime=13_600)], hour=True)
    assert not S.plan(root, S.TO_LEFT, S.UPDATE).of(S.ACT_COPY)
    # Without the switch, the same pair is an update waiting to happen.
    root = F.build([e("dst.txt", mtime=10_000)], [e("dst.txt", mtime=13_600)])
    assert S.plan(root, S.TO_LEFT, S.UPDATE).of(S.ACT_COPY)


def test_always_compare_contents_reads_every_same_size_pair(qt_app, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from app.core.folderdiff import FolderSession
    from app.core.loader import Loader

    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    for name, a, b in (("touched.txt", b"12345", b"12345"), ("edited.txt", b"abcde", b"abcdX"),
                       ("grown.txt", b"abc", b"abcd")):
        (left / name).write_bytes(a)
        (right / name).write_bytes(b)
    # Same moment on both sides: size and time alone would say "same".
    for name in ("edited.txt",):
        os.utime(left / name, (1_000_000, 1_000_000))
        os.utime(right / name, (1_000_000, 1_000_000))
    os.utime(right / "touched.txt", (2_000_000, 2_000_000))

    loader = Loader()
    session = FolderSession(loader, str(left), str(right), by_content=True)
    session.start()
    end = time.monotonic() + 10
    while (session.tree is None or session.busy) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert find(session.tree, "touched.txt").status == F.CONTENT_SAME
    assert find(session.tree, "edited.txt").status == F.CONTENT_DIFF
    assert find(session.tree, "grown.txt").status != F.CONTENT_SAME
    loader.shutdown()
