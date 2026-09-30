"""Folder sync (1.0): the plan, the request File Manager reads, the handoff
file, and the preview."""

from __future__ import annotations

import json

import pytest

from app.core import folders as F
from app.core import syncplan as S
from app.core.folders import Entry
from app.io import handoff


def e(rel, size=10, mtime=1000.0, **kw):
    return Entry(rel=rel, is_dir=False, size=size, mtime=mtime, **kw)


def d(rel, **kw):
    return Entry(rel=rel, is_dir=True, **kw)


def find(root, rel):
    for node in root.walk():
        if node.rel.lower() == rel.lower():
            return node
    raise KeyError(rel)


def tree():
    return F.build(
        [e("same.txt"), e("newer.txt", mtime=2000), e("older.txt", mtime=500),
         e("size.txt", size=5), e("left.txt"), d("newdir"), e("newdir\\a.txt", size=3),
         e("newdir\\b.txt", size=4), d("both"), e("both\\in.txt", mtime=3000),
         d("link", is_link=True), d("clash")],
        [e("same.txt"), e("newer.txt"), e("older.txt"), e("size.txt", size=6),
         e("right.txt"), d("olddir"), e("olddir\\x.txt"), d("both"), e("both\\in.txt"),
         e("clash")])


def acts(plan):
    return {(a.act, a.rel, a.why) for a in plan.actions}


def test_update_copies_what_is_new_or_newer_and_leaves_the_rest_saying_why():
    plan = S.plan(tree(), S.TO_RIGHT, S.UPDATE)
    assert acts(plan) == {
        (S.ACT_COPY, "both\\in.txt", S.NEWER),
        (S.ACT_COPY, "left.txt", S.NEW),
        (S.ACT_COPY, "newdir", S.NEW),
        (S.ACT_COPY, "newer.txt", S.NEWER),
        (S.ACT_SKIP, "older.txt", S.TARGET_NEWER),
        (S.ACT_SKIP, "size.txt", S.UNSURE),
        (S.ACT_SKIP, "link", S.LINK),
        (S.ACT_SKIP, "clash", S.CLASH),
    }
    folder = next(a for a in plan.copies if a.rel == "newdir")
    assert folder.is_dir and folder.files == 2 and folder.size == 7
    assert plan.conflict == "newer"
    assert not plan.removals


def test_mirror_also_removes_what_only_the_target_has_whole_folders_once():
    plan = S.plan(tree(), S.TO_RIGHT, S.MIRROR)
    assert {(a.rel, a.is_dir, a.files) for a in plan.removals} == {
        ("olddir", True, 1), ("right.txt", False, 1)}


def test_the_other_direction_reads_the_same_tree_the_other_way():
    plan = S.plan(tree(), S.TO_LEFT, S.MIRROR)
    copies = {a.rel for a in plan.copies}
    assert copies == {"right.txt", "olddir", "older.txt"}
    assert {a.rel for a in plan.removals} == {"left.txt", "newdir"}


def test_a_walk_that_could_not_read_something_never_removes():
    root = F.build([e("a.txt"), d("locked", error="Access is denied")],
                   [e("a.txt"), e("extra.txt"), d("locked")])
    plan = S.plan(root, S.TO_RIGHT, S.MIRROR)
    assert not plan.removals
    assert "not offered" in plan.no_removals
    assert (S.ACT_SKIP, "locked", S.UNREAD) in acts(plan)


def test_a_content_compare_that_found_the_same_bytes_copies_nothing():
    root = F.build([e("t.txt", mtime=2000)], [e("t.txt")])
    F.settle(find(root, "t.txt"), True)
    assert S.plan(root, S.TO_RIGHT, S.UPDATE).empty


def test_picked_rows_replace_whatever_is_there_and_a_folder_means_its_differences():
    root = tree()
    plan = S.plan(root, S.TO_RIGHT, S.COPY,
                  nodes=[find(root, "older.txt"), find(root, "both"),
                         find(root, "both\\in.txt"), find(root, "same.txt"),
                         find(root, "right.txt")])
    assert acts(plan) == {(S.ACT_COPY, "older.txt", S.REPLACE),
                          (S.ACT_COPY, "both\\in.txt", S.REPLACE)}
    assert plan.conflict == "overwrite"


def test_removing_picked_rows_takes_them_from_the_side_the_direction_points_at():
    root = tree()
    picked = [find(root, "left.txt"), find(root, "same.txt"), find(root, "right.txt"),
              find(root, "link")]
    from_left = S.plan(root, S.TO_LEFT, S.REMOVE, nodes=picked)
    assert {(a.act, a.rel) for a in from_left.actions} == {
        (S.ACT_REMOVE, "left.txt"), (S.ACT_REMOVE, "same.txt"), (S.ACT_SKIP, "link")}
    from_right = S.plan(root, S.TO_RIGHT, S.REMOVE, nodes=picked)
    assert {a.rel for a in from_right.removals} == {"same.txt", "right.txt"}


def test_the_request_is_one_copy_job_and_one_recycle_job_in_file_managers_shape():
    plan = S.plan(tree(), S.TO_RIGHT, S.MIRROR)
    got = S.request(plan, plan.actions, "S:\\Jobs", "D:\\Jobs", title="S -> D")
    assert got["version"] == 1 and got["from"] == "File Compare"
    copy, recycle = got["jobs"]
    assert copy["kind"] == "copy" and copy["destination"] == "D:\\Jobs"
    assert copy["conflict"] == "newer"
    pairs = dict(zip(copy["sources"], copy["into"]))
    assert pairs["S:\\Jobs\\both\\in.txt"] == "D:\\Jobs\\both"
    assert pairs["S:\\Jobs\\newdir"] == "D:\\Jobs"
    assert "S:\\Jobs\\older.txt" not in pairs          # left alone is never sent
    assert recycle == {"kind": "recycle",
                       "sources": ["D:\\Jobs\\olddir", "D:\\Jobs\\right.txt"]}


def test_only_ticked_actions_are_sent():
    plan = S.plan(tree(), S.TO_RIGHT, S.UPDATE)
    one = [a for a in plan.copies if a.rel == "left.txt"]
    got = S.request(plan, one, "\\\\srv\\a", "\\\\srv\\b")
    assert got["jobs"] == [{"kind": "copy", "sources": ["\\\\srv\\a\\left.txt"],
                            "destination": "\\\\srv\\b", "into": ["\\\\srv\\b"],
                            "conflict": "newer"}]


@pytest.mark.parametrize("left, right, why", [
    ("C:\\A", "c:\\a\\", "same folder"),
    ("C:\\A", "C:\\A\\B", "inside"),
    ("C:\\A\\B", "C:\\A", "inside"),
    ("", "C:\\A", "Both sides"),
])
def test_one_folder_inside_the_other_is_refused(left, right, why):
    assert why in S.refusal(left, right)
    assert S.refusal("C:\\A", "C:\\AB") == ""


# ------------------------------------------------------------- the handoff

def test_the_request_is_written_and_file_manager_started_with_it(tmp_path, monkeypatch):
    started = []

    class Popen:
        def __init__(self, args, **_kw):
            started.append(args)

    monkeypatch.setattr(handoff.subprocess, "Popen", Popen)
    path, program = handoff.send({"version": 1, "jobs": []}, program="FileManager.exe",
                                 where=str(tmp_path))
    assert program == "FileManager.exe"
    assert started == [["FileManager.exe", "--queue", path]]
    assert json.loads(open(path).read()) == {"version": 1, "jobs": []}
    assert handoff.result(path) is None
    with open(handoff.result_path(path), "w") as out:
        json.dump({"copied": 3}, out)
    assert handoff.result(path) == {"copied": 3}
    assert not (tmp_path / path).exists()          # both files tidied away


def test_without_file_manager_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff.launch, "locate", lambda _c: "")
    with pytest.raises(FileNotFoundError, match="File Manager is not installed"):
        handoff.send({"jobs": []}, where=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_a_unc_path_is_remote():
    assert handoff.drive_is_remote("\\\\server\\share")
    assert not handoff.drive_is_remote("/tmp")


def test_the_outcome_reads_as_one_line():
    from app.core.folderdiff import describe

    line = describe({"copied": 12, "failed": 1, "cancelled": True})
    assert "12 copied" in line and "1 failed" in line and "cancelled" in line


# ------------------------------------------------------------- the preview

def test_the_preview_ticks_every_action_and_sends_only_what_stays_ticked():
    from PySide6.QtCore import Qt

    from app.ui.syncdialog import SyncDialog

    dialog = SyncDialog(tree(), "S:\\Jobs", "D:\\Jobs", mode=S.MIRROR)
    items = [dialog.list.topLevelItem(i) for i in range(dialog.list.topLevelItemCount())]
    ticked = [i for i in items if i.flags() & Qt.ItemIsUserCheckable]
    assert len(ticked) == 6 and all(i.checkState(0) == Qt.Checked for i in ticked)
    assert "removing 2" in dialog.go.text()
    assert "Recycle Bin" in dialog.warning.text()
    dialog.set_remote((False, True))
    assert "permanently" in dialog.warning.text()
    for item in ticked:
        if item.text(0) == "Remove":
            item.setCheckState(0, Qt.Unchecked)
    assert dialog.go.text() == "Send to File Manager"
    dialog._send()  # noqa: SLF001
    assert [job["kind"] for job in dialog.request["jobs"]] == ["copy"]

    dialog.set_direction(S.TO_LEFT)
    assert "D:\\Jobs" in dialog.where.text().splitlines()[0]


def test_the_preview_will_not_send_two_folders_that_are_one():
    from app.ui.syncdialog import SyncDialog

    dialog = SyncDialog(tree(), "C:\\A", "C:\\A\\B")
    assert not dialog.go.isEnabled()
    assert "inside" in dialog.warning.text()
