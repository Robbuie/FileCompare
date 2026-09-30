"""Checks on the design-system port and the difference colours.

The first five are File Manager's `tests/test_theme.py`, unchanged, because
the ported files are unchanged and should pass the same checks.
"""

import pytest

from app.theme import diff, qss, sheet
from app.theme.tokens import ACCENTS, DENSITIES, THEMES


def test_every_combination_builds():
    for theme in THEMES:
        for accent in ACCENTS:
            for density in DENSITIES:
                tokens = qss.build(theme, accent, density)
                assert tokens["bg_0"].startswith("#")
                assert tokens["accent"].startswith("#")


def test_unknown_names_fall_back_rather_than_raise():
    tokens = qss.build("from-a-later-version", "chartreuse", "enormous")
    assert tokens["theme_name"] == "dark"
    assert tokens["accent_name"] == "blue"
    assert tokens["density_name"] == "normal"


def test_accent_derivations_track_the_accent():
    blue = qss.build(accent="blue")
    red = qss.build(accent="redline")
    for key in ("accent", "accent_dim", "accent_text", "accent_soft"):
        assert blue[key] != red[key], f"{key} does not follow the accent"


def test_density_changes_metrics_and_nothing_else():
    compact = qss.build(density="compact")
    large = qss.build(density="large")
    assert compact["row_h"] != large["row_h"]
    assert compact["bg_0"] == large["bg_0"]
    assert compact["accent"] == large["accent"]


def test_render_rejects_an_unknown_token():
    with pytest.raises(KeyError):
        qss.render("QWidget {{ color: {not_a_token}; }}", qss.build())


def test_the_sheet_renders_for_every_combination():
    for theme in THEMES:
        for accent in ACCENTS:
            for density in DENSITIES:
                assert "QWidget" in sheet.render(sheet.tokens(theme, accent, density))


def test_every_theme_has_every_difference_colour_opaque():
    names = [f"diff_{kind}_{part}" for kind in (*diff.KINDS, "ignored")
             for part in ("bar", "row", "mark")] + ["diff_filler"]
    for theme in THEMES:
        tokens = sheet.tokens(theme)
        for name in names:
            value = tokens[name]
            assert value.startswith("#") and len(value) == 7, (theme, name, value)


def test_difference_colours_do_not_follow_the_accent():
    """The rule File Manager's CLAUDE.md set before this view existed."""
    blue = sheet.tokens(accent="blue")
    red = sheet.tokens(accent="redline")
    for key in blue:
        if key.startswith("diff_"):
            assert blue[key] == red[key], f"{key} follows the accent"


def test_a_mark_is_stronger_than_its_row_wash():
    for theme in THEMES:
        tokens = sheet.tokens(theme)
        surface = qss.unhex(tokens["bg_2"])
        for kind in diff.KINDS:
            row = qss.unhex(tokens[f"diff_{kind}_row"])
            mark = qss.unhex(tokens[f"diff_{kind}_mark"])
            distance = lambda c: sum(abs(a - b) for a, b in zip(c, surface))  # noqa: E731
            assert distance(mark) > distance(row), (theme, kind)
