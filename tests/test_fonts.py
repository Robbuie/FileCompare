"""Text that is placed by column has to be drawn in the font it was measured in.

The application stylesheet sets the UI family on every QWidget, and a
stylesheet font wins over `setFont`. Until 1.11.1 the text panes measured
columns in the mono face and painted in Segoe UI, so syntax colours and
character marks sat beside the text they belonged to. The preview showed it;
no test did. These do.
"""

import os

from PySide6.QtGui import QFontInfo, QPainter

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


def test_the_panes_paint_in_the_face_they_measure(qt_app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    tab = _open(window, "moved.left.st", "moved.right.st")
    pane = tab.view.left

    # The stylesheet still owns the widget font; the pane must not use it.
    assert not QFontInfo(pane.font()).fixedPitch()
    assert QFontInfo(pane.mono).fixedPitch()

    used = []
    original = QPainter.setFont

    def record(self, font):
        used.append(QFontInfo(font).fixedPitch())
        return original(self, font)

    monkeypatch.setattr(QPainter, "setFont", record)
    pane.grab()
    assert used and all(used)
    window.close()


def test_the_line_editor_is_mono_too(qt_app, tmp_path):
    window = _window(tmp_path)
    tab = _open(window, "settings.left.ini", "settings.right.ini")
    editor = tab.view.editor
    editor.ensurePolished()
    assert QFontInfo(editor.font()).fixedPitch()
    window.close()
