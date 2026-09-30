"""Render the window to a PNG without a screen.

The same tool as File Manager's `tools/preview.py`, for the same reason:
Claude cannot see this application run, but Qt's offscreen platform draws
the real window with the real stylesheet into an image, which catches what is
obvious to a pair of eyes and invisible in a diff -- a token that did not
apply, a pane that collapsed, chrome that does not match the family.

It runs the real stack: real session, real loader thread, real diff. Only the
screen is missing. It says nothing about whether the window *behaves*.

    python tools/preview.py --pair tests/data/text/settings.left.ini tests/data/text/settings.right.ini --out preview.png
    python tools/preview.py --all-themes --out-dir previews
    python tools/preview.py --start --out start.png
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PAIR = (os.path.join(HERE, "tests", "data", "text", "settings.left.ini"),
                os.path.join(HERE, "tests", "data", "text", "settings.right.ini"))


def build(theme: str, accent: str, density: str, width: int, height: int):
    from PySide6.QtWidgets import QApplication

    from app.core.config import Config
    from app.ui.window import MainWindow

    app = QApplication.instance() or QApplication([])
    # A throwaway settings file: a preview must not read, or write, the
    # settings of whoever runs it.
    config = Config(path=os.path.join(tempfile.mkdtemp(), "config.json"))
    window = MainWindow(config, look={"theme": theme, "accent": accent, "density": density},
                        look_source="own")
    window.resize(width, height)
    return app, window


def settle(app, window, seconds: float = 10.0) -> None:
    """Pump events until every comparison has an answer, or time runs out."""
    from app.core.session import WAITING
    from app.ui.comparetab import CompareTab

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        tabs = [window.pages.widget(i) for i in range(window.pages.count())]
        busy = [t for t in tabs if isinstance(t, CompareTab) and t.session.kind == WAITING]
        if not busy:
            break
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()


def render(out: str, *, pair=DEFAULT_PAIR, start: bool = False, theme="dark",
           accent="blue", density="normal", width=1400, height=820, step: int = 0,
           rules=None) -> str:
    app, window = build(theme, accent, density, width, height)
    if start:
        window.new_tab()
    else:
        tab = window.compare(*pair)
        if rules is not None:
            tab.session.options.rules = rules
    window.show()
    settle(app, window)
    page = window.pages.currentWidget()
    for _ in range(step):
        page.view.next_difference()
    app.processEvents()
    window.grab().save(out)
    window.close()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", nargs=2, default=list(DEFAULT_PAIR))
    parser.add_argument("--start", action="store_true", help="the start page")
    parser.add_argument("--out", default="preview.png")
    parser.add_argument("--theme", default="dark")
    parser.add_argument("--accent", default="blue")
    parser.add_argument("--density", default="normal")
    parser.add_argument("--size", default="1400x820")
    parser.add_argument("--step", type=int, default=0, help="press next difference N times")
    parser.add_argument("--all-themes", action="store_true")
    parser.add_argument("--out-dir", default="previews")
    args = parser.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))

    if args.all_themes:
        from app.theme.tokens import THEMES

        os.makedirs(args.out_dir, exist_ok=True)
        for theme in THEMES:
            out = os.path.join(args.out_dir, f"{theme}.png")
            render(out, pair=args.pair, start=args.start, theme=theme, accent=args.accent,
                   density=args.density, width=width, height=height, step=args.step)
            print(out)
        return 0
    print(render(args.out, pair=args.pair, start=args.start, theme=args.theme,
                 accent=args.accent, density=args.density, width=width, height=height,
                 step=args.step))
    return 0


if __name__ == "__main__":
    sys.exit(main())
