"""The difference colours, which are semantic and never follow the accent.

File Manager's CLAUDE.md reserved this before the compare view existed: a diff
colour has to agree with something else -- green is always "only on the
right", red is always "only on the left" -- so it stays fixed and stays named,
and nobody tidies it into the accent later. With the accent on redline, a
deletion and the current-difference outline would otherwise be the same red.

Each kind is one hue, and three strengths of it are derived here per theme:

  * `bar`  -- the hue itself, for the overview map and the gutter strip;
  * `row`  -- a wash across the whole row, pre-mixed against the pane's own
    surface so it is opaque and paints the same on every widget;
  * `mark` -- the stronger tint behind the characters that actually differ.

Pre-mixed rather than translucent because a painter that draws a row wash and
then an intraline mark on top of it would otherwise stack two alphas, and the
result would depend on paint order. Mixing against `bg_2` once gives a colour
that means one thing.

The strengths are per theme because a 13% wash that reads on the dark greys
vanishes on paper white, and high contrast exists to be read rather than
skimmed.
"""

from __future__ import annotations

from app.theme import qss

#: Channel triples. `add` and `chg` match the family's `good` and `warn` so a
#: green in the compare view is the green in File Manager's age chip.
HUES: dict[str, tuple[int, int, int]] = {
    "add": (70, 201, 139),      # only on the right
    "del": (229, 83, 75),       # only on the left; File Manager's `down` red
    "chg": (242, 176, 62),      # on both sides, and they differ
    "moved": (160, 124, 255),   # a block that moved (later versions)
    "conflict": (238, 70, 70),  # three-way only (later versions)
}

#: (row wash, intraline mark) as the share of the hue in the mix.
STRENGTH: dict[str, tuple[float, float]] = {
    "dark": (0.13, 0.36),
    "blueprint": (0.14, 0.38),
    "light": (0.15, 0.36),
    "paper": (0.15, 0.36),
    "contrast": (0.24, 0.55),
}

KINDS = tuple(HUES)

#: 1.18: the palettes. "family" is the semantic set above; "classic" is
#: Beyond Compare's way, chosen by the user as the default: every difference
#: in one red, whichever side it is on, and a file on one side only of a
#: folder compare in violet. Moved blocks and conflicts keep their own hue.
PALETTES = ("classic", "family")
CLASSIC_RED = (222, 60, 60)


def build(tokens: dict[str, str], palette: str = "classic") -> dict[str, str]:
    """The `diff_*` tokens for the theme `tokens` was built for."""
    theme = tokens.get("theme_name", "dark")
    row, mark = STRENGTH.get(theme, STRENGTH["dark"])
    surface = qss.unhex(tokens["bg_2"])
    classic = palette == "classic"
    hues = dict(HUES)
    if classic:
        for kind in ("add", "del", "chg"):
            hues[kind] = CLASSIC_RED
    out: dict[str, str] = {"diff_palette": "classic" if classic else "family"}
    dark = sum(surface) < 382
    # The ink a classic difference is written in: the red, pulled toward
    # the text colour of the theme so it reads as text and not as a wash.
    ink_to = (255, 255, 255) if dark else (0, 0, 0)
    out["diff_ink"] = qss.mix(CLASSIC_RED, ink_to, 0.78 if dark else 0.82)
    for kind, hue in hues.items():
        out[f"diff_{kind}_bar"] = qss.rgb(hue)
        out[f"diff_{kind}_row"] = qss.mix(hue, surface, row)
        out[f"diff_{kind}_mark"] = qss.mix(hue, surface, mark)
    # An ignored difference is text the rules said does not matter. It is
    # shown, in grey, rather than hidden: a compare that says "identical"
    # while hiding forty differences is worse than one that shows them.
    muted = qss.unhex(tokens["txt_2"])
    out["diff_ignored_bar"] = tokens["txt_2"]
    out["diff_ignored_row"] = qss.mix(muted, surface, 0.07)
    out["diff_ignored_mark"] = qss.mix(muted, surface, 0.22)
    # The row opposite a line that exists on one side only. Darker than the
    # pane, so it reads as a gap rather than as an empty line in the file.
    # Find matches: the selection hue, which is the family's "this is what you
    # asked for" colour, strong enough to read through a change wash.
    out["find_mark"] = qss.mix(qss.unhex(tokens["sel"]), surface, 0.42)
    out["diff_filler"] = qss.mix(qss.unhex(tokens["bg_0"]), surface, 0.55)
    # Folder compare's roles (1.18): a side only on the left, only on the
    # right, and a pair that differs. Family: red, green, amber. Classic:
    # one side only is violet whichever side, a differing pair red.
    roles = {"dir_left": "moved" if classic else "del",
             "dir_right": "moved" if classic else "add",
             "dir_newer": "chg"}
    for role, kind in roles.items():
        for part in ("bar", "row"):
            out[f"{role}_{part}"] = out[f"diff_{kind}_{part}"]
    # A merge's taken lines are green in either palette: there "added" is
    # what was chosen, not a difference.
    out["merge_taken_row"] = qss.mix(HUES["add"], surface, row)
    # Unified's "+" lines (1.19) are green in either palette, so the two
    # halves of a change can be told apart in one column.
    out["uni_add_bar"] = qss.rgb(HUES["add"])
    out["uni_add_row"] = qss.mix(HUES["add"], surface, row)
    out["uni_add_mark"] = qss.mix(HUES["add"], surface, mark)
    return out
