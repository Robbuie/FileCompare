"""Reads on shares in worker processes (1.4): real processes, a real hang,
a real kill. `volume.FORCE_REMOTE` sends local paths through the pool, which
is the only way to have one off a network."""

from __future__ import annotations

import os
import time

import pytest
from PySide6.QtWidgets import QApplication

from app.core.loader import Loader
from app.io import pool as io_pool
from app.io import volume
from app.io import walk as io_walk
from app.io.read import open_side


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(volume, "FORCE_REMOTE", True)
    loader = Loader()
    answers: dict[int, object] = {}
    loader.finished.connect(lambda request, envelope: answers.__setitem__(request, envelope))
    yield loader, answers
    loader.shutdown()


def wait(answers, request, seconds=20.0):
    end = time.monotonic() + seconds
    while request not in answers and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    return answers.get(request)


def test_volume_keys():
    assert volume.key("\\\\Server\\Share\\a.txt") == "\\\\server"
    assert volume.key("\\\\?\\UNC\\srv\\s\\a") == "\\\\srv"
    assert volume.key("") == volume.LOCAL


def test_a_read_on_a_share_runs_in_a_worker_and_comes_back(remote, tmp_path):
    loader, answers = remote
    path = tmp_path / "a.txt"
    path.write_text("one\ntwo\n")
    request = loader.submit_io(str(path), open_side, str(path), 1 << 20, "")
    envelope = wait(answers, request)
    assert envelope is not None and envelope.ok
    kind, loaded = envelope.value
    assert loaded.lines == ["one", "two"]
    assert loader._processes is not None and loader._processes.keys() == ["test"]  # noqa: SLF001


def test_a_walk_reports_progress_from_the_worker(remote, tmp_path):
    loader, answers = remote
    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("x")
    progress = io_walk.Progress()
    request = loader.submit_io(str(tmp_path), io_walk.walk, str(tmp_path), progress=progress)
    envelope = wait(answers, request)
    assert envelope.ok and len(envelope.value) == 30
    assert progress.done


def test_a_read_that_hangs_is_killed_and_the_next_one_gets_a_new_worker(remote, tmp_path):
    loader, answers = remote
    hung = loader.submit_io(str(tmp_path), time.sleep, 60)
    time.sleep(1.0)                                     # the worker is up and stuck
    first = loader._processes._workers["test"].process  # noqa: SLF001
    assert first.is_alive()
    assert loader.abandon(hung)
    envelope = wait(answers, hung, 5)
    assert envelope is not None and not envelope.ok and "stopped answering" in envelope.error
    first.join(5)
    assert not first.is_alive()
    path = tmp_path / "b.txt"
    path.write_text("after\n")
    again = loader.submit_io(str(path), open_side, str(path), 1 << 20, "")
    assert wait(answers, again).value[1].lines == ["after"]


def test_a_cancel_reaches_a_walk_in_the_worker(remote, tmp_path):
    loader, answers = remote
    progress = io_walk.Progress()
    progress.cancel.set()                     # cancelled before it could finish
    request = loader.submit_io(str(tmp_path), io_walk.walk, str(tmp_path), progress=progress)
    envelope = wait(answers, request)
    assert envelope is not None                # answered either way, never left waiting


def test_a_local_read_stays_on_a_thread(tmp_path):
    loader = Loader()
    answers = {}
    loader.finished.connect(lambda r, e: answers.__setitem__(r, e))
    path = tmp_path / "c.txt"
    path.write_text("x\n")
    request = loader.submit_io(str(path), open_side, str(path), 1 << 20, "")
    assert wait(answers, request).ok
    assert loader._processes is None           # noqa: SLF001 - no process was started
    loader.shutdown()


def test_abandoning_a_thread_read_is_a_no_op():
    loader = Loader()
    assert loader.abandon(12345) is False
    loader.shutdown()


def test_a_worker_that_dies_answers_what_it_held(tmp_path, monkeypatch):
    monkeypatch.setattr(volume, "FORCE_REMOTE", True)
    got = []
    pool = io_pool.Pool(lambda r, ok, v, e: got.append((r, ok, e)), lambda r, c: None)
    pool.submit("test", 7, time.sleep, (60,), {})
    time.sleep(1.0)
    pool._workers["test"].process.kill()       # noqa: SLF001 - a crash, not a kill by us
    end = time.monotonic() + 5
    while not got and time.monotonic() < end:
        time.sleep(0.05)
    assert got and got[0][0] == 7 and not got[0][1]
    pool.shutdown()
