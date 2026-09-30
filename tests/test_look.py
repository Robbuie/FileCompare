"""The two rules a reviewer would otherwise have to remember, checked by grep.

No literal colour outside `app/theme/`: a hardcoded grey is a spot that stops
following the theme picker. Redline PDF's `verify.js` fails its build on the
same thing.

No filesystem call under `app/ui/`: the UI thread never touches a file,
because a dead share blocks the call for half a minute. The one allowed door
is `QFileDialog`, which is Windows' own dialog and somebody asking.
"""

import os
import re

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")

COLOUR = re.compile(r"""["']#[0-9a-fA-F]{3,8}["']|\brgba?\(\s*\d""")
FILESYSTEM = re.compile(
    r"^\s*(import os\b|from os\b|import pathlib|from pathlib|import shutil|from shutil)"
    r"|\bos\.(path|stat|scandir|listdir|remove|rename|replace|makedirs|walk)\b"
    r"|(?<![\w.])open\(",
    re.MULTILINE,
)


def _files(folder: str):
    for base, _dirs, names in os.walk(os.path.join(ROOT, folder)):
        for name in names:
            if name.endswith(".py"):
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    yield path, handle.read()


def _strip_docstrings_and_comments(text: str) -> str:
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return re.sub(r"#[^\n]*", "", text)


def test_no_literal_colour_outside_the_theme():
    offenders = []
    for folder in ("ui", "core", "io"):
        for path, text in _files(folder):
            code = re.sub(r'"""[\s\S]*?"""', "", text)
            for match in COLOUR.finditer(code):
                offenders.append(f"{os.path.relpath(path, ROOT)}: {match.group(0)}")
    assert not offenders, "colour literals outside app/theme: " + ", ".join(offenders)


def test_the_ui_never_touches_the_filesystem():
    offenders = []
    for path, text in _files("ui"):
        code = _strip_docstrings_and_comments(text)
        for match in FILESYSTEM.finditer(code):
            offenders.append(f"{os.path.relpath(path, ROOT)}: {match.group(0).strip()}")
    assert not offenders, "filesystem calls under app/ui: " + ", ".join(offenders)


def test_the_engine_imports_no_qt():
    for path, text in _files(os.path.join("core", "diff")):
        assert "PySide6" not in text, path
    for path, text in _files("io"):
        assert "PySide6" not in text, path
