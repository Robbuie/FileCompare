"""The command line, the hand-over, settings, the session and the window.

The window test builds the real window offscreen and runs a real comparison
through the real loader thread. It proves the pieces are wired together; it
does not prove the window behaves under a mouse, which is the user's to check.
"""

import json
import os
import time

import pytest

from app import cli
from app.core import appearance, instance
from app.core.config import Config

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "text")


# ---------------------------------------------------------------------- cli

def test_two_paths():
    request = cli.parse(["C:\\a.txt", "D:\\b.txt"])
    assert request.paths == ["C:\\a.txt", "D:\\b.txt"] and not request.error


def test_relative_paths_resolve_against_the_callers_folder():
    request = cli.parse(["a.txt", "..\\b.txt"], cwd="C:\\Jobs\\110")
    assert request.paths == ["C:\\Jobs\\110\\a.txt", "C:\\Jobs\\b.txt"]


def test_unc_paths_survive():
    request = cli.parse(["\\\\server\\share\\x.txt", "y.txt"], cwd="\\\\server\\share\\old")
    assert request.paths == ["\\\\server\\share\\x.txt", "\\\\server\\share\\old\\y.txt"]


def test_titles_and_readonly():
    request = cli.parse(["a", "b", "--left-title", "Old", "--readonly", "both"])
    assert request.left_title == "Old" and request.readonly == {"left", "right"}


def test_errors_are_reported_not_raised():
    assert cli.parse(["a", "b", "c"]).error
    assert cli.parse(["--merge", "a", "b"]).error
    assert cli.parse(["--mode", "sideways", "a", "b"]).error
    assert not cli.parse(["--merge", "m", "t", "b", "-o", "out"]).error


# ------------------------------------------------------------------ instance

def test_hand_over_message_round_trips():
    data = instance.encode(["a b.txt", "c.txt"], "C:\\Work")
    assert instance.decode(data) == (["a b.txt", "c.txt"], "C:\\Work")


def test_a_garbled_message_is_dropped():
    assert instance.decode(b"not json\n") is None
    assert instance.decode(b'{"argv": [1, 2]}\n') is None


def test_second_instance_hands_over(qt_app):
    """A real second process, as File Manager would start one. A thread in
    this process would be the wrong test: Qt sockets belong to the thread
    that made them, and one made on a plain Python thread crashes Qt later."""
    import subprocess
    import sys

    from PySide6.QtCore import QCoreApplication

    name = f"FileCompare-test-{os.getpid()}"
    listener = instance.Listener(name)
    assert listener.listen()
    got = []
    listener.received.connect(lambda argv, cwd: got.append((argv, cwd)))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; from PySide6.QtCore import QCoreApplication; "
            "app = QCoreApplication([]); from app.core import instance; "
            f"sys.exit(0 if instance.hand_over(['x', 'y'], 'C:\\\\', {name!r}) else 1)")
    child = subprocess.Popen([sys.executable, "-c", code], cwd=root)
    end = time.monotonic() + 10
    while (not got or child.poll() is None) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    listener.close()
    assert child.wait(5) == 0
    assert got == [(["x", "y"], "C:\\")]


# ---------------------------------------------------------- config and look

def test_config_rejects_unknown_keys(tmp_path):
    config = Config(path=str(tmp_path / "c.json"))
    with pytest.raises(KeyError):
        config.get("no.such.key")
    config.set("theme", "paper")
    assert config.save()
    assert Config.load(str(tmp_path / "c.json")).get("theme") == "paper"


def test_a_corrupt_settings_file_is_not_fatal(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ not json")
    assert Config.load(str(path)).get("theme") == "dark"


def test_follows_file_manager_when_it_can(tmp_path):
    theirs = tmp_path / "fm.json"
    theirs.write_text(json.dumps({"theme": "blueprint", "accent": "amber"}))
    config = Config(path=str(tmp_path / "c.json"))
    look, source = appearance.resolve(config, file_manager=appearance.file_manager_look(str(theirs)))
    assert source == "file manager"
    assert look == {"theme": "blueprint", "accent": "amber", "density": "normal"}

    config.set("look.follow_file_manager", False)
    config.set("theme", "light")
    look, source = appearance.resolve(config, probe=False)
    assert source == "own" and look["theme"] == "light"


def test_missing_file_manager_settings_fall_back(tmp_path):
    assert appearance.file_manager_look(str(tmp_path / "absent.json")) is None
    config = Config(path=str(tmp_path / "c.json"))
    look, source = appearance.resolve(config, file_manager=None, probe=False)
    assert source == "own"


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


def make_session(left, right, **options):
    from app.core.loader import Loader
    from app.core.session import Options, Session

    loader = Loader()
    session = Session(loader, left, right, options=Options(**options))
    session._keep_loader = loader
    return session


def test_session_compares_a_pair(qt_app):
    from app.core import session as core

    s = make_session(os.path.join(DATA, "settings.left.ini"),
                     os.path.join(DATA, "settings.right.ini"))
    s.start()
    assert wait_for(lambda: s.kind == core.TEXT)
    assert len(s.result.differences) == 4


def test_a_missing_side_fails_and_the_other_stays(qt_app, tmp_path):
    from app.core import session as core

    s = make_session(os.path.join(DATA, "settings.left.ini"), str(tmp_path / "gone.ini"))
    s.start()
    assert wait_for(lambda: s.kind == core.BROKEN and s.sides[0].state == core.READY)
    assert s.sides[1].state == core.FAILED and s.sides[1].error == "Not found"


def test_a_slow_side_times_out_and_its_late_answer_is_dropped(qt_app, monkeypatch):
    from app.core import session as core

    real = core.open_side

    def slow(path, max_bytes):
        if path.endswith("right.ini"):
            time.sleep(0.6)
        return real(path, max_bytes)

    monkeypatch.setattr(core, "open_side", slow)
    s = make_session(os.path.join(DATA, "settings.left.ini"),
                     os.path.join(DATA, "settings.right.ini"), timeout=0.15)
    s.start()
    assert wait_for(lambda: s.sides[1].state == core.SLOW, 3)
    wait_for(lambda: False, 0.8)     # the late answer arrives, and is ignored
    assert s.sides[1].state == core.SLOW and s.kind == core.BROKEN


def test_rules_rerun_the_diff_without_reading_again(qt_app):
    from app.core import session as core
    from app.core.rules import Rules

    s = make_session(os.path.join(DATA, "endings.crlf.txt"), os.path.join(DATA, "endings.lf.txt"))
    s.start()
    assert wait_for(lambda: s.kind == core.TEXT)
    assert s.result.exact and not s.byte_identical
    s.set_rules(Rules(case=True))
    assert wait_for(lambda: s.result is not None and s.kind == core.TEXT)


def test_two_folders_are_recognised(qt_app, tmp_path):
    from app.core import session as core

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    s = make_session(str(tmp_path / "a"), str(tmp_path / "b"))
    s.start()
    assert wait_for(lambda: s.kind == core.FOLDERS)


# -------------------------------------------------------------------- window

def test_the_window_opens_a_comparison_and_steps_through_it(qt_app, tmp_path):
    from app.core import session as core
    from app.ui.comparetab import CompareTab
    from app.ui.starttab import StartTab
    from app.ui.window import MainWindow

    config = Config(path=str(tmp_path / "c.json"))
    window = MainWindow(config, look={"theme": "dark", "accent": "blue", "density": "normal"},
                        look_source="own", custom_frame=False)
    window.resize(1200, 700)
    window.open_request(cli.parse([os.path.join(DATA, "settings.left.ini"),
                                   os.path.join(DATA, "settings.right.ini")]))
    window.show()
    tab = window.pages.currentWidget()
    assert isinstance(tab, CompareTab)
    assert wait_for(lambda: tab.session.kind == core.TEXT)
    wait_for(lambda: False, 0.1)
    assert tab.count.text() == "Difference 1 of 4"
    tab.view.next_difference()
    assert tab.count.text() == "Difference 2 of 4"
    tab.view.last_difference()
    assert tab.count.text() == "Difference 4 of 4"
    assert window.tabs.tabText(0) == "settings.left.ini  vs  settings.right.ini"

    window.close_page(tab)
    assert isinstance(window.pages.currentWidget(), StartTab)
    window.close()


def test_the_start_page_becomes_the_comparison_in_the_same_tab(qt_app, tmp_path):
    from app.ui.comparetab import CompareTab
    from app.ui.window import MainWindow

    config = Config(path=str(tmp_path / "c.json"))
    window = MainWindow(config, look={}, look_source="own", custom_frame=False)
    window.open_request(cli.parse([]))
    start = window.pages.currentWidget()
    start.set_paths(os.path.join(DATA, "endings.crlf.txt"), os.path.join(DATA, "endings.lf.txt"))
    start.go.click()
    assert window.tabs.count() == 1
    assert isinstance(window.pages.currentWidget(), CompareTab)
    window.close()
