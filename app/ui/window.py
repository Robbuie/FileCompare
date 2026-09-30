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
from app.core import appearance
from app.core.config import Config
from app.core.loader import Loader
from app.core.rules import WHITESPACE, Rules
from app.core.session import Options, Session
from app.theme import sheet
from app.theme.tokens import ACCENT_LABELS, ACCENTS, DENSITIES, DENSITY_LABELS, THEME_LABELS, THEMES
from app.ui import glyphs, winframe
from app.ui.comparetab import CompareTab
from app.ui.starttab import StartTab
from app.ui.titlebar import TitleBar

KEYS = """\
Alt+Down / Alt+Up         next, previous difference
Home / End                first, last difference
Ctrl+Home / Ctrl+End      top, bottom of the file
Up, Down, PgUp, PgDn      scroll
Left / Right              scroll sideways
Tab                       the other side
Ctrl+U                    swap sides
Ctrl+R                    compare again from disk
Ctrl+I                    rules off and on
Ctrl+T                    new comparison
Ctrl+W                    close this tab
Ctrl+Tab / Ctrl+Shift+Tab next, previous tab
F1                        this list"""


def rules_from(config: Config) -> Rules:
    whitespace = config.get("compare.whitespace")
    patterns = config.get("compare.patterns")
    return Rules(
        whitespace=whitespace if whitespace in WHITESPACE else "none",
        case=bool(config.get("compare.case")),
        blank_lines=bool(config.get("compare.blank_lines")),
        patterns=tuple(p for p in patterns if isinstance(p, str)) if isinstance(patterns, list) else (),
    )


class MainWindow(QMainWindow):

    def __init__(self, config: Config, *, look: dict[str, str], look_source: str,
                 custom_frame: bool = True) -> None:
        super().__init__()
        self._config = config
        self._look = dict(look)
        self._look_source = look_source
        self._loader = Loader(self)
        self._tokens = sheet.tokens(**self._look)
        self._titlebar: TitleBar | None = None
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
        self.statusBar().addWidget(self._status_left, 1)
        self.statusBar().addPermanentWidget(self._status_right)
        self.statusBar().setSizeGripEnabled(False)

        if custom_frame:
            self._titlebar = TitleBar()
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
            column.addWidget(body, 1)
            self.setCentralWidget(root)
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self._frame = winframe.NativeFrame(self, glass=False, dark=self._is_dark())
        else:
            self.setCentralWidget(body)

        self._shortcuts()
        self.apply_look(self._look, self._look_source, save=False)

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
        self.tabs.setCurrentIndex(index)
        self.pages.setCurrentWidget(page)
        page.focus_view()
        return index

    def _index_of(self, page: QWidget) -> int:
        return self.pages.indexOf(page)

    def _tab_changed(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            page = self.pages.widget(index)
            self.pages.setCurrentIndex(index)
            page.focus_view()
            self._status_left.setText(getattr(page, "_last_status", ""))

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
        # The page leaves the stack before its tab leaves the strip: removing
        # the tab moves the current index, and `_tab_changed` reads the stack.
        index = self._index_of(page)
        self.pages.removeWidget(page)
        self.tabs.removeTab(index)
        page.deleteLater()
        if self.pages.count() == 0:
            self.new_tab()

    def new_tab(self, left: str = "", right: str = "") -> StartTab:
        page = StartTab((self._config.get("start.left_folder"),
                         self._config.get("start.right_folder")))
        page.set_paths(left, right)
        page.compareRequested.connect(lambda l, r, p=page: self._start_to_compare(p, l, r))
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
                      readonly: set[str] | None = None) -> CompareTab:
        options = Options(
            rules=rules_from(self._config),
            intraline=self._config.get("compare.intraline"),
            timeout=float(self._config.get("load.timeout")),
            max_bytes=int(float(self._config.get("load.max_mb")) * 1024 * 1024),
        )
        session = Session(self._loader, left, right, options=options, titles=titles,
                          readonly=readonly)
        tab = CompareTab(session, self._tokens)
        tab.titleChanged.connect(lambda t=tab: self._retitle(t))
        tab.status.connect(lambda text, t=tab: self._tab_status(t, text))
        session.start()
        return tab

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

    def open_request(self, request: Request) -> None:
        if request.error:
            self.flash(request.error)
            if not self.pages.count():
                self.new_tab()
            return
        if request.merge:
            self.flash("Three-way merge arrives in a later version; "
                       "showing mine against theirs.")
            self.compare(request.paths[0], request.paths[1], readonly={"left", "right"})
            return
        if len(request.paths) == 2:
            self.compare(request.paths[0], request.paths[1],
                         titles=(request.left_title, request.right_title),
                         readonly=request.readonly)
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
        self._tokens = sheet.apply(QApplication.instance(), **self._look)
        if self._titlebar is not None:
            self._titlebar.apply_tokens(self._tokens)
        if self._frame is not None:
            self._frame.set_dark(self._is_dark())
        self._new.setIcon(glyphs.icon("plus", colour=self._tokens["txt_1"],
                                      muted=self._tokens["txt_2"], size=14))
        for index in range(self.tabs.count()):
            button = self.tabs.tabButton(index, QTabBar.RightSide)
            if button is not None:
                button.setIcon(glyphs.icon("close", colour=self._tokens["txt_2"],
                                           muted=self._tokens["txt_2"], size=10))
        for page in self._pages():
            if isinstance(page, CompareTab):
                page.apply_tokens(self._tokens)
        where = "File Manager's look" if source == "file manager" else "own look"
        self._status_right.setText(
            f"{THEME_LABELS.get(self._tokens['theme_name'], '')}  ·  "
            f"{ACCENT_LABELS.get(self._tokens['accent_name'], '')}  ·  {where}")

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

    # ----------------------------------------------------------------- menu

    def _show_app_menu(self, at: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("New comparison\tCtrl+T", self.new_tab)
        menu.addAction("Close tab\tCtrl+W", self.close_page)
        menu.addSeparator()
        for key, label, names, labels in (
                ("theme", "Theme", THEMES, THEME_LABELS),
                ("accent", "Accent", ACCENTS, ACCENT_LABELS),
                ("density", "Density", DENSITIES, DENSITY_LABELS)):
            sub = menu.addMenu(label)
            group = QActionGroup(sub)
            current = self._tokens[f"{key}_name"]
            for name in names:
                action = QAction(labels.get(name, name), sub)
                action.setCheckable(True)
                action.setChecked(name == current)
                action.triggered.connect(lambda _c=False, k=key, n=name: self._choose(k, n))
                group.addAction(action)
                sub.addAction(action)
        follow = menu.addAction("Follow File Manager's look")
        follow.setCheckable(True)
        follow.setChecked(bool(self._config.get("look.follow_file_manager")))
        follow.triggered.connect(self._follow)
        menu.addSeparator()
        menu.addAction("Keys\tF1", self.show_keys)
        menu.addAction("About File Compare", self._about)
        menu.addSeparator()
        menu.addAction("Exit", self.close)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(at)

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
            ("Ctrl+O", self.new_tab),
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
        elif len(paths) == 1:
            event.acceptProposedAction()
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

    def closeEvent(self, event) -> None:  # noqa: N802
        self._config.set("window.maximized", self.isMaximized())
        if not self.isMaximized():
            self._config.set("window.width", self.width())
            self._config.set("window.height", self.height())
        self._config.save()
        self._loader.shutdown()
        super().closeEvent(event)
