"""The window: title bar, a strip of comparison tabs, and the status line.

Its shape is File Manager's -- the same custom title bar with Windows' own
snapping and shadow kept (`winframe.py`), the same tab pills, the same status
line on the backdrop -- so a comparison opened from File Manager looks like
part of it.

Every way in arrives at `open_request`: the command line at startup, a second
instance handing over its arguments, the start page's Compare button, and a
drop of two files on the window.
"""

from __future__ import annotations

import ntpath
from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.cli import Request
from app.core import appearance, formats, savedsession, updates
from app.core.config import Config
from app.core.loader import Loader
from app.core.rules import Rules
from app.core.rules import from_config as rules_from_config
from app.core.session import Options, Session
from app.io import sessionfile
from app.theme import sheet
from app.theme.tokens import ACCENT_LABELS, ACCENTS, DENSITIES, DENSITY_LABELS, THEME_LABELS, THEMES
from app.ui import glyphs, winframe
from app.ui.chrome import MenuBar, ToolBar
from app.ui.commands import HIDDEN, ONLY, State
from app.ui.comparetab import CompareTab
from app.ui.mergetab import MergeTab
from app.ui.starttab import StartTab
from app.ui.titlebar import TitleBar

KEYS = """\
Alt+Down / Alt+Up         next, previous difference
Home / End                first, last difference
Ctrl+Home / Ctrl+End      top, bottom of the file
Up, Down, PgUp, PgDn      move; with Shift, select lines
Ctrl+Up / Ctrl+Down       scroll without moving
Left / Right              scroll sideways
Tab                       the other side
Ctrl+M                    the other end of a moved block
Ctrl+L, then Ctrl+L       hold this line opposite one on the other side
Ctrl+Shift+L              remove the pin here, or every pin
Alt+Right / Alt+Left      copy the selected lines, or this difference, right, left
Ctrl+Alt+Right / Left     copy everything right, left
Enter, F2, double-click   edit the selected lines (Ctrl+Enter keeps, Esc drops)
Shift+Enter               insert an empty line below
Right-click               copy, edit and align from a menu
F5 (folders)              copy the selected rows from the side you're on
Alt+Right / Left (folders) copy the selected rows right, left
Delete                    delete the selected lines
Ctrl+Z / Ctrl+Y           undo, redo on this side
Ctrl+S / Ctrl+Shift+S     save this side, save both
Ctrl+C                    copy the selected lines
Ctrl+A                    select every line
Ctrl+F                    find; F3 / Shift+F3 next, previous
Ctrl+Shift+H              save an HTML report or a patch
Ctrl+Alt+S                save this comparison's setup as a session file
Ctrl+U                    swap sides
Ctrl+R                    compare again from disk
Ctrl+I                    rules off and on
Ctrl+T                    new comparison
Ctrl+W                    close this tab
Ctrl+Tab / Ctrl+Shift+Tab next, previous tab
F1                        this list"""


def rules_from(config: Config) -> Rules:
    # Moved to core in 1.11, where the command-line report reads it too.
    return rules_from_config(config)


class MainWindow(QMainWindow):

    def __init__(self, config: Config, *, look: dict[str, str], look_source: str,
                 custom_frame: bool = True) -> None:
        super().__init__()
        self._config = config
        self._look = dict(look)
        self._look_source = look_source
        self._loader = Loader(self)
        #: 1.10: session files being read, by request id.
        self._session_files: dict[int, str] = {}
        self._loader.finished.connect(self._loaded)
        self._tokens = sheet.tokens(**self._look, colours=self._colours())
        self._titlebar: TitleBar | None = None
        #: Set when a merge tab saved with nothing unresolved (git's answer).
        self.merge_ok = False
        self._frame: winframe.NativeFrame | None = None

        self.setWindowTitle("File Compare")
        self.setAcceptDrops(True)
        self.resize(int(config.get("window.width")), int(config.get("window.height")))

        # The tab strip and the pages under it.
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setFocusPolicy(Qt.NoFocus)
        self.tabs.setElideMode(Qt.ElideMiddle)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.tabBarDoubleClicked.connect(lambda i: self.new_tab() if i < 0 else None)
        self.pages = QStackedWidget()
        self._new = QToolButton()
        self._new.setProperty("role", "nav")
        self._new.setToolTip("New comparison (Ctrl+T)")
        self._new.setFocusPolicy(Qt.NoFocus)
        self._new.clicked.connect(lambda _c=False: self.new_tab())
        strip = QWidget()
        strip.setProperty("role", "tabstrip")
        strip.setAttribute(Qt.WA_StyledBackground, True)
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(10, 0, 10, 0)
        strip_row.setSpacing(4)
        strip_row.addWidget(self.tabs)
        strip_row.addWidget(self._new)
        strip_row.addStretch(1)

        body = QWidget()
        stack = QVBoxLayout(body)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(4)
        stack.addWidget(strip)
        stack.addWidget(self.pages, 1)

        self._status_left = QLabel()
        self._status_right = QLabel()
        #: 1.17: where you are in the current tab ("Difference 2 of 4"), which
        #: was in the tab's own toolbar row until the window had a toolbar.
        self._position = QLabel()
        self._position.setProperty("role", "position")
        self.statusBar().addWidget(self._status_left, 1)
        self.statusBar().addPermanentWidget(self._position)
        self.statusBar().addPermanentWidget(self._status_right)
        self.statusBar().setSizeGripEnabled(False)

        # 1.17: the menu bar and the labelled toolbar, both from
        # `ui/commands.py`; this window is their provider.
        self.menubar = MenuBar(self)
        self.toolbar = ToolBar(self)

        if custom_frame:
            self._titlebar = TitleBar()
            self._titlebar.set_menubar(self.menubar)
            self._titlebar.menuRequested.connect(self._show_app_menu)
            self._titlebar.goRequested.connect(self.new_tab)
            self._titlebar.minimizeRequested.connect(self.showMinimized)
            self._titlebar.maximizeRequested.connect(self.toggle_maximized)
            self._titlebar.closeRequested.connect(self.close)
            root = QWidget()
            column = QVBoxLayout(root)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            column.addWidget(self._titlebar)
            column.addWidget(self.toolbar)
            column.addWidget(body, 1)
            self.setCentralWidget(root)
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self._frame = winframe.NativeFrame(self, glass=False, dark=self._is_dark())
        else:
            root = QWidget()
            column = QVBoxLayout(root)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            column.addWidget(self.menubar)
            column.addWidget(self.toolbar)
            column.addWidget(body, 1)
            self.setCentralWidget(root)

        self._shortcuts()
        self.apply_look(self._look, self._look_source, save=False)

        self.updates = updates.Updates(config, __version__, self)
        self.updates.available.connect(self._update_available)
        self.updates.uptodate.connect(
            lambda current: self.flash(f"{current} is the latest version"))
        self.updates.problem.connect(self.flash)
        self.updates.progress.connect(self._update_progress)
        self.updates.ready.connect(self._update_ready)
        self.updates.start_if_wanted()

    # ----------------------------------------------------------------- tabs

    def _pages(self) -> list[QWidget]:
        return [self.pages.widget(i) for i in range(self.pages.count())]

    def _add_page(self, page: QWidget) -> int:
        self.pages.addWidget(page)
        index = self.tabs.addTab(page.title())
        self.tabs.setTabToolTip(index, page.tooltip())
        close = QToolButton()
        close.setProperty("role", "tabclose")
        close.setFocusPolicy(Qt.NoFocus)
        close.setToolTip("Close (Ctrl+W)")
        close.setIcon(glyphs.icon("close", colour=self._tokens["txt_2"],
                                  muted=self._tokens["txt_2"], size=10))
        close.clicked.connect(lambda _c=False, p=page: self.close_page(p))
        self.tabs.setTabButton(index, QTabBar.RightSide, close)
        changed = getattr(page, "commandsChanged", None)
        if changed is not None:
            changed.connect(lambda p=page: self._page_changed(p))
        self.tabs.setCurrentIndex(index)
        self.pages.setCurrentWidget(page)
        page.focus_view()
        self._page_changed(page)
        return index

    def _index_of(self, page: QWidget) -> int:
        return self.pages.indexOf(page)

    def _tab_changed(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            page = self.pages.widget(index)
            self.pages.setCurrentIndex(index)
            page.focus_view()
            self._status_left.setText(getattr(page, "_last_status", ""))
            self._page_changed(page)

    def _tab_moved(self, source: int, target: int) -> None:
        page = self.pages.widget(source)
        self.pages.removeWidget(page)
        self.pages.insertWidget(target, page)
        self.pages.setCurrentIndex(self.tabs.currentIndex())

    def _retitle(self, page: QWidget) -> None:
        index = self._index_of(page)
        if index >= 0:
            self.tabs.setTabText(index, page.title())
            self.tabs.setTabToolTip(index, page.tooltip())

    def close_page(self, page: QWidget | None = None) -> None:
        page = page or self.pages.currentWidget()
        if page is None:
            return
        if not self._may_close([page]):
            return
        if isinstance(page, (CompareTab, MergeTab)):
            page.stop()
        # The page leaves the stack before its tab leaves the strip: removing
        # the tab moves the current index, and `_tab_changed` reads the stack.
        index = self._index_of(page)
        self.pages.removeWidget(page)
        self.tabs.removeTab(index)
        page.deleteLater()
        if self.pages.count() == 0:
            self.new_tab()

    def new_tab(self, left: str = "", right: str = "") -> StartTab:
        recent = [tuple(pair) for pair in self._config.get("recent")
                  if isinstance(pair, list) and len(pair) == 2]
        page = StartTab((self._config.get("start.left_folder"),
                         self._config.get("start.right_folder")), recent=recent)
        page.set_paths(left, right)
        page.compareRequested.connect(lambda l, r, p=page: self._start_to_compare(p, l, r))
        page.sessionRequested.connect(self.open_session)
        page.browsed.connect(lambda side, folder: self._config.set(
            "start.left_folder" if side == 0 else "start.right_folder", folder))
        self._add_page(page)
        return page

    def _start_to_compare(self, start: StartTab, left: str, right: str) -> None:
        """The start page becomes the comparison, in the same tab."""
        index = self._index_of(start)
        tab = self._compare_page(left, right)
        self.pages.removeWidget(start)
        self.tabs.removeTab(index)
        start.deleteLater()
        self._insert_page(index, tab)

    def _insert_page(self, index: int, page: QWidget) -> None:
        self._add_page(page)
        current = self._index_of(page)
        if current != index:
            self.tabs.moveTab(current, index)

    def _compare_page(self, left: str, right: str, *, titles=("", ""),
                      readonly: set[str] | None = None, mode: str = "auto",
                      saved=None) -> CompareTab:
        options = Options(
            rules=rules_from(self._config),
            intraline=self._config.get("compare.intraline"),
            timeout=float(self._config.get("load.timeout")),
            max_bytes=int(float(self._config.get("load.max_mb")) * 1024 * 1024),
            backup=bool(self._config.get("save.backup")),
            folder_mask=str(self._config.get("folders.mask") or ""),
            folder_hour=bool(self._config.get("folders.ignore_hour")),
            folder_by_content=bool(self._config.get("folders.by_content")),
            folder_archives=bool(self._config.get("folders.archives")),
            folder_show=str(self._config.get("folders.show") or ""),
            folder_open_expanded=bool(self._config.get("folders.open_expanded")),
            folder_history=tuple(str(p) for p in self._config.get("folders.history") or []
                                 if isinstance(p, str))[:20],
            mode=mode,
            format="text" if mode == "text" else "auto",
            syntax="auto" if self._config.get("view.syntax") else "off",
            show=str(self._config.get("view.show") or "all"),
            context=int(self._config.get("view.context") or 3),
            details=bool(self._config.get("view.details")),
            file_history=self._file_history(),
        )
        if saved is not None:
            # 1.10: a session file's settings over the application's own.
            options = replace(
                options, rules=saved.rules, intraline=saved.intraline,
                folder_show=saved.folder_show or options.folder_show, **{name: value for name, value in (
                    ("folder_mask", saved.folder_mask), ("folder_hour", saved.folder_hour),
                    ("folder_by_content", saved.folder_by_content),
                    ("folder_archives", saved.folder_archives)) if value is not None})
        session = Session(self._loader, left, right, options=options, titles=titles,
                          readonly=readonly)
        if saved is not None:
            session.structure = saved.structure and session.format_kind != formats.PLAIN
            session.pins = list(saved.pins)
        self._remember(left, right)
        tab = CompareTab(session, self._tokens)
        tab.openPair.connect(lambda l, r: self.compare(l, r))
        tab.openExtracted.connect(lambda l, r, titles: self.compare(
            l, r, titles=tuple(titles), readonly={"left", "right"}))
        tab.titleChanged.connect(lambda t=tab: self._retitle(t))
        tab.status.connect(lambda text, t=tab: self._tab_status(t, text))
        tab.setting.connect(self._config.set)
        tab.pairChanged.connect(self._remember)
        session.start()
        return tab

    def _file_history(self) -> tuple[str, ...]:
        """Files compared lately, newest first, for a side's path box (1.18):
        both sides of each recent pair."""
        out: list[str] = []
        for pair in self._config.get("recent") or []:
            if isinstance(pair, list):
                for path in pair:
                    if isinstance(path, str) and path and path not in out:
                        out.append(path)
        return tuple(out[:20])

    def open_session(self, path: str) -> None:
        """A .fcsession file (1.10): read off the UI thread, then opened as
        the comparison it describes."""
        request = self._loader.submit(sessionfile.read, path)
        self._session_files[request] = path
        self.flash(f"Opening the session {ntpath.basename(path)}...")

    def _loaded(self, request: int, envelope) -> None:
        path = self._session_files.pop(request, None)
        if path is None:
            return
        if not envelope.ok:
            reason = (envelope.error or "could not be read").split(": ", 1)[-1]
            self.flash(f"{ntpath.basename(path)}: {reason}")
            if not self.pages.count():
                self.new_tab()
            return
        saved = envelope.value
        tab = self.compare(saved.left, saved.right, titles=saved.titles,
                           readonly=set(saved.readonly), mode=saved.mode, saved=saved)
        tab.session_file = path

    def _remember(self, left: str, right: str) -> None:
        if not left or not right:
            return
        pairs = [p for p in self._config.get("recent")
                 if isinstance(p, list) and p != [left, right]]
        self._config.set("recent", ([[left, right]] + pairs)[:20])

    def _tab_status(self, tab: CompareTab, text: str) -> None:
        tab._last_status = text
        if self.pages.currentWidget() is tab:
            self._status_left.setText(text)

    def compare(self, left: str, right: str, **kwargs) -> CompareTab:
        tab = self._compare_page(left, right, **kwargs)
        # A lone empty start page is replaced rather than left behind.
        current = self.pages.currentWidget()
        if isinstance(current, StartTab) and self.pages.count() == 1 \
                and not any(f.text().strip() for f in current.fields):
            self._add_page(tab)
            self.close_page(current)
        else:
            self._add_page(tab)
        return tab

    def merge(self, mine: str, theirs: str, base: str, *, output: str = "") -> MergeTab:
        from app.core.mergesession import MergeSession

        session = MergeSession(self._loader, mine, theirs, base, output,
                               max_bytes=int(float(self._config.get("load.max_mb")) * 1024 * 1024))
        tab = MergeTab(session, self._tokens)
        tab.titleChanged.connect(lambda t=tab: self._retitle(t))
        tab.status.connect(lambda text, t=tab: self._tab_status(t, text))
        tab.finished.connect(self._merge_finished)
        session.start()
        current = self.pages.currentWidget()
        self._add_page(tab)
        if isinstance(current, StartTab) and self.pages.count() == 2 \
                and not any(f.text().strip() for f in current.fields):
            self.close_page(current)
        return tab

    def _merge_finished(self, ok: bool) -> None:
        self.merge_ok = ok

    def open_request(self, request: Request) -> None:
        if request.select_left:
            self._config.set("explorer.left", request.select_left)
            self._config.save()
            self.flash(f"Left side: {request.select_left}. "
                       "Right-click another and choose Compare to left side.")
            if not self.pages.count():
                self.new_tab(request.select_left)
            return
        if request.with_left:
            left = self._config.get("explorer.left")
            if not left:
                self.new_tab("", request.with_left)
                self.flash("No left side chosen yet; pick one here.")
                return
            self.compare(left, request.with_left)
            return
        if request.error:
            self.flash(request.error)
            if not self.pages.count():
                self.new_tab()
            return
        if request.merge:
            self.merge(*request.paths[:3], output=request.output)
            return
        if len(request.paths) == 1 and savedsession.is_session(request.paths[0]):
            self.open_session(request.paths[0])
            return
        if len(request.paths) == 2:
            self.compare(request.paths[0], request.paths[1],
                         titles=(request.left_title, request.right_title),
                         readonly=request.readonly, mode=request.mode)
        elif len(request.paths) == 1:
            self.new_tab(request.paths[0])
        elif not self.pages.count():
            self.new_tab()

    def flash(self, text: str) -> None:
        self.statusBar().showMessage(text, 15000)

    # ---------------------------------------------------------------- look

    def _is_dark(self) -> bool:
        return sum(sheet.qss.unhex(self._tokens["bg_0"])) < 382

    def apply_look(self, look: dict[str, str], source: str, *, save: bool = True) -> None:
        self._look = dict(look)
        self._look_source = source
        self._tokens = sheet.apply(QApplication.instance(), **self._look,
                                   colours=self._colours())
        if self._titlebar is not None:
            self._titlebar.apply_tokens(self._tokens)
        if self._frame is not None:
            self._frame.set_dark(self._is_dark())
        self._new.setIcon(glyphs.icon("plus", colour=self._tokens["txt_1"],
                                      muted=self._tokens["txt_2"], size=14))
        self.toolbar.apply_tokens(self._tokens)
        for index in range(self.tabs.count()):
            button = self.tabs.tabButton(index, QTabBar.RightSide)
            if button is not None:
                button.setIcon(glyphs.icon("close", colour=self._tokens["txt_2"],
                                           muted=self._tokens["txt_2"], size=10))
        for page in self._pages():
            if isinstance(page, (CompareTab, MergeTab)):
                page.apply_tokens(self._tokens)
        where = "File Manager's look" if source == "file manager" else "own look"
        self._status_right.setText(
            f"{THEME_LABELS.get(self._tokens['theme_name'], '')}  ·  "
            f"{ACCENT_LABELS.get(self._tokens['accent_name'], '')}  ·  {where}")

    def _colours(self) -> str:
        value = self._config.get("view.colours")
        return value if value in ("classic", "family") else "classic"

    def _set_colours(self, value: str) -> None:
        self._config.set("view.colours", value)
        self.apply_look(self._look, self._look_source)

    def _choose(self, key: str, value: str) -> None:
        """A theme, accent or density picked from the menu. Choosing one is
        choosing this application's own look, so following File Manager stops
        -- and the status line says so, since the two now differ."""
        look = dict(self._look)
        look[key] = value
        for name in appearance.KEYS:
            self._config.set(name, look[name])
        following = self._config.get("look.follow_file_manager")
        self._config.set("look.follow_file_manager", False)
        self.apply_look(look, "own")
        if following:
            self.flash("Using this application's own look now; "
                       "the menu can follow File Manager's again.")

    def _follow(self, on: bool) -> None:
        self._config.set("look.follow_file_manager", on)
        look, source = appearance.resolve(self._config)
        if on and source != "file manager":
            self.flash("File Manager's settings could not be read; keeping this look.")
        self.apply_look(look, source)

    # ------------------------------------------------------ commands (1.17)

    def _page(self):
        return self.pages.currentWidget()

    def _kind(self) -> str:
        page = self._page()
        return page.page_kind() if page is not None and hasattr(page, "page_kind") else "start"

    def _page_changed(self, page) -> None:
        """A page's commands, title or position changed: the toolbar and the
        position in the status bar follow the current page only."""
        if page is not self._page():
            return
        self.toolbar.set_kind(self._kind())
        self.toolbar.refresh()
        count = getattr(page, "count", None)
        self._position.setText(count.text() if count is not None else "")

    #: Commands the window answers itself, whatever the page.
    WINDOW = frozenset({
        "new", "open-session", "close-tab", "next-tab", "previous-tab", "exit", "keys",
        "check-updates", "about", "follow-look", "syntax-default", "keep-orig",
        "updates-on-launch"})

    def command_state(self, id_: str) -> State:
        if id_ in self.WINDOW:
            config = self._config
            checked = {
                "follow-look": bool(config.get("look.follow_file_manager")),
                "syntax-default": bool(config.get("view.syntax")),
                "keep-orig": bool(config.get("save.backup")),
                "updates-on-launch": bool(config.get("updates.check_on_launch")),
            }.get(id_)
            return State(checked=checked)
        if id_ in (">recent", ">theme", ">accent", ">density", ">colours"):
            return State()
        kind = self._kind()
        if id_ in ONLY and kind not in ONLY[id_]:
            return HIDDEN
        page = self._page()
        if page is None or not hasattr(page, "command_state"):
            return HIDDEN
        return page.command_state(id_)

    def run_command(self, id_: str) -> None:
        if id_ == "new":
            self.new_tab()
        elif id_ == "open-session":
            self._browse_session()
        elif id_ == "close-tab":
            self.close_page()
        elif id_ == "next-tab":
            self._step_tab(1)
        elif id_ == "previous-tab":
            self._step_tab(-1)
        elif id_ == "exit":
            self.close()
        elif id_ == "keys":
            self.show_keys()
        elif id_ == "check-updates":
            self.updates.check(manual=True)
        elif id_ == "about":
            self._about()
        elif id_ == "follow-look":
            self._follow(not bool(self._config.get("look.follow_file_manager")))
        elif id_ == "syntax-default":
            self._set_syntax(not bool(self._config.get("view.syntax")))
        elif id_ == "keep-orig":
            self._config.set("save.backup", not bool(self._config.get("save.backup")))
        elif id_ == "updates-on-launch":
            self._config.set("updates.check_on_launch",
                             not bool(self._config.get("updates.check_on_launch")))
        else:
            page = self._page()
            if page is not None and hasattr(page, "run_command"):
                page.run_command(id_)
        page = self._page()
        if page is not None:
            self._page_changed(page)

    def fill_menu(self, name: str, menu: QMenu) -> None:
        if name in ("theme", "accent", "density"):
            names, labels = {"theme": (THEMES, THEME_LABELS), "accent": (ACCENTS, ACCENT_LABELS),
                             "density": (DENSITIES, DENSITY_LABELS)}[name]
            group = QActionGroup(menu)
            current = self._tokens[f"{name}_name"]
            for value in names:
                action = QAction(labels.get(value, value), menu)
                action.setCheckable(True)
                action.setChecked(value == current)
                action.triggered.connect(lambda _c=False, k=name, n=value: self._choose(k, n))
                group.addAction(action)
                menu.addAction(action)
            return
        if name == "colours":
            group = QActionGroup(menu)
            for value, label in (("classic", "Classic: every difference in red"),
                                 ("family", "Family: changed amber, left red, right green")):
                action = QAction(label, menu)
                action.setCheckable(True)
                action.setChecked(self._colours() == value)
                action.triggered.connect(lambda _c=False, v=value: self._set_colours(v))
                group.addAction(action)
                menu.addAction(action)
            return
        if name == "recent":
            pairs = [p for p in self._config.get("recent") if isinstance(p, list) and len(p) == 2]
            for left, right in pairs[:12]:
                action = menu.addAction(f"{ntpath.basename(left) or left}   vs   "
                                        f"{ntpath.basename(right) or right}")
                action.setToolTip(f"{left}\n{right}")
                action.triggered.connect(lambda _c=False, l=left, r=right: self.compare(l, r))
            return
        page = self._page()
        if page is not None and hasattr(page, "fill_menu"):
            page.fill_menu(name, menu)

    def _browse_session(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self._config.get("start.left_folder") or ""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a saved session", start, "File Compare session (*.fcsession)")
        if path:
            self.open_session(path.replace("/", "\\"))

    def _show_app_menu(self, at: QPoint) -> None:
        """The mark at the left of the title bar opens the Session menu."""
        menu = self.menubar.menus.get("Session")
        if menu is not None:
            menu.popup(at)

    def _set_syntax(self, on: bool) -> None:
        """The default for new tabs, and every open text tab now -- except
        one whose language was picked by hand, which keeps it."""
        self._config.set("view.syntax", bool(on))
        for index in range(self.pages.count()):
            page = self.pages.widget(index)
            if isinstance(page, CompareTab) and page.language in ("auto", "off"):
                page.set_language("auto" if on else "off")

    # -------------------------------------------------------------- updates

    def _update_available(self, release) -> None:
        """Found something newer. Nothing is downloaded until this is answered."""
        box = QMessageBox(self)
        box.setWindowTitle("Update")
        size = f" ({release.size / 1e6:.0f} MB)" if release.size else ""
        box.setText(f"File Compare {release.version} is available{size}. "
                    f"This is {__version__}.")
        box.setInformativeText("It downloads in the background and installs when you quit.")
        download = box.addButton("Download", QMessageBox.AcceptRole)
        skip = box.addButton("Skip this version", QMessageBox.RejectRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is download:
            self.updates.accept(release)
        elif box.clickedButton() is skip:
            self.updates.skip(release)

    def _update_progress(self, done: int, total: int) -> None:
        share = (done / total * 100) if total else 0
        self.statusBar().showMessage(f"Downloading update  {share:.0f}%", 2000)

    def _update_ready(self, release) -> None:
        self.flash(f"File Compare {release.version} installs when you quit")
        answer = QMessageBox.question(
            self, "Update ready",
            f"File Compare {release.version} is downloaded. Quit and install it now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.close()

    def show_keys(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Keys")
        box.setTextFormat(Qt.PlainText)
        box.setText(KEYS)
        box.setStyleSheet("QLabel { font-family: " + self._tokens["mono"] + "; }")
        box.exec()

    def _about(self) -> None:
        QMessageBox.about(self, "File Compare",
                          f"File Compare {__version__}\n\nSide-by-side compare for "
                          "Windows, from the same family as File Manager and "
                          "Redline PDF.")

    def _shortcuts(self) -> None:
        pairs = (
            ("Ctrl+T", self.new_tab),
            ("Ctrl+O", self._browse_session),
            ("Ctrl+W", self.close_page),
            ("Ctrl+Tab", lambda: self._step_tab(1)),
            ("Ctrl+Shift+Tab", lambda: self._step_tab(-1)),
            ("F1", self.show_keys),
        )
        for keys, slot in pairs:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(slot)

    def _step_tab(self, step: int) -> None:
        count = self.tabs.count()
        if count:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % count)

    # --------------------------------------------------------- dropping in

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [url.toLocalFile().replace("/", "\\") for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if len(paths) >= 2:
            event.acceptProposedAction()
            self.compare(paths[0], paths[1])
        elif len(paths) == 1 and savedsession.is_session(paths[0]):
            event.acceptProposedAction()
            self.open_session(paths[0])
        elif len(paths) == 1:
            event.acceptProposedAction()
            page = self.pages.currentWidget()
            if isinstance(page, CompareTab):
                # One file dropped on a comparison: it replaces the side it
                # was dropped on, in a new tab, so the pair it came from is
                # still there to go back to.
                x = page.mapFrom(self, event.position().toPoint()).x()
                side = 0 if x < page.width() / 2 else 1
                paths_now = [s.path for s in page.session.sides]
                paths_now[side] = paths[0]
                self.compare(*paths_now)
            else:
                self.new_tab(paths[0])

    # ---------------------------------------------------------------- frame

    def hit_parts(self, pos) -> tuple[bool, bool]:
        """For `winframe`: is `pos` the maximise button, and is it caption."""
        bar = self._titlebar
        if bar is None:
            return False, False
        local = bar.mapFrom(self, pos)
        return bar.max_button.geometry().contains(local), bar.is_caption(local)

    def set_max_hover(self, hot: bool) -> None:
        if self._titlebar is not None:
            self._titlebar.set_max_hover(hot)

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._frame is not None and not self._frame.active:
            self._frame.install()
            if self._frame.problem:
                self.flash(self._frame.problem)

    def nativeEvent(self, event_type, message):  # noqa: N802
        if self._frame is not None:
            answer = self._frame.handle(event_type, message)
            if answer is not None:
                return answer
        return super().nativeEvent(event_type, message)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange and self._titlebar is not None:
            self._titlebar.set_maximized(self.isMaximized())
        super().changeEvent(event)

    def bring_forward(self) -> None:
        """A second instance handed something over: come to the front."""
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _may_close(self, pages: list[QWidget]) -> bool:
        """Ask about unsaved edits in `pages`. True when closing can go on:
        nothing was unsaved, it was saved, or it was deliberately discarded."""
        from PySide6.QtCore import QEventLoop, QTimer

        dirty = [p for p in pages if isinstance(p, (CompareTab, MergeTab)) and p.session.dirty]
        for page in dirty:
            self.tabs.setCurrentIndex(self._index_of(page))
            box = QMessageBox(self)
            box.setWindowTitle("Unsaved changes")
            box.setText(f"{page.title().lstrip('* ')} has unsaved changes.")
            box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Save)
            answer = box.exec()
            if answer == QMessageBox.Cancel:
                return False
            if answer == QMessageBox.Save:
                if not page.save_all():
                    return False
                loop = QEventLoop()
                outcome = {"ok": False}

                def finished(ok: bool, loop=loop) -> None:
                    outcome["ok"] = ok
                    loop.quit()

                page.savesFinished.connect(finished)
                QTimer.singleShot(120_000, loop.quit)
                loop.exec()
                page.savesFinished.disconnect(finished)
                if not outcome["ok"] or page.session.dirty:
                    return False
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._may_close(self._pages()):
            event.ignore()
            return
        self._config.set("window.maximized", self.isMaximized())
        if not self.isMaximized():
            self._config.set("window.width", self.width())
            self._config.set("window.height", self.height())
        self._config.save()
        self.updates.shutdown()
        self._loader.shutdown()
        super().closeEvent(event)
