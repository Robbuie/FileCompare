"""The command table (1.17): one table for the menus and the toolbar, and a
window whose every menu and button can be asked about without falling over."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication

from app.ui import commands as C


def test_every_id_in_a_menu_or_toolbar_is_a_command():
    for _title, items in C.MENUS:
        for item in items:
            if item == "-":
                continue
            if item.startswith(">"):
                assert item[1:] in C.DYNAMIC, item
            else:
                assert item in C.COMMANDS, item
    for groups in C.TOOLBARS.values():
        for group in groups:
            for item in group:
                assert item in C.COMMANDS, item
                assert C.COMMANDS[item].glyph, f"{item} has no icon for the toolbar"
    for owner, spec in C.TOOL_MENUS.items():
        assert owner in C.COMMANDS
        if isinstance(spec, str):
            assert spec in C.DYNAMIC
        else:
            for item in spec:
                assert item == "-" or item.lstrip(">") in C.COMMANDS or item[1:] in C.DYNAMIC


def test_no_two_commands_claim_the_same_key():
    seen: dict[str, str] = {}
    for command in C.COMMANDS.values():
        if command.key:
            assert command.key not in seen, (command.id, seen.get(command.key))
            seen[command.key] = command.id


def test_a_menu_item_shows_its_key_without_registering_it():
    command = C.COMMANDS["next"]
    assert C.menu_text(command) == "Next difference\tAlt+Down"
    assert C.menu_text(C.COMMANDS["expand-all"]) == "Expand all"


def _wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()
    return predicate()


def _window(tmp_path):
    from app.core.config import Config
    from app.ui.window import MainWindow

    config = Config(path=str(tmp_path / "config.json"))
    return MainWindow(config, look={"theme": "dark", "accent": "blue", "density": "normal"},
                      look_source="own", custom_frame=False)


def _ask_everything(window):
    """Every command and every menu, asked about once: none may raise."""
    from app.ui.chrome import sync_menu

    for id_ in C.COMMANDS:
        state = window.command_state(id_)
        assert isinstance(state, C.State)
    for name in C.DYNAMIC:
        window.command_state(">" + name)
    for menu in window.menubar.menus.values():
        sync_menu(menu, window)
    window.toolbar.refresh()


def test_a_text_tab_drives_the_toolbar_and_menus(qt_app, tmp_path):
    from app.core import session as core

    left = tmp_path / "a.ini"
    right = tmp_path / "b.ini"
    left.write_text("[x]\nk = 1\nsame\nother = 2\n")
    right.write_text("[x]\nk = 2\nsame\nother = 3\n")
    window = _window(tmp_path)
    try:
        tab = window.compare(str(left), str(right))
        assert _wait(lambda: tab.session.kind == core.TEXT and tab.session.result is not None)
        window._page_changed(tab)
        assert window.toolbar.kind == "text"
        assert len(window.menubar.menus) == 8
        _ask_everything(window)
        assert window.command_state("next").enabled
        assert not window.command_state("show-diffs").visible     # a folder command
        assert not window.command_state("next-conflict").visible  # a merge command
        window.run_command("next")
        assert tab.count.text().startswith("Difference 2 of")
        assert window._position.text() == tab.count.text()
        window.run_command("rules")
        assert not tab.session.rules.enabled or not tab.session.rules.any
        window.run_command("mark-words")
        assert tab.session.options.intraline == "word"
        assert window.command_state("mark-words").checked
    finally:
        window._may_close = lambda pages: True
        window.close()


def test_a_folder_tab_has_its_own_toolbar(qt_app, tmp_path):
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a.txt").write_text("a")
    (right / "b.txt").write_text("b")
    window = _window(tmp_path)
    try:
        tab = window.compare(str(left), str(right))
        assert _wait(lambda: tab.folders is not None and tab.folders.session.tree is not None)
        window._page_changed(tab)
        assert window.toolbar.kind == "folder"
        _ask_everything(window)
        assert window.command_state("show-diffs").checked
        assert not window.command_state("copy-left").enabled      # nothing selected
        assert not window.command_state("edit").visible          # a text command
        window.run_command("show-all")
        assert tab.folders.model.show == "all"
    finally:
        window._may_close = lambda pages: True
        window.close()


def test_the_start_page_shows_only_the_window_commands(qt_app, tmp_path):
    window = _window(tmp_path)
    try:
        window.new_tab()
        assert window.toolbar.kind == "start"
        _ask_everything(window)
        assert window.command_state("new").enabled
        assert not window.command_state("copy-left").visible
    finally:
        window.close()
