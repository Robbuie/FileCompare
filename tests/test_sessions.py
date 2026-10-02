"""Saved sessions (1.10): a comparison's setup written to a file and opened
again as the same comparison."""

import json
import os

import pytest

from app import cli
from app.core import savedsession
from app.core.config import Config
from app.core.rules import Rules
from app.core.savedsession import Saved
from tests.test_app import DATA, wait_for


def test_round_trip_keeps_what_a_person_set():
    saved = Saved(left="C:\\a\\x.L5K", right="\\\\srv\\share\\x.L5K", titles=("Office", "Plant"),
                  readonly=("right",), mode="text",
                  rules=Rules(whitespace="all", case=True, patterns=("ExportDate=.*",),
                              markers=("//",)),
                  intraline="word", structure=False, pins=[(3, 9), (10, 20)],
                  folder_mask="*.L5K;-old", folder_show="different", folder_hour=False,
                  folder_by_content=True, folder_archives=False)
    text = savedsession.dumps(saved)
    data = json.loads(text)
    assert data["format"] == savedsession.FORMAT and "markers" not in data["rules"]
    back = savedsession.loads(text)
    assert back.left == saved.left and back.right == saved.right
    assert back.titles == ("Office", "Plant") and back.readonly == ("right",)
    assert back.rules.whitespace == "all" and back.rules.case
    assert back.rules.patterns == ("ExportDate=.*",) and back.rules.markers == ()
    assert back.intraline == "word" and back.structure is False and back.mode == "text"
    assert back.pins == [(3, 9), (10, 20)]
    assert (back.folder_mask, back.folder_show, back.folder_hour, back.folder_by_content,
            back.folder_archives) == ("*.L5K;-old", "different", False, True, False)


def test_a_text_session_has_no_folder_settings():
    text = savedsession.dumps(Saved(left="a", right="b"))
    assert "folder" not in json.loads(text)
    assert savedsession.loads(text).folder_mask is None


@pytest.mark.parametrize("text, says", [
    ("not json", "not a session file"),
    ('{"format": "something else"}', "not a File Compare session"),
    ('{"format": "File Compare session", "version": 99, "left": "a"}', "newer"),
    ('{"format": "File Compare session", "version": 1}', "nothing to compare"),
])
def test_bad_files_say_why(text, says):
    with pytest.raises(ValueError, match=says):
        savedsession.loads(text)


def test_odd_values_are_tidied_not_trusted():
    text = json.dumps({"format": savedsession.FORMAT, "version": 1, "left": "a", "right": "b",
                       "rules": {"whitespace": "sideways", "patterns": ["", "x"]},
                       "pins": [[1, 2], [-1, 3], "x", [4]], "readonly": ["left", "up"],
                       "intraline": "pixels", "unknown": 5})
    saved = savedsession.loads(text)
    assert saved.rules.whitespace == "none" and saved.rules.patterns == ("x",)
    assert saved.pins == [(1, 2)] and saved.readonly == ("left",) and saved.intraline == "char"


def test_the_window_opens_a_session_file_as_it_was_saved(qt_app, tmp_path):
    from app.core import session as core
    from app.ui.comparetab import CompareTab
    from app.ui.window import MainWindow

    path = tmp_path / "pair.fcsession"
    path.write_text(savedsession.dumps(Saved(
        left=os.path.join(DATA, "settings.left.ini"), right=os.path.join(DATA, "settings.right.ini"),
        titles=("Office", "Plant"), rules=Rules(whitespace="all", case=True), pins=[(3, 8)])))
    config = Config(path=str(tmp_path / "c.json"))
    window = MainWindow(config, look={}, look_source="own", custom_frame=False)
    window.open_request(cli.parse([str(path)]))
    assert wait_for(lambda: isinstance(window.pages.currentWidget(), CompareTab))
    tab = window.pages.currentWidget()
    assert wait_for(lambda: tab.session.kind == core.TEXT and tab.session.result is not None)
    s = tab.session
    assert s.sides[0].title == "Office" and s.rules.whitespace == "all" and s.rules.case
    assert s.pins == [(3, 8)] and any(r[0] == 3 and r[1] == 8 for r in s.result.rows)
    assert tab.session_file == str(path)
    # And back out again, the same.
    again = tab.saved_session()
    assert again.pins == [(3, 8)] and again.titles == ("Office", "Plant")
    assert again.rules.whitespace == "all"
    window.close()


def test_a_broken_session_file_is_reported(qt_app, tmp_path):
    from app.ui.window import MainWindow

    path = tmp_path / "bad.fcsession"
    path.write_text("{}")
    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    said = []
    window.flash = said.append
    window.open_request(cli.parse([str(path)]))
    assert wait_for(lambda: len(said) >= 2)
    assert "not a File Compare session" in said[-1]
    window.close()
