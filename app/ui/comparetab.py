"""One comparison tab: the toolbar, a header over each side, and the view.

The tab draws a `core.session.Session` and turns clicks into calls on it. It
never reads a file: which side is loading, which failed and why, and what the
comparison found all arrive through `Session.changed`.

When the two sides are not two text files -- still loading, one missing, two
folders, a binary pair -- the view is swapped for a message that says so in
words. A blank pane is never an answer.

Editing arrives here as commands from the view (keys, the gutter's arrows,
the line editor) and leaves as calls on the session, which owns the text.
The tab's part is translating rows into lines, asking before anything is
lost -- a reload over edits, an overwrite of a file somebody else changed --
and saying why when an edit is not possible.
"""

from __future__ import annotations

import ntpath
import re

from PySide6.QtCore import QDir, QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import folders as F
from app.core import formats, siblings, syntax
from app.core import session as core
from app.core.diff import align
from app.core.folders import SHOWS as F_SHOWS
from app.core.rules import WHITESPACE, WHITESPACE_LABELS, Rules
from app.io import load as io_load
from app.io.load import LABELS
from app.io.longpath import display
from app.ui import glyphs
from app.ui.commands import HIDDEN, State
from app.ui.diffsidebar import DiffSidebar, Entry
from app.ui.diffview import DiffView
from app.ui.folderview import FolderView
from app.ui.hexview import HexView
from app.ui.rungview import RungView
from app.ui.imageview import ImageView
from app.ui.tableview import TableView

#: What the View switch offers, in order.
VIEW_LABELS = {"text": "Text", "rungs": "Rungs", "table": "Table", "hex": "Hex",
               "image": "Image"}


def _syntax_job(lines: list[str], key: str):
    """In the loader: the spans, returned with the list they were made from
    so a late answer for lines no longer on screen is recognised and dropped."""
    return lines, syntax.highlight(lines, key)


def _workbook_job(left: bytes, right: bytes, options):
    """In the loader: both workbooks read (once each; `workbook.read` keeps
    them), the sheet chosen, and compared like two CSV files."""
    from dataclasses import replace

    from app.core import tables, workbook

    empty = workbook.Book([], {}, {})
    books = [workbook.read(data, formulas=options.formulas) if data else empty
             for data in (left, right)]
    states = workbook.sheet_states(*books)
    sheet = options.sheet if any(s.name == options.sheet for s in states) \
        else workbook.first_different(states)
    sides = [workbook.table(book, sheet, header=options.header) for book in books]
    notes = sorted({book.cut[sheet] for book in books if sheet in book.cut})
    result = tables.compare(sides[0], sides[1], replace(options, sheet=sheet))
    return result, states, sheet, "; ".join(notes)


def _table_job(left: list[str], right: list[str], options):
    from app.core import tables

    return tables.compare(tables.parse("\n".join(left), header=options.header),
                          tables.parse("\n".join(right), header=options.header), options)

#: What a side can be saved as, from its menu: (label, encoding, mark).
SAVE_ENCODINGS = (
    ("UTF-8", "utf-8", False),
    ("UTF-8 with BOM", "utf-8", True),
    ("Windows-1252", "cp1252", False),
    ("UTF-16 LE with BOM", "utf-16-le", True),
    ("UTF-16 BE with BOM", "utf-16-be", True),
)


class SideHead(QWidget):
    """The strip over one side: its path box, what was read, and trouble.

    A path box as in Beyond Compare (folder compare since 1.15, files since
    1.18): type or paste a path and press Enter, pick a recent one, browse,
    or drop one on it. Only that side changes; the other stays as it is and
    is not read again. Under a file's path, a line of what was read -- when
    it was written, its size, encoding, line endings and lines -- which opens
    the side's menu (save, read as, encodings).
    """

    retry = Signal()
    menuRequested = Signal()
    #: The path this side should show now (a folder since 1.15, a file 1.18).
    pathChosen = Signal(str)
    browseRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "sidehead")
        self.setAttribute(Qt.WA_StyledBackground, True)
        #: A title given on the command line (`--left-title`), shown before
        #: the path when there is one.
        self.name = QLabel()
        self.name.setProperty("role", "sidename")
        self.name.hide()
        self.facts = QToolButton()
        self.facts.setProperty("role", "sidefacts")
        self.facts.setFocusPolicy(Qt.NoFocus)
        self.facts.setToolTip("When it was written, its size, encoding and line endings. "
                              "Click for saving and reading options for this side.")
        self.facts.clicked.connect(lambda _c=False: self.menuRequested.emit())
        self.state = QLabel()
        self.state.setProperty("role", "sidestate")
        self.again = QToolButton()
        self.again.setText("Retry")
        self.again.setProperty("role", "retry")
        self.again.setFocusPolicy(Qt.NoFocus)
        self.again.clicked.connect(self.retry)
        self.again.hide()

        self.up = QToolButton()
        self.up.setProperty("role", "nav")
        self.up.setProperty("glyph", "up")
        self.up.setFocusPolicy(Qt.NoFocus)
        self.up.setToolTip("Up one folder on this side; the other side stays")
        self.up.clicked.connect(lambda _c=False: self._go_up())
        self.up.hide()
        self.field = QLineEdit()
        self.field.setProperty("role", "pathbox")
        self.field.setPlaceholderText("Type or paste a file and press Enter")
        self.field.setToolTip("This side's file. Type or paste another and press Enter to "
                              "compare it with the other side, or drop one here.")
        self.field.returnPressed.connect(lambda: self.pathChosen.emit(self.field.text()))
        self.field.installEventFilter(self)
        self.places = QToolButton()
        self.places.setProperty("role", "nav")
        self.places.setProperty("glyph", "chevron_down")
        self.places.setFocusPolicy(Qt.NoFocus)
        self.places.setToolTip("Recent files")
        self.places.setPopupMode(QToolButton.InstantPopup)
        places = QMenu(self.places)
        places.aboutToShow.connect(lambda: self._fill_places(places))
        self.places.setMenu(places)
        self.browse = QToolButton()
        self.browse.setProperty("role", "nav")
        self.browse.setProperty("glyph", "open")
        self.browse.setFocusPolicy(Qt.NoFocus)
        self.browse.setToolTip("Choose a file for this side")
        self.browse.clicked.connect(lambda _c=False: self.browseRequested.emit())

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        top.addWidget(self.up)
        top.addWidget(self.name)
        top.addWidget(self.field, 1)
        top.addWidget(self.places)
        top.addWidget(self.browse)
        under = QHBoxLayout()
        under.setContentsMargins(0, 0, 0, 0)
        under.setSpacing(8)
        under.addWidget(self.facts)
        under.addStretch(1)
        under.addWidget(self.state)
        under.addWidget(self.again)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 4, 8, 2)
        box.setSpacing(1)
        box.addLayout(top)
        box.addLayout(under)
        self._top = top
        self._under = under
        self.folder_mode = False
        self.path = ""
        self.history: list[str] = []
        self.setAcceptDrops(True)

    # ------------------------------------------------- folder compare (1.15)

    def set_folder_mode(self) -> None:
        """A folder's path box: Up appears, the line of facts goes (a folder
        has none) and the state moves up beside the box. Once a folder tab,
        always one, so nothing has to undo this."""
        if self.folder_mode:
            return
        self.folder_mode = True
        self.up.show()
        self.facts.hide()
        self.name.hide()
        self._under.removeWidget(self.state)
        self._under.removeWidget(self.again)
        self._top.addWidget(self.state)
        self._top.addWidget(self.again)
        self.field.setPlaceholderText("Type or paste a folder and press Enter")
        self.field.setToolTip("This side's folder. Type or paste another and press Enter "
                              "to compare it with the other side, or drop a folder here.")
        self.places.setToolTip("Parent folders and recent folders")
        self.browse.setToolTip("Choose a folder for this side")
        self.layout().setContentsMargins(6, 4, 8, 4)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        ratio = float(self.devicePixelRatioF() or 1.0)
        for button in (self.up, self.places, self.browse):
            button.setIcon(glyphs.icon(button.property("glyph"), colour=tokens["txt_1"],
                                       muted=tokens["txt_2"], size=16, ratio=ratio))

    def show_folder(self, path: str, state: str, error: str) -> None:
        """The folder this side shows and how its walk is going."""
        self.path = path
        shown = display(path)
        if not self.field.hasFocus() or not self.field.isModified():
            self.field.setText(shown)
            self.field.setModified(False)
        self.field.setToolTip(shown or "No folder chosen")
        self.up.setEnabled(bool(F.ancestors(path)))
        text, tone, again = "", "", False
        if state == "walking":
            text = "Reading..."
        elif state in ("failed", "not answering"):
            text, tone, again = error or "Could not be read", "bad", True
        self.state.setText(text)
        self.state.setToolTip(text)
        self.state.setProperty("state", tone)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.again.setText("Retry")
        self.again.setVisible(again)

    def _go_up(self) -> None:
        above = F.ancestors(self.path)
        if above:
            self.pathChosen.emit(above[0])

    def _fill_places(self, menu: QMenu) -> None:
        menu.clear()
        above = F.ancestors(self.path) if self.folder_mode else []
        if above:
            menu.addSection("Up")
            for path in above:
                menu.addAction(display(path), lambda p=path: self.pathChosen.emit(p))
        recent = [p for p in self.history if not F.same_path(p, self.path)][:12]
        if recent:
            menu.addSection("Recent")
            for path in recent:
                menu.addAction(display(path), lambda p=path: self.pathChosen.emit(p))
        if not above and not recent:
            menu.addAction("No parent or recent folders" if self.folder_mode
                           else "No recent files").setEnabled(False)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Escape in the path box puts back the path being shown."""
        if watched is self.field and event.type() == QEvent.KeyPress \
                and event.key() == Qt.Key_Escape:
            self.field.setText(display(self.path))
            self.field.setModified(False)
            self.field.clearFocus()
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if _dropped_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        path = _dropped_path(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.pathChosen.emit(path)
        else:
            super().dropEvent(event)

    def show_side(self, side: core.Side, *, encoding_changed: bool = False) -> None:
        self.path = side.path
        path = display(side.path)
        if not self.field.hasFocus() or not self.field.isModified():
            self.field.setText(path)
            self.field.setModified(False)
            # The end, where the file's name is, is the part worth seeing.
            self.field.setCursorPosition(len(path))
        self.field.setToolTip(path or "Nothing chosen: type a path, browse, or drop a file")
        self.name.setText(side.title)
        self.name.setVisible(bool(side.title))
        facts = ""
        if side.loaded is not None and side.state == core.READY and side.doc is not None:
            # What a save would write, which after an edit or a change from
            # this menu is not what was read.
            label = LABELS.get(side.encoding, side.encoding) + (" BOM" if side.bom else "")
            eol = _eol_now(side.doc.endings) or side.loaded.eol
            parts = []
            if side.loaded.mtime:
                import datetime as _dt

                parts.append(_dt.datetime.fromtimestamp(side.loaded.mtime)
                             .strftime("%Y-%m-%d %H:%M"))
            if side.path:
                parts.append(f"{side.loaded.size:,} bytes")
            parts.append(label + (" (on save)" if encoding_changed else ""))
            if eol:
                parts.append(eol)
            count = len(side.doc.lines)
            parts.append(f"{count:,} line{'s' if count != 1 else ''}")
            facts = "   ".join(parts)
        elif side.loaded is not None and side.state == core.READY:
            facts = side.loaded.facts
        if side.readonly and facts:
            facts += "   read-only"
        self.facts.setText(facts)
        self.facts.setVisible(bool(facts))
        bad = side.state in (core.FAILED, core.SLOW)
        state, tone = "", ""
        again = ""
        if side.state == core.LOADING:
            state = "Reading..."
        elif bad:
            state, tone, again = side.error, "bad", "Retry"
        elif side.saving:
            state = "Saving..."
        elif side.save_error:
            state, tone = side.save_error, "bad"
        elif side.stale:
            state, tone, again = "Changed on disk", "bad", "Reload"
        elif side.dirty:
            state, tone = "Modified", "dirty"
        self.state.setText(state)
        self.state.setProperty("state", tone)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.again.setText(again or "Retry")
        self.again.setVisible(bool(again))

    def set_focused(self, focused: bool) -> None:
        # "active", not "focus": QWidget already has a read-only `focus`
        # property, so setting one by that name did nothing and the accent
        # line under the focused side never showed (fixed 1.14).
        value = "true" if focused else "false"
        if self.property("active") != value:
            self.setProperty("active", value)
            self.style().unpolish(self)
            self.style().polish(self)


def _dropped_path(mime) -> str:
    """The first local path in a drag, or "". Strings only: whether it is a
    folder is the walk's to find out, off the UI thread."""
    if mime is None or not mime.hasUrls():
        return ""
    for url in mime.urls():
        if url.isLocalFile():
            return QDir.toNativeSeparators(url.toLocalFile())
    return ""


def _eol_now(endings: list[str]) -> str:
    kinds = {e for e in endings if e}
    if not kinds:
        return ""
    if len(kinds) > 1:
        return "mixed"
    return {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[kinds.pop()]


class FindBar(QWidget):
    """Ctrl+F: a line of text to find in both sides, and where the matches are.

    Matches are marked in both panes while the bar is open. Enter and F3 go to
    the next one, Shift with either to the previous; Escape closes the bar and
    takes the marks with it.
    """

    changed = Signal()
    step = Signal(int)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "findbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.field = QLineEdit()
        self.field.setProperty("role", "findfield")
        self.field.setPlaceholderText("Find in both sides")
        self.field.textChanged.connect(lambda _t: self.changed.emit())
        self.case = QPushButton("Match case")
        self.regex = QPushButton("Regex")
        for button in (self.case, self.regex):
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.toggled.connect(lambda _c: self.changed.emit())
        self.count = QLabel()
        self.count.setProperty("role", "count")
        self.previous = QToolButton()
        self.next = QToolButton()
        self.close_button = QToolButton()
        for button, glyph, tip in ((self.previous, "diff_prev", "Previous match (Shift+F3)"),
                                   (self.next, "diff_next", "Next match (F3)"),
                                   (self.close_button, "close", "Close (Escape)")):
            button.setProperty("role", "nav")
            button.setProperty("glyph", glyph)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.NoFocus)
        self.previous.clicked.connect(lambda _c=False: self.step.emit(-1))
        self.next.clicked.connect(lambda _c=False: self.step.emit(1))
        self.close_button.clicked.connect(lambda _c=False: self.closed.emit())
        segments = QWidget()
        segments.setProperty("role", "segments")
        segments.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(segments)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(2)
        seg.addWidget(self.case)
        seg.addWidget(self.regex)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(self.field, 1)
        box.addWidget(segments)
        box.addWidget(self.previous)
        box.addWidget(self.next)
        box.addWidget(self.count)
        box.addWidget(self.close_button)
        self.hide()

    def pattern(self) -> tuple[re.Pattern | None, str]:
        """The compiled search, and a problem to show if it did not compile."""
        text = self.field.text()
        if not text:
            return None, ""
        flags = 0 if self.case.isChecked() else re.IGNORECASE
        try:
            return re.compile(text if self.regex.isChecked() else re.escape(text), flags), ""
        except re.error as exc:
            return None, f"Not a pattern: {exc}"

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        if key == Qt.Key_Escape:
            self.closed.emit()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F3):
            self.step.emit(-1 if shift else 1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class Message(QWidget):
    """What stands in for the view when there is nothing to draw in it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel()
        self.title.setProperty("role", "starttitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.body = QLabel()
        self.body.setProperty("role", "note")
        self.body.setAlignment(Qt.AlignCenter)
        self.body.setWordWrap(True)
        box = QVBoxLayout(self)
        box.addStretch(1)
        box.addWidget(self.title)
        box.addSpacing(6)
        box.addWidget(self.body)
        box.addStretch(2)
        box.setContentsMargins(60, 20, 60, 20)

    def say(self, title: str, body: str = "") -> None:
        self.title.setText(title)
        self.body.setText(body)


class Handoff(QWidget):
    """The page for a pair a sibling application compares better."""

    launch = Signal()
    anyway = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel()
        self.title.setProperty("role", "starttitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.body = QLabel()
        self.body.setProperty("role", "note")
        self.body.setAlignment(Qt.AlignCenter)
        self.body.setWordWrap(True)
        self.go = QPushButton()
        self.go.setProperty("role", "primary")
        self.go.clicked.connect(lambda _c=False: self.launch.emit())
        self.here = QPushButton("Compare here anyway")
        self.here.clicked.connect(lambda _c=False: self.anyway.emit())
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.go)
        buttons.addWidget(self.here)
        buttons.addStretch(1)
        box = QVBoxLayout(self)
        box.addStretch(1)
        box.addWidget(self.title)
        box.addSpacing(6)
        box.addWidget(self.body)
        box.addSpacing(14)
        box.addLayout(buttons)
        box.addStretch(2)
        box.setContentsMargins(60, 20, 60, 20)

    def offer(self, sibling: siblings.Sibling) -> None:
        self.title.setText(f"This pair compares best in {sibling.name}")
        self.body.setText(sibling.does)
        self.go.setText(f"Open both in {sibling.name}")


class CompareTab(QWidget):
    """Emits `titleChanged` when the tab's label should change and `status`
    with a line for the window's status bar."""

    titleChanged = Signal()
    status = Signal(str)
    #: A setting to keep for next time: (config key, value).
    setting = Signal(str, object)
    #: Every save the tab asked for has finished, successfully or not.
    savesFinished = Signal(bool)
    #: A pair to open in a tab of its own (from folder compare).
    openPair = Signal(str, str)
    openExtracted = Signal(str, str, object)
    #: 1.17: something the window's toolbar or menus show has changed.
    commandsChanged = Signal()
    #: 1.18: a side was pointed at another file: (left, right), to remember.
    pairChanged = Signal(str, str)

    def __init__(self, session: core.Session, tokens: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._tokens = tokens
        self._toolbar()
        self._shown_result = None
        self._matches: list[tuple[int, int]] = []
        self._pending_saves: set[int] = set()
        self._saves_ok = True
        #: The other modes' views, made the first time the pair turns out to
        #: need one. None until then.
        self.folders: FolderView | None = None
        #: 1.10: the session file this tab was opened from, if any; saving
        #: the session again offers the same file.
        self.session_file = ""
        self.sibling = siblings.for_pair(session.sides[0].path, session.sides[1].path)
        self._launch_request = 0
        #: "auto", or what the View switch (or --mode) chose.
        self.mode = session.options.mode if session.options.mode in VIEW_LABELS else "auto"
        # 1.16: a Logix pair's rungs drawn as ladder.
        self.rungs = RungView()
        self.rungs.currentChanged.connect(self._update_position)
        self.rungs.openRow.connect(self._rung_to_text)
        self.rungs.command.connect(self._command)
        self._rungs_for = None
        self.hex = HexView()
        self.hex.currentChanged.connect(self._update_position)
        self.hex.command.connect(self._command)
        self.images = ImageView()
        self.images.toleranceChanged.connect(self._measure_images)
        self.images.command.connect(self._command)
        self.table = TableView()
        self.table.optionsChanged.connect(lambda _o: self._measure_table())
        self.table.status.connect(self.status)
        self.table.command.connect(self._command)
        self._table_request = 0
        self._table_for = None
        self._hex_request = self._image_request = 0
        #: 1.1: "auto" (by the file's name), "off", or a language key for
        #: both sides; and the loader requests colouring each side.
        self.language = session.options.syntax
        self._syntax_requests = [0, 0]
        self._hex_for = self._image_for = None
        self.handoff = Handoff()
        self.handoff.launch.connect(self._launch_sibling)
        self.handoff.anyway.connect(self._compare_here)
        session._loader.finished.connect(self._loader_answer)

        self.view = DiffView()
        self.view.currentChanged.connect(self._update_position)
        self.view.command.connect(self._command)
        self.view.copyBlock.connect(self._copy_block)
        self.view.copyRows.connect(self._copy_rows)
        self.view.menuRequested.connect(self._text_menu)
        self.view.edited.connect(self._edited)
        self.find = FindBar()
        self.find.changed.connect(self._find_changed)
        self.find.step.connect(self._find_step)
        self.find.closed.connect(self._find_closed)
        self.message = Message()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.message)
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.handoff)
        self.stack.addWidget(self.hex)
        self.stack.addWidget(self.rungs)
        self.stack.addWidget(self.images)
        self.stack.addWidget(self.table)

        self.heads = (SideHead(), SideHead())
        self._file_history = list(session.options.file_history)
        for index, head in enumerate(self.heads):
            head.retry.connect(lambda i=index: self._reload_side(i))
            head.menuRequested.connect(lambda i=index: self._side_menu(i))
            head.history = self._file_history
            head.pathChosen.connect(lambda path, i=index: self._path_chosen(i, path))
            head.browseRequested.connect(lambda i=index: self._browse_side(i))
        self.view.set_show(session.options.show, session.options.context)
        self.view.set_details(session.options.details)
        self.view.set_layout(session.options.layout)
        heads = QHBoxLayout()
        heads.setContentsMargins(0, 0, 0, 0)
        heads.setSpacing(0)
        heads.addWidget(self.heads[0], 1)
        spacer = QWidget()
        spacer.setProperty("role", "sidehead")
        spacer.setAttribute(Qt.WA_StyledBackground, True)
        self._head_spacer = spacer
        heads.addWidget(spacer)
        heads.addWidget(self.heads[1], 1)

        card = QFrame()
        card.setProperty("role", "card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(1, 1, 1, 1)
        inner.setSpacing(0)
        inner.addLayout(heads)
        inner.addWidget(self.location)
        inner.addWidget(self.stack, 1)
        # 1.19: every difference in a list beside the card.
        self.sidebar = DiffSidebar()
        self.sidebar.goTo.connect(self._go_block)
        self._sidebar_on = bool(session.options.sidebar)
        self._outline_for = None
        self._sections: tuple = (None, None)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.sidebar)
        self.split.addWidget(card)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([270, 1100])
        self.sidebar.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 0)
        outer.setSpacing(6)
        outer.addWidget(self.find)
        outer.addWidget(self.split, 1)

        session.changed.connect(self.refresh)
        session.saved.connect(self._saved)
        self.apply_tokens(tokens)
        self.refresh()

    # ------------------------------------------------------------- toolbar

    def _toolbar(self) -> None:
        """Before 1.17 a row of bare icons over the card. The commands moved
        to the window's labelled toolbar and its menus, which ask
        `command_state` and call `run_command`; what stays is the line that
        says where you are, which the window shows in its status bar."""
        self.count = QLabel()
        self.count.setProperty("role", "count")
        # 1.19: where the cursor is in the file's outline, over the panes.
        self.location = QLabel()
        self.location.setProperty("role", "location")
        self.location.hide()

    def _fill_whitespace_menu(self, menu: QMenu) -> None:
        rules = self.session.rules
        for value in WHITESPACE:
            action = menu.addAction(WHITESPACE_LABELS[value])
            action.setCheckable(True)
            action.setChecked(rules.whitespace == value)
            action.triggered.connect(
                lambda _c=False, v=value: self._change_rules(whitespace=v))

    def _fill_patterns_menu(self, menu: QMenu) -> None:
        for pattern in self.session.rules.patterns:
            menu.addAction(pattern).setEnabled(False)

    def _change_rules(self, **changes) -> None:
        from dataclasses import replace

        rules = replace(self.session.rules, enabled=True, **changes)
        self.session.set_rules(rules)

    def _set_intraline(self, mode: str) -> None:
        self.session.set_intraline(mode)
        self.view.set_mode(mode)
        self._sync_toggles()

    def _command(self, name: str) -> None:
        s = self.session
        side = self.view.focused_side
        if name == "swap":
            s.swap()
            if self.folders is not None:
                self.folders.session.swap()
        elif name == "reload":
            self.reload()
        elif name == "rules":
            s.set_rules(s.rules.toggled())
        elif name in ("copy-left", "copy-right"):
            to_side = 0 if name == "copy-left" else 1
            picked = self.view.state.copyable()
            if picked is not None:
                # 1.13: two or more rows selected are what gets copied.
                self._copy_rows(picked[0], picked[1], to_side)
            elif self.view.state.current is not None:
                self._copy_block(self.view.state.current, to_side)
        elif name in ("copy-all-left", "copy-all-right"):
            to_side = 0 if name == "copy-all-left" else 1
            if self._can_edit(to_side):
                s.copy_all(to_side)
        elif name == "undo":
            if not s.undo(side):
                self.status.emit("Nothing to undo on this side")
        elif name == "redo":
            if not s.redo(side):
                self.status.emit("Nothing to redo on this side")
        elif name == "save":
            self.save_side(side)
        elif name == "save-all":
            self.save_all()
        elif name == "find":
            self.open_find()
        elif name == "find-next":
            self._find_step(1)
        elif name == "find-previous":
            self._find_step(-1)
        elif name == "copy-text":
            text = self.view.selected_text()
            QApplication.clipboard().setText(text)
            count = len(self.view.selected_lines()[1])
            self.status.emit(f"Copied {count} line{'s' if count != 1 else ''}")
        elif name == "report":
            self.save_report()
        elif name == "save-session":
            self.save_session()
        elif name == "align":
            self._align()
        elif name == "unalign":
            self._unalign()
        elif name == "move-partner":
            if not self.view.go_to_partner():
                self.status.emit("This difference is not a moved block")
        elif name == "select-all":
            if self.view.state.rows:
                self.view.select_rows(side, 0, len(self.view.state.rows))
        elif name == "toggle-unified":
            self.run_command("layout-sbs" if self.view.state.layout == "unified"
                             else "layout-unified")
        elif name == "sidebar":
            self.run_command("sidebar")
        elif name in ("edit", "insert-line", "delete-lines", "align") \
                and self.view.state.layout != "sbs":
            self.status.emit("Editing and aligning are in Side by side (View > Side by side)")
        elif name == "edit":
            if self._can_edit(side) and self._current_or_say():
                self.view.begin_edit()
        elif name == "insert-line":
            # Bound to Shift+Enter since 1.0 and never handled until 1.13: an
            # empty line below the cursor's line on the focused side.
            if self._can_edit(side) and self._current_or_say() and s.result.rows:
                row = min(self.view.state.cursor, len(s.result.rows) - 1)
                _first, stop = align.side_range(s.result.rows, row, row + 1, side)
                s.replace_lines(side, stop, stop, [""])
        elif name == "delete-lines":
            if self._can_edit(side) and self._current_or_say():
                lo, hi = self.view.state.selection()
                first, stop = align.side_range(s.result.rows, lo, hi, side)
                if stop > first:
                    s.replace_lines(side, first, stop, [])

    def save_report(self) -> None:
        """Ctrl+Shift+H: the comparison as an HTML report or a unified patch."""
        from app.core import report
        from app.io import save as io_save

        s = self.session
        if s.result is None or s.kind != core.TEXT:
            self.status.emit("A report needs a text comparison")
            return
        names = tuple(ntpath.basename(display(side.path)) or "untitled" for side in s.sides)
        start = ntpath.join(ntpath.dirname(display(s.sides[0].path)),
                            f"{ntpath.splitext(names[0])[0]} vs {ntpath.splitext(names[1])[0]}.html")
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save the comparison", start,
            "HTML report (*.html);;Unified patch (*.patch *.diff)")
        if not path:
            return
        path = QDir.toNativeSeparators(path)
        left, right = s.result_lines
        if path.lower().endswith((".patch", ".diff")) or "patch" in chosen.lower():
            text = report.unified(s.result, left, right, names)
        else:
            text = report.html_report(s.result, left, right, names=names,
                                      rules=s.rules.describe(),
                                      note=s.format_note if s.structure else "")
        s._loader.submit(io_save.save, path, text.encode("utf-8"))
        self.status.emit(f"Saving {ntpath.basename(path)}")

    def saved_session(self):
        """This comparison's setup, for a session file (1.10)."""
        from app.core.savedsession import Saved

        s = self.session
        saved = Saved(
            left=s.sides[0].path, right=s.sides[1].path,
            titles=(s.sides[0].title, s.sides[1].title),
            readonly=tuple(name for name, side in zip(("left", "right"), s.sides)
                           if side.readonly),
            mode=self.mode,
            rules=s.rules,
            intraline=s.options.intraline,
            structure=s.structure,
            pins=list(s.pins),
        )
        if self.folders is not None:
            folder = self.folders.session
            saved.folder_mask = self.folders.mask.text()
            saved.folder_show = self.folders.model.show
            saved.folder_hour = folder.hour
            saved.folder_by_content = folder.by_content
            saved.folder_archives = folder.archives
        return saved

    def save_session(self) -> None:
        """Ctrl+Alt+S: this comparison's setup as a .fcsession file."""
        from app.core import savedsession
        from app.io import save as io_save

        s = self.session
        names = tuple(ntpath.basename(display(side.path).rstrip("\\")) or "untitled"
                      for side in s.sides)
        folder = ntpath.dirname(display(s.sides[0].path).rstrip("\\"))
        start = self.session_file or ntpath.join(
            folder, f"{ntpath.splitext(names[0])[0]} vs "
                    f"{ntpath.splitext(names[1])[0]}{savedsession.EXTENSION}")
        path, _chosen = QFileDialog.getSaveFileName(
            self, "Save this comparison as a session", start,
            f"File Compare session (*{savedsession.EXTENSION})")
        if not path:
            return
        path = QDir.toNativeSeparators(path)
        if not savedsession.is_session(path):
            path += savedsession.EXTENSION
        text = savedsession.dumps(self.saved_session())
        s._loader.submit(io_save.save, path, text.encode("utf-8"))
        self.session_file = path
        self.status.emit(f"Saved the session as {ntpath.basename(path)}; open it to compare "
                         "the same way again")

    def _can_edit(self, index: int) -> bool:
        side = self.session.sides[index]
        if side.editable:
            return True
        self.status.emit(side.why_not_editable or "This side cannot be edited")
        return False

    def _current_or_say(self) -> bool:
        if self.session.current:
            return True
        self.status.emit("Still comparing after the last edit; try again in a moment")
        return False

    def _copy_block(self, block: int, to_side: int) -> None:
        if self._can_edit(to_side) and self._current_or_say():
            self.session.copy_block(block, to_side)

    def _copy_rows(self, first: int, stop: int, to_side: int) -> None:
        if self._can_edit(to_side) and self._current_or_say():
            if self.session.copy_rows(first, stop, to_side):
                count = stop - first
                self.status.emit(f"Copied {count} row{'s' if count != 1 else ''} to the "
                                 + ("left" if to_side == 0 else "right"))

    def _text_menu(self, point) -> None:
        """Right-click in a text pane (1.13): the copies first, Beyond Compare's
        order, then editing the lines, then the rest."""
        s = self.session
        state = self.view.state
        if s.kind != core.TEXT or s.result is None:
            return
        menu = QMenu(self)
        names = ("left", "right")
        picked = state.copyable()
        block = state.current if state.current is not None and \
            state.current < len(state.blocks) else None
        row = state.cursor
        for to_side in (0, 1):
            arrow = "Alt+Left" if to_side == 0 else "Alt+Right"
            editable = s.sides[to_side].editable
            if picked is not None:
                count = picked[1] - picked[0]
                action = menu.addAction(f"Copy {count} selected rows to the {names[to_side]}"
                                        f"\t{arrow}",
                                        lambda t=to_side, p=picked: self._copy_rows(p[0], p[1], t))
                action.setEnabled(editable)
                continue
            if block is not None and state.blocks[block].start <= row < state.blocks[block].end:
                action = menu.addAction(f"Copy this difference to the {names[to_side]}\t{arrow}",
                                        lambda t=to_side, b=block: self._copy_block(b, t))
                action.setEnabled(editable)
                b = state.blocks[block]
                if b.end - b.start > 1:
                    action = menu.addAction(f"Copy just this line to the {names[to_side]}",
                                            lambda t=to_side, r=row: self._copy_rows(r, r + 1, t))
                    action.setEnabled(editable)
        if not menu.isEmpty():
            menu.addSeparator()
        side = self.view.focused_side
        editable = s.sides[side].editable
        menu.addAction("Edit these lines\tF2", lambda: self._command("edit")).setEnabled(editable)
        menu.addAction("Delete these lines\tDel",
                       lambda: self._command("delete-lines")).setEnabled(editable)
        menu.addAction("Insert a line below\tShift+Enter",
                       lambda: self._command("insert-line")).setEnabled(editable)
        menu.addSeparator()
        menu.addAction("Copy text\tCtrl+C", lambda: self._command("copy-text"))
        menu.addAction("Select all\tCtrl+A", lambda: self._command("select-all"))
        menu.addSeparator()
        menu.addAction("Align with a line on the other side\tCtrl+L",
                       lambda: self._command("align"))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(point)

    def _edited(self, side: int, lo: int, hi: int, text: str) -> None:
        s = self.session
        if not self._current_or_say():
            return
        first, stop = align.side_range(s.result.rows, lo, hi, side)
        lines = text.split("\n") if text else []
        if not s.replace_lines(side, first, stop, lines):
            if not s.sides[side].editable:
                self._can_edit(side)

    # -------------------------------------------------------------- saving

    def save_side(self, index: int, *, force: bool = False) -> bool:
        side = self.session.sides[index]
        if side.doc is None:
            return False
        if not side.path:
            return self.save_side_as(index)
        if not side.editable:
            if side.readonly or (side.loaded is not None and side.loaded.lossy):
                return self.save_side_as(index)
            return False
        if not side.dirty and not self.session.encoding_changed(index) and not force:
            self.status.emit("No changes to save on this side")
            return False
        if self.session.save(index, force=force):
            self._pending_saves.add(index)
            return True
        return False

    def save_side_as(self, index: int) -> bool:
        side = self.session.sides[index]
        if side.doc is None:
            return False
        path, _filter = QFileDialog.getSaveFileName(self, "Save as", side.path)
        if not path:
            return False
        path = QDir.toNativeSeparators(path)
        if self.session.save(index, path=path):
            self._pending_saves.add(index)
            return True
        return False

    def save_all(self) -> bool:
        """Every side with unsaved edits. True if any save started."""
        started = False
        self._saves_ok = True
        for index, side in enumerate(self.session.sides):
            if side.dirty and side.editable:
                started = self.save_side(index) or started
        if not started:
            self.status.emit("No changes to save")
        return started

    def _saved(self, index: int, result) -> None:
        self._pending_saves.discard(index)
        name = ntpath.basename(display(result.path))
        if result.ok:
            extra = f"  ·  backup {ntpath.basename(result.backup)}" if result.backup else ""
            self.status.emit(f"Saved {name}{extra}")
        elif result.conflict:
            box = QMessageBox(self)
            box.setWindowTitle("Changed on disk")
            box.setText(f"{name} changed on disk after it was read.")
            box.setInformativeText("Overwriting replaces what is on disk now with this side. "
                                   "Save as keeps both.")
            overwrite = box.addButton("Overwrite", QMessageBox.DestructiveRole)
            elsewhere = box.addButton("Save as...", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is overwrite:
                self.save_side(index, force=True)
                return
            if box.clickedButton() is elsewhere and self.save_side_as(index):
                return
            self._saves_ok = False
        else:
            self._saves_ok = False
            self.status.emit(f"Not saved: {name}: {result.error}")
        if not self._pending_saves:
            self.savesFinished.emit(self._saves_ok)
            self._saves_ok = True

    def reload(self) -> None:
        """Ctrl+R. Asks first when it would throw edits away."""
        if self.session.dirty and not self._confirm_discard("Compare again from disk"):
            return
        if self.folders is not None:
            # A folder tab walks again; the session's sides are only paths,
            # and reading them again could turn a folder tab into a message
            # if one side was pointed at something that is not a folder.
            self.folders.session.start()
            return
        self.session.reload()

    def _reload_side(self, index: int) -> None:
        if self.folders is not None:
            self.folders.session.retry(index)
            return
        side = self.session.sides[index]
        if side.dirty and not self._confirm_discard("Reload this side"):
            return
        self.session.retry(index)

    def _confirm_discard(self, action: str) -> bool:
        answer = QMessageBox.question(
            self, action, "There are unsaved changes. Reading from disk throws them away.",
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return answer == QMessageBox.Discard

    def _read_as(self, index: int, encoding: str) -> None:
        side = self.session.sides[index]
        if side.dirty and not self._confirm_discard("Read as"):
            return
        self.session.read_as(index, encoding)

    def _side_menu(self, index: int) -> None:
        menu = QMenu(self)
        self._fill_side_menu(index, menu)
        head = self.heads[index]
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(head.facts.mapToGlobal(head.facts.rect().bottomLeft()))

    def _fill_side_menu(self, index: int, menu: QMenu) -> None:
        """Saving, reading as and line endings for one side: the menu under
        the side's facts, and File > Left side / Right side (1.17)."""
        s = self.session
        side = s.sides[index]
        save = menu.addAction("Save\tCtrl+S", lambda: self.save_side(index))
        save.setEnabled(side.editable and (side.dirty or s.encoding_changed(index)))
        menu.addAction("Save as...", lambda: self.save_side_as(index)).setEnabled(side.doc is not None)
        menu.addSeparator()
        reading = menu.addMenu("Read as")
        auto = reading.addAction("Work it out" + (
            f"  ({io_load.label(side.loaded.encoding)})"
            if side.loaded is not None and not side.read_as and side.loaded.encoding else ""))
        auto.setCheckable(True)
        auto.setChecked(not side.read_as)
        auto.triggered.connect(lambda _c=False: self._read_as(index, ""))
        reading.addSeparator()
        for label, encoding in io_load.READ_AS:
            action = reading.addAction(label)
            action.setCheckable(True)
            action.setChecked(side.read_as == encoding)
            action.triggered.connect(lambda _c=False, e=encoding: self._read_as(index, e))
        reading.setEnabled(bool(side.path) and side.loaded is not None
                           and not side.loaded.binary or bool(side.read_as))
        encodings = menu.addMenu("Save with encoding")
        choices = list(SAVE_ENCODINGS)
        if side.encoding and side.encoding not in ("ascii",) and not any(
                (side.encoding, side.bom) == (e, b) for _l, e, b in choices):
            # The encoding it was read in is always one it can be saved in.
            choices.insert(0, (io_load.label(side.encoding) + (" with BOM" if side.bom else ""),
                               side.encoding, side.bom))
        for label, encoding, bom in choices:
            action = encodings.addAction(label)
            action.setCheckable(True)
            action.setChecked((side.encoding, side.bom) == (encoding, bom)
                              or (side.encoding == "ascii" and encoding == "utf-8" and not bom
                                  and not side.bom))
            action.triggered.connect(lambda _c=False, e=encoding, b=bom: s.set_encoding(index, e, b))
        encodings.setEnabled(side.doc is not None)
        endings = menu.addMenu("Convert line endings")
        for eol in ("CRLF", "LF", "CR"):
            endings.addAction(eol, lambda e=eol: s.set_line_endings(index, e))
        endings.setEnabled(side.editable)
        menu.addSeparator()
        menu.addAction("Copy path", lambda: QApplication.clipboard().setText(display(side.path)))
        menu.addAction("Reload from disk", lambda: self._reload_side(index))

    # ----------------------------------------------------------------- find

    def open_find(self) -> None:
        self.find.show()
        selected = self.view.selected_text()
        if selected and "\n" not in selected and len(selected) < 80 and not self.find.field.text():
            self.find.field.setText(selected.strip())
        self.find.field.setFocus(Qt.ShortcutFocusReason)
        self.find.field.selectAll()
        self._find_changed()

    def _find_changed(self) -> None:
        pattern, problem = self.find.pattern() if self.find.isVisible() else (None, "")
        self.view.set_find(pattern)
        self._matches = []
        if pattern is not None:
            left, right = self.session.result_lines if self.session.result else ([], [])
            lines = (left, right)
            for row, entry in enumerate(self.view.state.rows):
                for side in (0, 1):
                    index = entry[side]
                    if index != align.NONE and pattern.search(lines[side][index]):
                        self._matches.append((row, side))
        if problem:
            self.find.count.setText(problem)
        elif pattern is None:
            self.find.count.setText("")
        else:
            self.find.count.setText(f"{len(self._matches):,} match"
                                    f"{'es' if len(self._matches) != 1 else ''}")

    def _find_step(self, direction: int) -> None:
        if not self.find.isVisible():
            self.open_find()
            return
        if not self._matches:
            return
        here = (self.view.state.cursor, self.view.state.side)
        if direction > 0:
            target = next((m for m in self._matches if m > here), self._matches[0])
        else:
            target = next((m for m in reversed(self._matches) if m < here), self._matches[-1])
        row, side = target
        self.view.select_rows(side, row, row + 1)
        number = self._matches.index(target) + 1
        self.find.count.setText(f"{number:,} of {len(self._matches):,}")

    def _find_closed(self) -> None:
        self.find.hide()
        self.view.set_find(None)
        self._matches = []
        self.focus_view()

    # --------------------------------------------------------------- theme

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens
        ratio = float(self.devicePixelRatioF() or 1.0)
        for button in (self.find.previous, self.find.next, self.find.close_button):
            button.setIcon(glyphs.icon(button.property("glyph"), colour=tokens["txt_1"],
                                       muted=tokens["txt_2"], size=16, ratio=ratio))
        self.view.apply_tokens(tokens)
        if self.folders is not None:
            self.folders.apply_tokens(tokens)
        for head in self.heads:
            head.apply_tokens(tokens)
        self.hex.apply_tokens(tokens)
        self.rungs.apply_tokens(tokens)
        self.images.apply_tokens(tokens)
        self.table.apply_tokens(tokens)
        self.sidebar.apply_tokens(tokens)
        if self.folders is None:
            self._head_spacer.setFixedWidth(self.view.gutter.width())

    # -------------------------------------------------------------- drawing

    def title(self) -> str:
        names = [ntpath.basename(display(side.path)) or "?" for side in self.session.sides]
        titles = [side.title for side in self.session.sides]
        if any(titles):
            names = [t or n for t, n in zip(titles, names)]
        mark = "* " if self.session.dirty else ""
        if names[0].lower() == names[1].lower():
            return mark + names[0]
        return f"{mark}{names[0]}  vs  {names[1]}"

    def tooltip(self) -> str:
        return "\n".join(display(side.path) for side in self.session.sides)

    def summary(self) -> str | None:
        """What this comparison found, in a few words, for Home (1.21)."""
        s = self.session
        if self.folders is not None:
            tree = self.folders.session.tree
            return F.summary(tree).split("  \u00b7  ")[0] if tree is not None else None
        if s.kind == core.TEXT and s.result is not None and s.current:
            n = len(s.result.differences)
            return "Same" if not n else f"{n:,} difference{'s' if n != 1 else ''}"
        if s.kind == core.BINARY:
            return "Identical" if s.byte_identical else "Files differ"
        return None

    def refresh(self) -> None:
        s = self.session
        for index, (head, side) in enumerate(zip(self.heads, s.sides)):
            if not head.folder_mode:
                head.show_side(side, encoding_changed=s.encoding_changed(index))
        self._sync_toggles()
        self.view.set_editable(s.sides[0].editable, s.sides[1].editable)
        kind = s.kind
        shown = self.shown_mode()
        if self.sibling is not None and kind in (core.TEXT, core.BINARY) and self.mode == "auto":
            self.handoff.offer(self.sibling)
            self.stack.setCurrentWidget(self.handoff)
        elif shown == "hex":
            self._show_hex()
        elif shown == "image":
            self._show_images()
        elif shown == "table":
            self._show_table()
        elif shown == "rungs":
            self._show_rungs()
        elif kind == core.TEXT and s.result is not None:
            if s.result is not self._shown_result:
                self._shown_result = s.result
                left, right = s.result_lines
                self.view.set_comparison(s.result, left, right, s.options.intraline, s.pins)
                self._colour()
                self._outline_for = None
                if self.find.isVisible():
                    self._find_changed()
            self.stack.setCurrentWidget(self.view)
        elif kind == core.FOLDERS:
            self._shown_result = None
            self.stack.setCurrentWidget(self._folder_view())
        else:
            self._shown_result = None
            self.stack.setCurrentWidget(self.message)
            self.message.say(*self._explain(kind))
        self._show_sidebar()
        self._show_headings()
        self._update_position()
        self.titleChanged.emit()

    # ------------------------------------------- differences list (1.19)

    def _show_sidebar(self) -> None:
        text = self.stack.currentWidget() is self.view and self.session.result is not None
        self.sidebar.setVisible(text and self._sidebar_on)
        if text and self._sidebar_on:
            self._fill_sidebar()

    def _outline(self) -> tuple:
        """Per side, the section each line shown is in, or None. Crumbs from a
        format comparer when there are some; the outline otherwise."""
        from app.core import outline

        s = self.session
        key = (id(s.result), self.language)
        if self._outline_for == key:
            return self._sections
        self._outline_for = key
        out = []
        crumbs = s.result_crumbs if s.structure else ([], [])
        for side in (0, 1):
            lines = s.result_lines[side]
            if crumbs and crumbs[side] and any(crumbs[side]):
                out.append(list(crumbs[side]))
                continue
            language = self.language_for(side) or syntax.detect(
                s.sides[side].path, lines[0] if lines else "")
            out.append(outline.sections(lines, language) if language else None)
        self._sections = tuple(out)
        self._sidebar_key = None
        return self._sections

    #: Past this many differences the list is cut, with a line saying so.
    LIST_LIMIT = 3000

    def _fill_sidebar(self) -> None:
        from app.core.diff import align as A

        s = self.session
        result = s.result
        if result is None or s.kind != core.TEXT:
            return
        key = (id(result), self.language)
        if getattr(self, "_sidebar_key", None) == key:
            return
        self._sidebar_key = key
        known, summaries = self._summaries()
        groups: dict[str, list[Entry]] = {}
        order: list[str] = []
        ignored: list[Entry] = []
        for index, (heading, title, detail) in enumerate(summaries):
            block = result.blocks[index]
            bar = "diff_ignored_bar" if not block.significant else (
                "diff_moved_bar" if block.move >= 0 else {
                    A.DELETED: "diff_del_bar", A.INSERTED: "diff_add_bar"}.get(
                    block.kind, "diff_chg_bar"))
            entry = Entry(index, title, detail, bar)
            if not block.significant:
                ignored.append(entry)
                continue
            if heading not in groups:
                groups[heading] = []
                order.append(heading)
            groups[heading].append(entry)
        listed = [(h, groups[h]) for h in order]
        if ignored:
            listed.append(("Ignored by rules", ignored))
        if len(result.blocks) > self.LIST_LIMIT:
            listed.append((f"First {self.LIST_LIMIT:,} of {len(result.blocks):,} listed", []))
        self.sidebar.set_entries(key, listed)

    def _summaries(self) -> tuple[bool, list[tuple[str, str, str]]]:
        """Per difference: (section, where, what), for the list and for
        Unified's headings. Kept per comparison and language."""
        from app.core import outline

        s = self.session
        key = (id(s.result), self.language)
        cached = getattr(self, "_summaries_for", None)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        sections = self._outline()
        known = any(x is not None for x in sections)
        left, right = s.result_lines
        out = []
        for index, block in enumerate(s.result.blocks[:self.LIST_LIMIT]):
            title, detail = outline.summary(s.result, index, left, right)
            heading = outline.section_of(s.result.rows[block.start:block.end], sections) \
                if known else ""
            out.append((heading or ("Top of file" if known else "Differences"), title, detail))
        self._summaries_for = (key, known, out)
        return known, out

    def _show_headings(self) -> None:
        """Unified's heading over each difference (1.19)."""
        s = self.session
        if self.view.state.layout != "unified" or s.result is None or s.kind != core.TEXT:
            return
        known, summaries = self._summaries()
        headings = {}
        for index, (section, title, detail) in enumerate(summaries):
            headings[index] = (f"{section}     {title}: {detail}" if known
                               else f"{title}: {detail}")
        self.view.set_headings(headings)

    def _go_block(self, block: int) -> None:
        self.view.go(block)
        self.view.setFocus(Qt.OtherFocusReason)

    def _show_location(self) -> None:
        """file > section > line, for the line under the cursor (1.19)."""
        s = self.session
        if self.stack.currentWidget() is not self.view or s.result is None \
                or s.kind != core.TEXT or not self.view.state.rows:
            self.location.hide()
            return
        sections = self._outline()
        state = self.view.state
        side = state.side
        row = max(0, min(state.cursor, len(state.rows) - 1))
        index = state.rows[row][side]
        if index == align.NONE:
            side = 1 - side
            index = state.rows[row][side]
        names = sections[side] if 0 <= side < 2 else None
        if not names or index == align.NONE or index >= len(names):
            self.location.hide()
            return
        name = ntpath.basename(display(s.sides[side].path)) or ("left", "right")[side]
        parts = [name] + [p for p in names[index].split(" \u203a ") if p] + \
            [f"line {index + 1:,}"]
        self.location.setText("   \u203a   ".join(parts))
        self.location.show()

    # --------------------------------------------------------- the modes

    def available_modes(self) -> list[str]:
        """What the View switch can offer for this pair."""
        from app.core import imagediff

        s = self.session
        out = []
        loaded = [side.loaded for side in s.sides]
        if all(l is not None and not l.binary for l in loaded) and not any(
                l is not None and l.lossy for l in loaded):
            out.append("text")
            if s.format_kind in ("l5x", "l5k") and s.structure:
                out.append("rungs")
            from app.core import tables

            if all(tables.is_table(side.path) or not side.path for side in s.sides):
                out.append("table")
        if all(l is not None and l.data is not None for l in loaded):
            from app.core import workbook

            if all(workbook.is_workbook(side.path) or not side.path for side in s.sides) \
                    and any(side.path for side in s.sides):
                out.append("table")
            out.append("hex")
            if all(imagediff.is_image(side.path) or not side.path for side in s.sides):
                out.append("image")
        return out or ["text"]

    def shown_mode(self) -> str:
        """Which of text, hex and image this pair is shown as now."""
        from app.core import imagediff

        s = self.session
        if s.kind not in (core.TEXT, core.BINARY):
            return "text"
        modes = self.available_modes()
        if self.mode in modes:
            return self.mode
        if "image" in modes and all(imagediff.is_image(side.path) for side in s.sides):
            return "image"
        if "table" in modes and all(side.path for side in s.sides):
            return "table"
        if s.kind == core.BINARY and "hex" in modes:
            return "hex"
        return "text"

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.refresh()
        self.focus_view()

    # ------------------------------------------------------ syntax colour

    def language_for(self, side: int) -> str:
        """The language key one side is coloured as, "" for none."""
        s = self.session
        if self.language == "off":
            return ""
        if s.sides[side].structured:
            # A side shown by its structure is canonical lines this
            # application wrote, not the file's text; its colour would be
            # the colour of the wrong language.
            return ""
        if self.language != "auto":
            return self.language
        lines = s.result_lines[side]
        return syntax.detect(s.sides[side].path, lines[0] if lines else "")

    def language_label(self) -> str:
        if self.language == "off":
            return "Plain text"
        keys = {self.language_for(0), self.language_for(1)} - {""}
        if not keys:
            return "Plain text"
        return " / ".join(sorted(syntax.name_of(k) for k in keys))

    def _colour(self) -> None:
        """Colour both sides for the lines the view is drawing now: small
        files on the spot, large ones in the loader, very large not at all."""
        s = self.session
        for side in (0, 1):
            lines = s.result_lines[side]
            key = self.language_for(side)
            self._syntax_requests[side] = 0
            if not key or not lines:
                self.view.set_syntax(side, None, None)
                continue
            if syntax.size(lines) <= syntax.SYNC_LIMIT:
                self.view.set_syntax(side, lines, syntax.highlight(lines, key))
            else:
                self._syntax_requests[side] = s._loader.submit(_syntax_job, lines, key)
        self.commandsChanged.emit()

    def set_language(self, language: str) -> None:
        self.language = language
        self._colour()
        self._show_sidebar()
        self._show_location()

    def _fill_language_menu(self, menu: QMenu) -> None:
        s = self.session
        detected = {syntax.detect(side.path, (lines[0] if lines else ""))
                    for side, lines in zip(s.sides, s.result_lines)} - {""}
        auto = menu.addAction("By the file's name" + (
            f"  ({' / '.join(sorted(syntax.name_of(k) for k in detected))})"
            if detected else "  (plain text)"))
        auto.setCheckable(True)
        auto.setChecked(self.language == "auto")
        auto.triggered.connect(lambda _c=False: self.set_language("auto"))
        off = menu.addAction("Plain text, no colour")
        off.setCheckable(True)
        off.setChecked(self.language == "off")
        off.triggered.connect(lambda _c=False: self.set_language("off"))
        menu.addSeparator()
        for key, label in syntax.MENU:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.language == key)
            action.triggered.connect(lambda _c=False, k=key: self.set_language(k))

    def _fill_view_menu(self, menu: QMenu) -> None:
        shown = self.shown_mode()
        for mode in self.available_modes():
            action = menu.addAction(VIEW_LABELS[mode])
            action.setCheckable(True)
            action.setChecked(mode == shown)
            action.triggered.connect(lambda _c=False, m=mode: self.set_mode(m))

    def _show_rungs(self) -> None:
        """1.16: the comparison's rungs as ladder. Read from the rows the text
        view shows -- nothing is compared again."""
        from app.core import ladder

        self.stack.setCurrentWidget(self.rungs)
        s = self.session
        if s.result is not None and s.result is not self._rungs_for:
            self._rungs_for = s.result
            left, right = s.result_lines
            crumbs = s.result_crumbs
            self.rungs.set_pairs(ladder.pairs(s.result.rows, left, right,
                                              crumbs[0] if crumbs else (),
                                              crumbs[1] if crumbs else ()))
            if self.rungs.canvas.current < 0:
                self.rungs.go_first()

    def _rung_to_text(self, row: int) -> None:
        """A rung double-clicked: the same place in the text view."""
        self.set_mode("text")
        self.view.reveal(row)

    def _show_table(self) -> None:
        self.stack.setCurrentWidget(self.table)
        key = tuple(side.doc.revision if side.doc else -1 for side in self.session.sides) + \
            tuple(id(side.doc) for side in self.session.sides) + \
            tuple(side.loaded.digest if side.loaded else "" for side in self.session.sides)
        if self._table_for != key:
            self._table_for = key
            self._measure_table()

    def _is_workbook_pair(self) -> bool:
        from app.core import workbook

        sides = self.session.sides
        return any(side.path for side in sides) and all(
            workbook.is_workbook(side.path) or not side.path for side in sides)

    def _measure_table(self) -> None:
        s = self.session
        if self._is_workbook_pair():
            self.table.set_workbook(True)
            data = [side.loaded.data if side.loaded is not None and side.path else b""
                    for side in s.sides]
            self._table_request = s._loader.submit(_workbook_job, data[0], data[1],
                                                   self.table.options)
            return
        self.table.set_workbook(False)
        self._table_request = s._loader.submit(
            _table_job, list(s.sides[0].lines), list(s.sides[1].lines), self.table.options)

    def _navigate(self, where: str) -> None:
        if self.stack.currentWidget() is self.rungs:
            {"first": self.rungs.go_first, "last": self.rungs.go_last,
             "next": lambda: self.rungs.step(1),
             "previous": lambda: self.rungs.step(-1)}[where]()
            return
        if self.stack.currentWidget() is self.table:
            self.table.step(-1 if where in ("previous", "last") else 1)
            return
        if self.stack.currentWidget() is self.hex:
            if where == "first":
                self.hex.go(0)
            elif where == "last":
                self.hex.go(len(self.hex.blocks) - 1)
            else:
                self.hex.step(1 if where == "next" else -1)
            return
        {"first": self.view.first_difference, "last": self.view.last_difference,
         "next": self.view.next_difference, "previous": self.view.previous_difference}[where]()

    def _pair_bytes(self) -> tuple[bytes, bytes]:
        left, right = (side.loaded for side in self.session.sides)
        return ((left.data if left is not None else b"") or b"",
                (right.data if right is not None else b"") or b"")

    def _show_hex(self) -> None:
        from app.core import hexdiff

        self.stack.setCurrentWidget(self.hex)
        data = self._pair_bytes()
        key = (id(data[0]), id(data[1]))
        if self._hex_for != key:
            self._hex_for = key
            self._hex_request = self.session._loader.submit(hexdiff.compare, *data)
            self._hex_data = data
            from app.core import workbook

            if any(workbook.is_old_workbook(side.path) for side in self.session.sides):
                self.status.emit("An old .xls workbook is compared as bytes. Saved as "
                                 ".xlsx it compares as a table, sheet by sheet.")

    def _show_images(self) -> None:
        self.stack.setCurrentWidget(self.images)
        data = self._pair_bytes()
        key = (id(data[0]), id(data[1]))
        if self._image_for != key:
            self._image_for = key
            self._measure_images(self.images.tolerance.value())

    def _measure_images(self, tolerance: int) -> None:
        from app.core import imagediff

        data = self._pair_bytes()
        self._image_request = self.session._loader.submit(imagediff.compare, data[0], data[1],
                                                          tolerance)

    def _folder_view(self) -> FolderView:
        if self.folders is None:
            from app.core.folderdiff import FolderSession

            s = self.session
            folder = FolderSession(s._loader, s.sides[0].path, s.sides[1].path,
                                   mask=s.options.folder_mask, timeout=s.options.timeout,
                                   hour=s.options.folder_hour,
                                   by_content=s.options.folder_by_content,
                                   archives=s.options.folder_archives,
                                   parent=self)
            self.folders = FolderView(folder, self._tokens, mask=s.options.folder_mask,
                                      open_expanded=s.options.folder_open_expanded,
                                      layout=s.options.folder_layout,
                                      categories=s.options.folder_categories)
            if s.options.folder_show in F_SHOWS:
                self.folders.set_show(s.options.folder_show)
            # 1.15: each side's header becomes its path box.
            self._folder_history = list(s.options.folder_history)
            for index, head in enumerate(self.heads):
                head.set_folder_mode()
                head.history = self._folder_history
                head.apply_tokens(self._tokens)
            folder.changed.connect(self._show_folder_heads)
            self.folders.rebase.connect(self._rebase)
            self.folders.openPair.connect(self.openPair)
            self.folders.openExtracted.connect(self.openExtracted)
            self.folders.status.connect(self.status)
            self.folders.setting.connect(self.setting)
            self.folders.command.connect(self._command)
            self.folders.split.connect(self._folder_split)
            self.folders.sideChanged.connect(self._folder_side)
            self.folders.commandsChanged.connect(self.commandsChanged)
            self._folder_side(self.folders.side)
            self.stack.addWidget(self.folders)
            folder.start()
        return self.folders

    def _show_folder_heads(self) -> None:
        if self.folders is None:
            return
        for head, side in zip(self.heads, self.folders.session.sides):
            head.show_folder(side.path, side.state, side.error)

    def _path_chosen(self, index: int, path: str) -> None:
        if self.folders is not None:
            self.set_folder(index, path)
        else:
            self.set_file(index, path)

    def _browse_side(self, index: int) -> None:
        if self.folders is not None:
            self._browse_folder(index)
        else:
            self._browse_file(index)

    def set_file(self, index: int, path: str) -> bool:
        """Point one side of a text tab at another file (1.18). The other
        side keeps what it read; edits on this side are asked about first."""
        path = path.strip().strip('"')
        s = self.session
        side = s.sides[index]
        if not path or path == side.path:
            self.heads[index].show_side(side)
            return False
        if side.dirty and not self._confirm_discard("Open another file on this side"):
            self.heads[index].show_side(side)
            return False
        if not s.set_path(index, path):
            return False
        self._shown_result = None
        history = self._file_history
        history[:] = [path] + [p for p in history if p.lower() != path.lower()]
        del history[20:]
        self.sibling = siblings.for_pair(s.sides[0].path, s.sides[1].path)
        self.pairChanged.emit(s.sides[0].path, s.sides[1].path)
        self.titleChanged.emit()
        return True

    def _browse_file(self, index: int) -> None:
        start = ntpath.dirname(display(self.session.sides[index].path)) or ntpath.dirname(
            display(self.session.sides[1 - index].path))
        chosen, _filter = QFileDialog.getOpenFileName(
            self, f"Choose the {'left' if index == 0 else 'right'} file", start)
        if chosen:
            self.set_file(index, QDir.toNativeSeparators(chosen))

    def set_folder(self, index: int, path: str) -> bool:
        """Point one side of a folder tab at another folder (1.15). The other
        side keeps its listing and its folder."""
        path = F.tidy(path)
        if self.folders is None or not path:
            return False
        if not self.folders.session.set_path(index, path):
            self._show_folder_heads()
            return False
        self._moved(index, path)
        return True

    def _rebase(self, left: str, right: str) -> None:
        """From a row's menu: one side, or both, moved into that folder."""
        if self.folders is None:
            return
        self.folders.session.set_paths(left, right)
        for index, path in ((0, left), (1, right)):
            if path:
                self._moved(index, path)

    def _moved(self, index: int, path: str) -> None:
        side = self.session.sides[index]
        side.path = path
        side.title = ""
        history = self._folder_history
        history[:] = [path] + [p for p in history if not F.same_path(p, path)]
        del history[20:]
        self.setting.emit("folders.history", list(history))
        self._show_folder_heads()
        self.titleChanged.emit()

    def _browse_folder(self, index: int) -> None:
        start = self.folders.session.sides[index].path if self.folders is not None else ""
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose the {'left' if index == 0 else 'right'} folder", start)
        if chosen:
            self.set_folder(index, QDir.toNativeSeparators(chosen))

    def _folder_side(self, side: int) -> None:
        """1.14: the header over the half F5 copies from is the focused one."""
        self.heads[0].set_focused(side == 0)
        self.heads[1].set_focused(side == 1)

    def _folder_split(self, left: int, middle: int) -> None:
        """1.12: each side's header over its own half of the folder tree.
        A folder tab stays a folder tab, so nothing has to undo this."""
        self.heads[0].setFixedWidth(max(0, left))
        self._head_spacer.setFixedWidth(max(0, middle))

    def _launch_sibling(self) -> None:
        from app.io import launch

        paths = [side.path for side in self.session.sides if side.path]
        self._launch_request = self.session._loader.submit(
            launch.start_each, self.sibling.programs, paths)
        self.status.emit(f"Starting {self.sibling.name}...")

    def _loader_answer(self, request: int, envelope) -> None:
        if not request:
            return
        if request == self._hex_request:
            self._hex_request = 0
            if envelope.ok:
                self.hex.set_data(*self._hex_data, envelope.value)
                self._update_position()
            return
        if request in self._syntax_requests:
            side = self._syntax_requests.index(request)
            self._syntax_requests[side] = 0
            lines = self.session.result_lines[side]
            if envelope.ok and envelope.value is not None and envelope.value[0] is lines:
                self.view.set_syntax(side, lines, envelope.value[1])
            return
        if request == self._table_request:
            self._table_request = 0
            if envelope.ok:
                value = envelope.value
                if isinstance(value, tuple):          # a workbook pair
                    result, states, sheet, note = value
                    self.table.set_sheets(states, sheet, note)
                    value = result
                self.table.set_result(value)
                self._update_position()
            else:
                self.status.emit(f"Could not read as a table: {envelope.error}")
            return
        if request == self._image_request:
            self._image_request = 0
            if envelope.ok:
                self.images.set_result(envelope.value)
                self.status.emit(self.images.describe())
            return
        if request != self._launch_request:
            return
        self._launch_request = 0
        if envelope.ok:
            self.status.emit(f"Opened both in {self.sibling.name}")
        else:
            reason = envelope.error.split(": ", 1)[-1]
            self.status.emit(f"{self.sibling.name}: {reason}")

    def _compare_here(self) -> None:
        self.sibling = None
        self.refresh()

    def stop(self) -> None:
        """The tab is closing: stop polling, walking and reading."""
        self.session.stop()
        if self.folders is not None:
            self.folders.session.stop()

    def _explain(self, kind: str) -> tuple[str, str]:
        s = self.session
        left, right = s.sides
        if kind == core.WAITING:
            if s.comparing:
                return "Comparing...", ""
            return "Reading...", ""
        if kind == core.BROKEN:
            failed = [n for n, side in zip(("Left", "Right"), s.sides)
                      if side.state in (core.FAILED, core.SLOW)]
            return (f"{' and '.join(failed)} could not be read",
                    "The reason is over the side. Retry reads it again.")
        if kind == core.MIXED:
            return ("A file and a folder",
                    "One side is a file and the other a folder. Choose two files.")
        if kind == core.BINARY:
            if s.byte_identical:
                return "Identical", "The two files are the same, byte for byte."
            both = all(side.loaded is not None and side.loaded.binary for side in s.sides)
            detail = ("Both files are binary" if both else "One side is binary")
            return ("The files differ",
                    f"{detail} and larger than hex compare holds in memory "
                    f"({io_load.KEEP_BYTES // (1024 * 1024)} MB), so they were compared "
                    "by content hash only.")
        if s.problem:
            return "Could not compare", s.problem
        return "", ""

    def _sync_toggles(self) -> None:
        focused = self.folders.side if self.folders is not None else self.view.focused_side
        self.heads[0].set_focused(focused == 0)
        self.heads[1].set_focused(focused == 1)

    def _update_position(self) -> None:
        s = self.session
        self._show_location()
        if self.stack.currentWidget() is self.rungs:
            current, total = self.rungs.position()
            if s.result is None:
                text = "Comparing..."
            elif not total:
                text = "No rung differs"
            else:
                noun = "rung differs" if total == 1 else "rungs differ"
                text = f"Rung {current} of {total} that differ" if current \
                    else f"{total} {noun}"
                pair = self.rungs.current_pair()
                if current and pair is not None:
                    rung = pair.right or pair.left
                    text += f"  ·  {rung.crumb}"
            self.count.setText(text)
            self.count.setProperty("state", "same" if s.result is not None and not total
                                   else "")
            self.count.style().unpolish(self.count)
            self.count.style().polish(self.count)
            self.commandsChanged.emit()
            return
        if self.stack.currentWidget() is self.table:
            result = self.table.model.result
            total = len(result.differences) if result else 0
            self.count.setText(f"{total:,} record{'s' if total != 1 else ''} differ"
                               if result else "Comparing...")
            self.commandsChanged.emit()
            return
        if self.stack.currentWidget() is self.hex:
            current, total = self.hex.position()
            result = self.hex.result
            if result is None:
                text = "Comparing bytes..."
            elif result.identical:
                text = "Identical, byte for byte"
            else:
                noun = "difference" if total == 1 else "differences"
                text = f"Difference {current} of {total}" if current else f"{total} {noun}"
                if current:
                    text += f"  ·  offset 0x{self.hex.blocks[current - 1][0] * 16:X}"
                if result.left_size != result.right_size:
                    text += (f"  ·  {result.left_size:,} and {result.right_size:,} bytes")
            self.count.setText(text)
            self.commandsChanged.emit()
            return
        result = s.result if s.kind == core.TEXT else None
        state = ""
        if result is None:
            text = ""
        elif result.exact:
            text = ("Identical, byte for byte" if s.byte_identical
                    else "Same text" + self._why_not_bytes())
            state = "same"
        elif result.identical:
            ignored = len(result.blocks)
            text = f"No differences that count  ·  {ignored} ignored"
            state = "same"
        else:
            current, total = self.view.position()
            noun = "difference" if total == 1 else "differences"
            text = (f"Difference {current} of {total}" if current
                    else f"{total} {noun}")
            moved = self._moved_note()
            if current and moved:
                text += f"  ·  {moved}"
            crumb = self._crumb()
            if current and crumb:
                text += f"  ·  {crumb}"
        self.count.setText(text)
        self.count.setProperty("state", state)
        self.count.style().unpolish(self.count)
        self.count.style().polish(self.count)
        focused = self.folders.side if self.folders is not None else self.view.focused_side
        self.heads[0].set_focused(focused == 0)
        self.heads[1].set_focused(focused == 1)
        if result is not None:
            self.status.emit(self._status_line(result))
            if self.sidebar.isVisible():
                self.sidebar.set_current(self.view.state.current)
        self._show_location()
        self.commandsChanged.emit()

    def _align(self) -> None:
        """Ctrl+L, twice: hold a line on one side opposite a line on the
        other (1.6). The first press picks the line under the cursor; Tab
        across, move to the other line, and the second press makes the pin."""
        s = self.session
        state = self.view.state
        if s.result is None or s.kind != core.TEXT or not state.rows:
            self.status.emit("Lines can be aligned in a text comparison")
            return
        side = self.view.focused_side
        row = state.cursor
        line = state.rows[row][side]
        if line == align.NONE:
            self.status.emit("That row has no line on this side to align")
            return
        names = ("left", "right")
        pending = state.pending
        if pending is None or pending[0] == side:
            state.pending = (side, row)
            self.view.update_all()
            self.status.emit(f"Aligning {names[side]} line {line + 1}: pick the line on the "
                             f"{names[1 - side]} and press Ctrl+L again (Ctrl+Shift+L cancels)")
            return
        other = state.rows[pending[1]][pending[0]]
        state.pending = None
        left_line, right_line = (line, other) if side == 0 else (other, line)
        dropped = len(s.pins)
        s.pin(left_line, right_line)
        dropped = dropped + 1 - len(s.pins)
        note = f"; {dropped} earlier pin{'s' if dropped != 1 else ''} gave way" if dropped else ""
        self.status.emit(f"Left {left_line + 1} is held opposite right {right_line + 1}{note}. "
                         f"Ctrl+Shift+L removes pins")

    def _unalign(self) -> None:
        """Ctrl+Shift+L: cancel a half-made pin; otherwise remove the pin on
        the cursor's row, or every pin when the cursor is not on one."""
        s = self.session
        state = self.view.state
        if state.pending is not None:
            state.pending = None
            self.view.update_all()
            self.status.emit("Alignment cancelled")
            return
        if not s.pins:
            self.status.emit("No lines are pinned")
            return
        if state.cursor in state.pinned and state.rows:
            i, j, _kind = state.rows[state.cursor]
            s.unpin(i, j)
            self.status.emit(f"Removed the pin on left {i + 1}, right {j + 1}")
            return
        count = len(s.pins)
        s.unpin()
        self.status.emit(f"Removed {count} pin{'s' if count != 1 else ''}")

    def _moved_note(self) -> str:
        """For one end of a move: where the other end is, by line number,
        since that is what a person scrolls to."""
        s = self.session
        index = self.view.state.current
        if index is None or not s.result or index >= len(s.result.blocks):
            return ""
        move_index = s.result.blocks[index].move
        if move_index < 0:
            return ""
        move = s.result.moves[move_index]
        lines = move.size
        noun = "line" if lines == 1 else f"{lines} lines"
        if index == move.left_block:
            return f"Moved: {noun}, now at right {move.right[0] + 1} (Ctrl+M)"
        return f"Moved: {noun}, was at left {move.left[0] + 1} (Ctrl+M)"

    def _crumb(self) -> str:
        """Where the current difference is in the file's structure, when a
        format comparer said so."""
        s = self.session
        index = self.view.state.current
        if index is None or not s.result or index >= len(s.result.blocks):
            return ""
        block = s.result.blocks[index]
        left_crumbs, right_crumbs = s.result_crumbs
        for row in s.result.rows[block.start:block.end]:
            if row[1] != align.NONE and row[1] < len(right_crumbs) and right_crumbs[row[1]]:
                return right_crumbs[row[1]]
            if row[0] != align.NONE and row[0] < len(left_crumbs) and left_crumbs[row[0]]:
                return left_crumbs[row[0]]
        return ""

    def _why_not_bytes(self) -> str:
        left, right = (side.loaded for side in self.session.sides)
        if left is None or right is None:
            return ""
        reasons = []
        if (left.encoding, left.bom) != (right.encoding, right.bom):
            reasons.append("encoding")
        if left.eol != right.eol:
            reasons.append("line endings")
        return f"  ·  {' and '.join(reasons)} differ" if reasons else ""

    def _status_line(self, result) -> str:
        counts = result.counts()
        parts = []
        if counts["changed"]:
            parts.append(f"{counts['changed']:,} changed")
        if counts.get("moved"):
            parts.append(f"{counts['moved']:,} moved")
        if counts["deleted"]:
            parts.append(f"{counts['deleted']:,} only left")
        if counts["inserted"]:
            parts.append(f"{counts['inserted']:,} only right")
        if counts["ignored"]:
            parts.append(f"{counts['ignored']:,} ignored")
        lines = "  ·  ".join(parts) if parts else "no lines differ"
        note = f"    {self.session.format_note}" if self.session.structure and \
            self.session.format_note else ""
        return (f"{lines}    {self.session.rules.describe()}{note}    "
                f"compared in {result.elapsed * 1000:.0f} ms")

    # ------------------------------------------------- commands (1.17)

    #: Commands that go straight to `_command` with the same name.
    PLAIN_COMMANDS = frozenset({
        "swap", "reload", "copy-left", "copy-right", "copy-all-left", "copy-all-right",
        "undo", "redo", "save", "save-all", "find", "find-next", "find-previous",
        "copy-text", "report", "save-session", "align", "unalign", "move-partner",
        "select-all", "edit", "insert-line", "delete-lines"})

    def page_kind(self) -> str:
        """Which toolbar the window shows: "text", "folder" or "other"."""
        current = self.stack.currentWidget()
        if self.folders is not None and current is self.folders:
            return "folder"
        if current in (self.view, self.message, self.handoff):
            return "text"
        return "other"

    def command_state(self, id_: str) -> State:
        s = self.session
        kind = self.page_kind()
        if id_ in ("swap", "reload", "save-session", "copy-paths", "open-left", "open-right"):
            return State()
        if kind == "folder":
            answer = self.folders.command_state(id_)
            return answer if answer is not None else HIDDEN
        current = self.stack.currentWidget()
        text = current is self.view
        result = s.result if s.kind == core.TEXT else None
        has = bool(result and result.differences)
        focused = self.view.focused_side
        side = s.sides[focused]
        if id_ in ("compare-as", ">compare-as-menu"):
            if s.kind not in (core.TEXT, core.BINARY):
                return HIDDEN
            return State(label=VIEW_LABELS.get(self.shown_mode(), "Text")
                         if id_ == "compare-as" else None)
        if id_ in ("previous", "next"):
            if current is self.images:
                return HIDDEN
            if current is self.rungs:
                return State(enabled=self.rungs.position()[1] > 0)
            if current is self.hex:
                return State(enabled=self.hex.position()[1] > 0)
            if current is self.table:
                table = self.table.model.result
                return State(enabled=bool(table and table.differences))
            return State(enabled=has)
        if not text and kind == "text":
            # Still reading, a message, or a sibling's pair: the text
            # commands are there, and have nothing to act on yet.
            if id_ == "structure":
                return State(enabled=False, visible=s.format_kind != formats.PLAIN)
            if id_ in (">side-left", ">side-right", ">syntax", ">whitespace", ">patterns"):
                return HIDDEN
            return State(enabled=False) if id_ in self.TEXT_IDS else HIDDEN
        if kind != "text":
            return HIDDEN
        rules = s.rules
        editable = (s.sides[0].editable, s.sides[1].editable)
        on_block = has and (self.view.state.current is not None
                            or self.view.state.copyable() is not None)
        if id_ == "structure":
            return State(checked=s.structure, visible=s.format_kind != formats.PLAIN,
                         tip=f"Compare by {formats.names().get(s.format_kind, 'structure')}: "
                             "what the file says, not how it is laid out. Off compares and "
                             "edits the plain text.")
        if id_ == "rules":
            on = rules.enabled and rules.any
            return State(checked=on, label="Rules on" if on else None)
        if id_ == "ignore-case":
            return State(checked=rules.case)
        if id_ == "ignore-blank":
            return State(checked=rules.blank_lines)
        if id_ == "ignore-comments":
            return State(checked=rules.comments, enabled=bool(rules.markers),
                         label="Ignore comments" + (
                             f"  ({' '.join(m.strip() for m in rules.markers)})"
                             if rules.markers else "  (not known for this file type)"))
        layout = self.view.state.layout
        if id_ in self.VIEW_SHOWS:
            if layout == "fluid":
                return State(enabled=False, checked=id_ == "view-all",
                             tip="Fluid shows every line; Side by side and Unified can "
                                 "show only the differences")
            return State(checked=self.view.state.show == self.VIEW_SHOWS[id_])
        if id_ in self.LAYOUTS:
            return State(checked=layout == self.LAYOUTS[id_])
        if id_ == "details":
            return State(checked=self.view.details.isVisibleTo(self.view))
        if id_ == "sidebar":
            return State(checked=self._sidebar_on)
        if id_ == "mark-chars":
            return State(checked=s.options.intraline == "char")
        if id_ == "mark-words":
            return State(checked=s.options.intraline == "word")
        if id_ == "copy-left":
            return State(enabled=on_block and editable[0])
        if id_ == "copy-right":
            return State(enabled=on_block and editable[1])
        if id_ == "copy-all-left":
            return State(enabled=has and editable[0])
        if id_ == "copy-all-right":
            return State(enabled=has and editable[1])
        if id_ in ("edit", "insert-line", "delete-lines", "align"):
            if layout != "sbs":
                return State(enabled=False, tip="Editing and aligning are in Side by side")
            if id_ == "align":
                return State(enabled=result is not None)
            return State(enabled=side.editable and bool(self.view.state.rows))
        if id_ == "undo":
            return State(enabled=side.doc is not None and side.doc.can_undo)
        if id_ == "redo":
            return State(enabled=side.doc is not None and side.doc.can_redo)
        if id_ == "save":
            return State(enabled=side.editable and (side.dirty or s.encoding_changed(focused)))
        if id_ == "save-all":
            return State(enabled=s.dirty)
        if id_ == "save-as":
            return State(enabled=side.doc is not None)
        if id_ in ("first", "last", "move-partner"):
            return State(enabled=has)
        if id_ in ("report", "find", "find-next", "find-previous", "copy-text", "select-all",
                   "align", "unalign"):
            return State(enabled=result is not None)
        if id_ in (">side-left", ">side-right"):
            index = 0 if id_ == ">side-left" else 1
            return State(enabled=s.sides[index].doc is not None)
        if id_ in (">syntax", ">whitespace"):
            return State()
        if id_ == ">patterns":
            return State(visible=bool(rules.patterns))
        return HIDDEN

    #: 1.19: the text layouts, by command.
    LAYOUTS = {"layout-sbs": "sbs", "layout-fluid": "fluid", "layout-unified": "unified"}

    #: 1.18: the text view's show filter, by command.
    VIEW_SHOWS = {"view-all": "all", "view-diffs": "diffs", "view-same": "same",
                  "view-context": "context"}

    #: The text commands shown (greyed) while a text tab has nothing to show.
    TEXT_IDS = frozenset({
        "view-all", "view-diffs", "view-same", "view-context", "details", "sidebar",
        "layout-sbs", "layout-fluid", "layout-unified",
        "rules", "copy-left", "copy-right", "edit", "save", "undo", "redo", "find",
        "copy-all-left", "copy-all-right", "first", "last", "report", "mark-chars",
        "mark-words", "ignore-case", "ignore-blank", "ignore-comments", "copy-text",
        "select-all", "save-all", "save-as", "insert-line", "delete-lines", "align",
        "unalign", "move-partner", "find-next", "find-previous"})

    def run_command(self, id_: str) -> None:
        s = self.session
        if self.page_kind() == "folder" and self.folders.run_command(id_):
            return
        if id_ in ("open-left", "open-right"):
            self._browse_side(0 if id_ == "open-left" else 1)
            return
        if id_ in ("previous", "next", "first", "last"):
            self._navigate(id_)
        elif id_ in self.VIEW_SHOWS:
            self.view.set_show(self.VIEW_SHOWS[id_])
            self.setting.emit("view.show", self.VIEW_SHOWS[id_])
        elif id_ == "details":
            on = not self.view.details.isVisibleTo(self.view)
            self.view.set_details(on)
            self.setting.emit("view.details", on)
        elif id_ in self.LAYOUTS:
            self.view.set_layout(self.LAYOUTS[id_])
            self.setting.emit("view.layout", self.LAYOUTS[id_])
            self._show_headings()
        elif id_ == "sidebar":
            self._sidebar_on = not self._sidebar_on
            self.setting.emit("view.sidebar", self._sidebar_on)
            self._show_sidebar()
        elif id_ == "structure":
            s.set_structure(not s.structure)
        elif id_ == "rules":
            self._command("rules")
        elif id_ == "ignore-case":
            self._change_rules(case=not s.rules.case)
        elif id_ == "ignore-blank":
            self._change_rules(blank_lines=not s.rules.blank_lines)
        elif id_ == "ignore-comments":
            self._change_rules(comments=not s.rules.comments)
        elif id_ == "mark-chars":
            self._set_intraline("char")
        elif id_ == "mark-words":
            self._set_intraline("word")
        elif id_ == "save-as":
            self.save_side_as(self.view.focused_side)
        elif id_ == "copy-paths":
            QApplication.clipboard().setText(
                "\n".join(display(side.path) for side in s.sides))
            self.status.emit("Copied both paths")
        elif id_ in self.PLAIN_COMMANDS:
            self._command(id_)
        else:
            return
        if self.page_kind() != "folder":
            self.focus_view()
        self.commandsChanged.emit()

    def fill_menu(self, name: str, menu: QMenu) -> None:
        if name in ("side-left", "side-right"):
            self._fill_side_menu(0 if name == "side-left" else 1, menu)
        elif name == "syntax":
            self._fill_language_menu(menu)
        elif name == "whitespace":
            self._fill_whitespace_menu(menu)
        elif name == "patterns":
            self._fill_patterns_menu(menu)
        elif name == "compare-as-menu":
            self._fill_view_menu(menu)

    def focus_view(self) -> None:
        current = self.stack.currentWidget()
        if self.folders is not None and current is self.folders:
            self.folders.focus()
        elif current in (self.hex, self.images):
            current.setFocus(Qt.OtherFocusReason)
        elif current is self.table:
            self.table.grid.setFocus(Qt.OtherFocusReason)
        elif current is self.rungs:
            self.rungs.focus()
        else:
            self.view.setFocus(Qt.OtherFocusReason)

    def set_rules(self, rules: Rules) -> None:
        self.session.set_rules(rules)
