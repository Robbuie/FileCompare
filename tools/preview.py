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
        busy = [t for t in tabs if isinstance(t, CompareTab) and (
            t.session.kind == WAITING or t._table_request or t._hex_request
            or t._image_request or any(t._syntax_requests))]
        if not busy:
            break
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()


def act(app, page, actions) -> None:
    """Drive the tab the way keys would, for a preview of a state rather than
    of a fresh window. Each action is one of:

      NAME            a tab command, as the view's keys send them ("copy-left")
      find=TEXT       open the find bar and type TEXT
      select=S,A,B    select rows A to B on side S
      next            press next difference
      expand          open every folder of a folder compare
      mode=VIEW       switch the View to text, rungs, table, hex or image
      menu=TITLE      open that menu of the menu bar; it is saved beside the
                      picture as `<out>-menu.png` (1.17)
      run=COMMAND     run a command from `ui/commands.py`, as a click would
    """
    for action in actions or ():
        name, _, value = action.partition("=")
        if name == "find":
            page.open_find()
            page.find.field.setText(value)
        elif name == "select":
            side, first, stop = (int(v) for v in value.split(","))
            page.view.select_rows(side, first, stop)
        elif name == "next":
            page.view.next_difference()
        elif name == "expand":
            page.folders.tree.expandAll()
        elif name == "mode":
            page.set_mode(value)
        elif name == "menu":
            from app.ui.chrome import sync_menu

            window = page.window()
            menu = window.menubar.menus[value]
            sync_menu(menu, window)
            menu.popup(window.mapToGlobal(window.rect().topLeft()))
            for _ in range(5):
                app.processEvents()
            window._preview_menu = menu
        elif name == "run":
            page.window().run_command(value)
        else:
            page._command(name)
        for _ in range(3):
            app.processEvents()
            time.sleep(0.02)


def render(out: str, *, pair=DEFAULT_PAIR, start: bool = False, theme="dark",
           accent="blue", density="normal", width=1400, height=820, step: int = 0,
           rules=None, actions=None) -> str:
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
    act(app, page, actions)
    settle(app, window, 3)
    app.processEvents()
    window.grab().save(out)
    menu = getattr(window, "_preview_menu", None)
    if menu is not None:
        menu.grab().save(os.path.splitext(out)[0] + "-menu.png")
        menu.close()
    # A preview that edited something must not stop on "unsaved changes".
    window._may_close = lambda pages: True
    window.close()
    return out


def sample_folders() -> tuple[str, str]:
    """Two small trees that differ in every way a sync cares about."""
    base = tempfile.mkdtemp()
    left, right = os.path.join(base, "Jobs"), os.path.join(base, "Backup")
    files = {
        left: {"Line 3\\Cell4.L5X": "a" * 900, "Line 3\\notes.txt": "new",
               "HMI\\screens.mer": "m" * 4000, "same.ini": "x", "only-left.csv": "1,2"},
        right: {"Line 3\\Cell4.L5X": "a" * 800, "Line 3\\notes.txt": "old",
                "same.ini": "x", "Retired\\old.L5X": "r" * 300, "only-right.txt": "z"},
    }
    now = time.time()
    for root, found in files.items():
        for rel, text in found.items():
            path = os.path.join(root, *rel.split("\\"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as out:
                out.write(text)
            age = 0 if root == left else 86400
            os.utime(path, (now - age, now - age))
    same = [os.path.join(r, "same.ini") for r in (left, right)]
    for path in same:
        os.utime(path, (now - 5000, now - 5000))
    return left, right


def render_sync(out: str, mode: str, theme="dark", accent="blue", density="normal",
                width=1400, height=820) -> str:
    """The folder view, and beside it (`<out>-dialog.png`) the sync preview."""
    from app.core import syncplan as S
    from app.ui.syncdialog import SyncDialog

    app, window = build(theme, accent, density, width, height)
    left, right = sample_folders()
    window.compare(left, right)
    window.show()
    page = window.pages.currentWidget()
    end = time.monotonic() + 10
    while time.monotonic() < end:
        app.processEvents()
        view = getattr(page, "folders", None)
        if view is not None and view.session.tree is not None and not view.session.busy:
            break
        time.sleep(0.02)
    settle(app, window, 1)
    window.grab().save(out)
    view = page.folders
    dialog = SyncDialog(view.session.tree, left, right,
                        mode=S.MIRROR if mode == "mirror" else S.UPDATE,
                        tokens=view.model.tokens, parent=window)
    dialog.set_remote((False, False))
    dialog.show()
    for _ in range(5):
        app.processEvents()
    second = os.path.splitext(out)[0] + "-dialog.png"
    dialog.grab().save(second)
    dialog.close()
    window.close()
    return f"{out}\n{second}"


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
    parser.add_argument("--do", action="append", default=[],
                        help="a tab command before the picture; see act()")
    parser.add_argument("--sync", choices=("update", "mirror"),
                        help="two sample folders, and the sync preview for them")
    args = parser.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))
    if args.sync:
        print(render_sync(args.out, args.sync, theme=args.theme, accent=args.accent,
                          density=args.density, width=width, height=height))
        return 0

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
                 step=args.step, actions=args.do))
    return 0


if __name__ == "__main__":
    sys.exit(main())
