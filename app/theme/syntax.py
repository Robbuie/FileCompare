"""Syntax colours (1.1): fixed per theme, never following the accent.

They are the quietest colours in the view on purpose. A compare tool's first
job is to show what differs, and a keyword painted as loud as a deletion
would compete with it; so every colour here is a muted hue that reads on the
theme's pane surface and still reads through the difference washes, which
are pre-mixed against the same surface (`theme/diff.py`).

Three sets: one for the dark greys (dark and blueprint), one for the light
ones (light and warm paper), and one for high contrast, which is brighter and
more saturated because that theme exists to be read.
"""

from __future__ import annotations

DARK = {
    "keyword": "#c792ea",
    "type": "#56c8d8",
    "function": "#dcd49a",
    "string": "#d9a37c",
    "number": "#a8d494",
    "comment": "#7f9a78",
    "constant": "#6fb8ff",
    "preproc": "#c792ea",
    "tag": "#6fa8ff",
    "attribute": "#9cd0f0",
    "builtin": "#56c8d8",
    "label": "#f0a868",
}

LIGHT = {
    "keyword": "#8a2fb8",
    "type": "#1f7a8c",
    "function": "#795e14",
    "string": "#a33b16",
    "number": "#2f7d32",
    "comment": "#6b7f62",
    "constant": "#1a5fb4",
    "preproc": "#8a2fb8",
    "tag": "#1a5fb4",
    "attribute": "#b8520f",
    "builtin": "#1f7a8c",
    "label": "#b8520f",
}

CONTRAST = {
    "keyword": "#e0a8ff",
    "type": "#5fe8f5",
    "function": "#fff17a",
    "string": "#ffb98a",
    "number": "#b8ff9e",
    "comment": "#9fd69a",
    "constant": "#86c8ff",
    "preproc": "#e0a8ff",
    "tag": "#86c8ff",
    "attribute": "#b8e4ff",
    "builtin": "#5fe8f5",
    "label": "#ffc07a",
}

BY_THEME = {"dark": DARK, "blueprint": DARK, "light": LIGHT, "paper": LIGHT,
            "contrast": CONTRAST}


def build(tokens: dict[str, str]) -> dict[str, str]:
    """The `syn_*` tokens for the theme `tokens` was built for."""
    chosen = BY_THEME.get(tokens.get("theme_name", "dark"), DARK)
    return {f"syn_{name}": value for name, value in chosen.items()}
