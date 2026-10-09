"""Home (1.21): sessions kept in folders, the quick row's mode, and what each
recent comparison found."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication

from app.core import library, savedsession
from app.ui.starttab import when


def test_the_library_keeps_named_sessions_in_folders():
    entries = library.add([], "Documents vs NAS", "Backups",
                          savedsession.Saved(left="C:\\Docs", right="\\\\nas\\Docs"))
    entries = library.add(entries, "Tools", "", savedsession.Saved(left="a", right="b"))
    assert library.folders(entries) == ["Backups", library.UNFILED]
    # The same name in the same folder replaces the old one.
    entries = library.add(entries, "documents vs nas", "Backups",
                          savedsession.Saved(left="C:\\New", right="\\\\nas\\Docs"))
    assert len(entries) == 2 and "C:\\New" in library.describe(entries[-1])
    moved = library.move(entries, 0, "Projects")
    assert library.folders(moved) == ["Projects", "Backups"]
    assert library.rename(moved, 0, "  Tools 2 ")[0]["name"] == "Tools 2"
    assert library.remove(moved, 0) == moved[1:]
    # Anything malformed is dropped rather than stopping Home.
    assert library.clean([{"name": "x", "text": "not json"}, 3, {"name": "", "text": "{}"}]) == []


def test_times_are_said_as_a_person_says_them():
    now = time.mktime((2026, 10, 9, 15, 0, 0, 0, 0, -1))
    assert when(now - 600, now).startswith("Today ")
    assert when(now - 86400, now) == "Yesterday"
    assert when(now - 3 * 86400, now) == time.strftime("%A", time.localtime(now - 3 * 86400))
    assert when(now - 30 * 86400, now) == time.strftime("%Y-%m-%d", time.localtime(now - 30 * 86400))
    assert when(0) == ""


def _wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def test_home_opens_kept_sessions_and_notes_what_was_found(qt_app, tmp_path):
    from app.core import session as core
    from app.core.config import Config
    from app.ui.comparetab import CompareTab
    from app.ui.starttab import StartTab
    from app.ui.window import MainWindow

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("one\ntwo\n")
    b.write_text("one\nTWO\n")
    config = Config(path=str(tmp_path / "c.json"))
    config.set("home.sessions", library.add(
        [], "My pair", "Work", savedsession.Saved(left=str(a), right=str(b))))
    window = MainWindow(config, look={}, look_source="own", custom_frame=False)
    try:
        home = window.new_tab()
        assert isinstance(home, StartTab) and home.title() == "Home"
        assert home.tree.topLevelItem(0).text(0) == "Work"
        item = home.tree.topLevelItem(0).child(0)
        home._open_item(item)
        tab = window.pages.currentWidget()
        assert isinstance(tab, CompareTab)
        assert _wait(lambda: tab.session.kind == core.TEXT and tab.summary() == "1 difference")
        window._page_changed(tab)
        notes = config.get("recent.notes")
        assert notes[f"{a}\n{b}"][0] == "1 difference"
        # The quick row compares as the tile chosen.
        home2 = window.new_tab()
        folders_tile = next(t for t in home2.tiles if t.mode == "folder")
        folders_tile.click()
        assert home2.mode == "folder"
        assert any(n[0] == "1 difference" for n in home2._notes.values())
        # Rename from the menu's path, and it is kept.
        home2._change(library.rename(home2.sessions, 0, "Renamed"))
        assert config.get("home.sessions")[0]["name"] == "Renamed"
    finally:
        window._may_close = lambda pages: True
        window.close()
