"""Syntax colour (1.1): which language, the spans, our two lexers, the view."""

from __future__ import annotations

import pytest

from app.core import syntax as S

CAT = {name: i for i, name in enumerate(S.CATEGORIES)}


@pytest.mark.parametrize("path, key", [
    ("C:\\x\\a.py", "python"), ("b.cs", "csharp"), ("Module1.vb", "vb.net"),
    ("deploy.ps1", "powershell"), ("run.bat", "batch"), ("q.sql", "tsql"),
    ("Cell4.L5X", "xml"), ("Cell4.L5K", "l5k"), ("Conveyor.st", "iec-st"),
    ("FB10.scl", "iec-st"), ("part.nc", "gcode"), ("x.json", "json"),
    ("settings.ini", "ini"), ("a.yaml", "yaml"), ("Makefile", "make"),
    ("notes.txt", ""), ("trace.log", ""), ("data.csv", ""), ("README", ""),
])
def test_the_language_comes_from_the_name(path, key):
    assert S.detect(path) == key


def test_a_file_without_an_extension_gets_one_look_at_its_first_line():
    assert S.detect("deploy", "#!/usr/bin/env python3") == "python"
    assert S.detect("deploy", "#!/bin/bash") == "bash"
    assert S.detect("export", '<?xml version="1.0"?>') == "xml"
    assert S.detect("export", "just some words") == ""


def test_spans_are_in_display_columns_with_tabs_expanded():
    spans = S.highlight(["\tx = 'a'  # note"], "python")
    # The tab is four columns, so the string starts at column 8.
    assert (8, 11, CAT["string"]) in spans[0]
    assert spans[0][-1] == (13, 19, CAT["comment"])


def test_a_comment_across_lines_colours_every_line_of_it():
    spans = S.highlight(["(* one", "two", "three *) x := 1;"], "iec-st")
    assert spans[0] == [(0, 6, CAT["comment"])]
    assert spans[1] == [(0, 3, CAT["comment"])]
    assert spans[2][0] == (0, 8, CAT["comment"])


def test_nothing_is_stripped_so_line_numbers_stay_true():
    spans = S.highlight(["", "", "x = 1", ""], "python")
    assert len(spans) == 4
    assert spans[2] and not spans[0] and not spans[3]


def test_structured_text_knows_its_keywords_times_and_based_numbers():
    spans = S.highlight(["IF Run THEN t := T#5s; n := 16#FF; END_IF"], "iec-st")[0]
    kinds = {cat for _a, _b, cat in spans}
    assert {CAT["keyword"], CAT["number"]} <= kinds
    assert (0, 2, CAT["keyword"]) in spans           # IF
    assert (17, 21, CAT["number"]) in spans          # T#5s


def test_l5k_colours_ladder_instructions_and_rung_comments():
    spans = S.highlight(['RC: "Start the motor";', "N: XIC(Start)OTE(Motor.Run);"],
                        "l5k")
    assert (4, 21, CAT["string"]) in spans[0]
    assert (3, 6, CAT["builtin"]) in spans[1]        # XIC
    assert (13, 16, CAT["builtin"]) in spans[1]      # OTE


def test_no_language_or_too_much_text_is_no_colour():
    assert S.highlight(["x"], "") is None
    assert S.highlight(["x"], "no-such-language") is None
    big = ["x" * 1000] * (S.LIMIT // 1000 + 1)
    assert S.highlight(big, "python") is None


def test_every_menu_entry_has_a_lexer():
    for key, _label in S.MENU:
        assert S.lexer(key) is not None, key


def test_every_theme_has_every_colour():
    from app.theme import sheet
    from app.theme.tokens import THEMES

    for theme in THEMES:
        tokens = sheet.tokens(theme, "blue", "normal")
        for name in S.CATEGORIES[1:]:
            assert tokens[f"syn_{name}"].startswith("#"), (theme, name)


# ------------------------------------------------------------------ the view

def test_the_view_uses_colour_only_for_the_lines_it_was_made_from():
    from app.ui.diffview import ViewState

    state = ViewState()
    lines = ["x = 1"]
    state.lines = (lines, [])
    state.syntax[0] = (lines, [[(0, 1, 1)]])
    assert state.syntax_spans(0, 0) == [(0, 1, 1)]
    state.lines = (["x = 1"], [])                 # a new list after an edit
    assert state.syntax_spans(0, 0) is None


def test_a_tab_colours_by_name_and_not_a_side_shown_by_structure(tmp_path):
    import time

    from PySide6.QtWidgets import QApplication

    from app.core.loader import Loader
    from app.core.session import Session
    from app.ui.comparetab import CompareTab
    from app.theme import sheet

    left = tmp_path / "a.ps1"
    right = tmp_path / "b.ps1"
    left.write_text("Write-Host 'one'\n")
    right.write_text("Write-Host 'two'\n")
    loader = Loader()
    session = Session(loader, str(left), str(right))
    tab = CompareTab(session, sheet.tokens("dark", "blue", "normal"))
    session.start()
    end = time.monotonic() + 5
    while session.result is None and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    tab.refresh()
    assert tab.language_for(0) == "powershell"
    assert tab.view.state.syntax_spans(0, 0)
    assert "PowerShell" in tab.language_label()
    tab.set_language("off")
    assert tab.view.state.syntax_spans(0, 0) is None
    assert tab.language_label() == "Plain text"
    tab.set_language("python")
    assert tab.language_for(1) == "python"
    session.sides[1].structured = True
    assert tab.language_for(1) == ""
    tab.stop()
    loader.shutdown()
