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


def build(tokens: dict[str, str]) -> dict[str, str]:
    """The `diff_*` tokens for the theme `tokens` was built for."""
    theme = tokens.get("theme_name", "dark")
    row, mark = STRENGTH.get(theme, STRENGTH["dark"])
    surface = qss.unhex(tokens["bg_2"])
    out: dict[str, str] = {}
    for kind, hue in HUES.items():
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
    out["diff_filler"] = qss.mix(qss.unhex(tokens["bg_0"]), surface, 0.55)
    return out
