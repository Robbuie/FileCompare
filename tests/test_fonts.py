"""Text that is placed by column has to be drawn in the font it was measured in.

The application stylesheet sets the UI family on every QWidget, and a
stylesheet font wins over `setFont`. Until 1.11.1 the text panes measured
columns in the mono face and painted in Segoe UI, so syntax colours and
character marks sat beside the text they belonged to. The preview showed it;
no test did. These do.
"""

import os

import pytest
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QFontMetricsF, QPainter

from app import cli
from app.core.config import Config

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "text")


def _window(tmp_path):
    from app.ui.window import MainWindow

    config = Config(path=str(tmp_path / "c.json"))
    window = MainWindow(config, look={"theme": "dark", "accent": "blue", "density": "normal"},
                        look_source="own", custom_frame=False)
    window.resize(1200, 700)
    return window


def _open(window, left, right):
    from app.core import session as core
    from tests.test_app import wait_for

    window.open_request(cli.parse([os.path.join(DATA, left), os.path.join(DATA, right)]))
    window.show()
    tab = window.pages.currentWidget()
    assert wait_for(lambda: tab.session.kind == core.TEXT)
    wait_for(lambda: False, 0.1)
    return tab


def _measured_mono(font) -> bool:
    """Whether every character is as wide as every other in this font, which
    is the thing the column arithmetic depends on. Measured rather than asked:
    `QFontInfo.fixedPitch` is not reported by every platform plugin -- the
    offscreen one on the Windows runner says False for Consolas."""
    metrics = QFontMetricsF(font)
    return abs(metrics.horizontalAdvance("i") - metrics.horizontalAdvance("W")) < 0.01


def _ui_family(widget) -> str:
    return widget.font().families()[0] if widget.font().families() else widget.font().family()


def test_the_panes_paint_in_the_face_they_measure(qt_app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    try:
        tab = _open(window, "moved.left.st", "moved.right.st")
        pane = tab.view.left

        # The bug was the painter getting the widget's font, which the
        # stylesheet owns. Whatever this machine resolves the families to,
        # the painter must be handed the pane's own font and not that one.
        used = []
        original = QPainter.setFont

        def record(self, font):
            used.append(font.families() or [font.family()])
            return original(self, font)

        monkeypatch.setattr(QPainter, "setFont", record)
        pane.grab()
        assert used
        assert all(families == pane.mono.families() for families in used)
        assert pane.mono.families()[0] == "Cascadia Mono"
        assert _ui_family(pane) != "Cascadia Mono"
    finally:
        window.close()


def test_the_mono_face_is_monospaced_where_one_exists(qt_app, tmp_path):
    fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if not _measured_mono(fixed):
        pytest.skip("this platform plugin offers no monospaced face to resolve to")
    window = _window(tmp_path)
    try:
        tab = _open(window, "settings.left.ini", "settings.right.ini")
        assert _measured_mono(tab.view.left.mono), QFontInfo(tab.view.left.mono).family()
    finally:
        window.close()


def test_the_line_editor_is_given_the_mono_family(qt_app, tmp_path):
    window = _window(tmp_path)
    try:
        tab = _open(window, "settings.left.ini", "settings.right.ini")
        editor = tab.view.editor
        editor.ensurePolished()
        # From the sheet's `{mono}` rule; the substitution `sheet.apply`
        # installs is what turns it into Consolas where Cascadia is missing.
        assert editor.font().family() == "Cascadia Mono"
        assert "consolas" in [f.lower() for f in QFont.substitutes("Cascadia Mono")]
    finally:
        window.close()
