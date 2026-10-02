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

from PySide6.QtCore import QDir, Qt, Signal
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
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import formats, siblings, syntax
from app.core import session as core
from app.core.diff import align
from app.core.rules import WHITESPACE, WHITESPACE_LABELS, Rules
from app.io import load as io_load
from app.io.load import LABELS
from app.io.longpath import display
from app.ui import glyphs
from app.ui.diffview import DiffView
from app.ui.folderview import FolderView
from app.ui.hexview import HexView
from app.ui.imageview import ImageView
from app.ui.tableview import TableView

#: What the View switch offers, in order.
VIEW_LABELS = {"text": "Text", "table": "Table", "hex": "Hex", "image": "Image"}


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
    """The strip over one side: name, folder, what was detected, and trouble."""

    retry = Signal()
    menuRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "sidehead")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.name = QLabel()
        self.name.setProperty("role", "sidename")
        self.where = QLabel()
        self.where.setProperty("role", "sidewhere")
        self.where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.facts = QToolButton()
        self.facts.setProperty("role", "sidefacts")
        self.facts.setFocusPolicy(Qt.NoFocus)
        self.facts.setToolTip("Encoding, line endings and saving for this side")
        self.facts.clicked.connect(lambda _c=False: self.menuRequested.emit())
        self.state = QLabel()
        self.state.setProperty("role", "sidestate")
        self.again = QToolButton()
        self.again.setText("Retry")
        self.again.setProperty("role", "retry")
        self.again.setFocusPolicy(Qt.NoFocus)
        self.again.clicked.connect(self.retry)
        self.again.hide()

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(self.name)
        top.addWidget(self.where, 1)
        top.addWidget(self.state)
        top.addWidget(self.again)
        top.addWidget(self.facts)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 7, 12, 7)
        box.addLayout(top)

    def show_side(self, side: core.Side, *, encoding_changed: bool = False) -> None:
        path = display(side.path)
        folder, name = ntpath.split(path)
        self.name.setText(side.title or name or path or "Nothing chosen")
        self.where.setText(folder if not side.title else path)
        self.where.setToolTip(path)
        facts = side.loaded.facts if side.loaded is not None and side.state == core.READY else ""
        if facts and side.doc is not None:
            # What a save would write, which after an edit or a change from
            # this menu is not what was read.
            label = LABELS.get(side.encoding, side.encoding) + (" BOM" if side.bom else "")
            eol = _eol_now(side.doc.endings) or side.loaded.eol
            parts = [label + (" (on save)" if encoding_changed else "")]
            if eol:
                parts.append(eol)
            count = len(side.doc.lines)
            parts.append(f"{count:,} line{'s' if count != 1 else ''}")
            facts = "  ·  ".join(parts)
        if side.readonly and facts:
            facts += "  ·  read-only"
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
        value = "true" if focused else "false"
        if self.property("focus") != value:
            self.setProperty("focus", value)
            self.style().unpolish(self)
            self.style().polish(self)


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

    def __init__(self, session: core.Session, tokens: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._tokens = tokens
        self._shown_result = None
        self._matches: list[tuple[int, int]] = []
        self._pending_saves: set[int] = set()
        self._saves_ok = True
        #: The other modes' views, made the first time the pair turns out to
        #: need one. None until then.
        self.folders: FolderView | None = None
        self.sibling = siblings.for_pair(session.sides[0].path, session.sides[1].path)
        self._launch_request = 0
        #: "auto", or what the View switch (or --mode) chose.
        self.mode = session.options.mode if session.options.mode in VIEW_LABELS else "auto"
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
        self.stack.addWidget(self.images)
        self.stack.addWidget(self.table)

        self.heads = (SideHead(), SideHead())
        for index, head in enumerate(self.heads):
            head.retry.connect(lambda i=index: self._reload_side(i))
            head.menuRequested.connect(lambda i=index: self._side_menu(i))
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
        inner.addWidget(self.stack, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 2, 8, 0)
        outer.setSpacing(6)
        self._toolrow = self._toolbar()
        outer.addWidget(self._toolrow)
        outer.addWidget(self.find)
        outer.addWidget(card, 1)

        session.changed.connect(self.refresh)
        session.saved.connect(self._saved)
        self.apply_tokens(tokens)
        self.refresh()

    # ------------------------------------------------------------- toolbar

    def _nav(self, icon: str, tip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setProperty("role", "nav")
        button.setProperty("glyph", icon)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(lambda _c=False: slot())
        self._navs.append(button)
        return button

    def _toolbar(self) -> QWidget:
        self._navs: list[QToolButton] = []
        row = QWidget()
        row.setProperty("role", "toolrow")
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self._first = self._nav("diff_first", "First difference (Home)",
                                lambda: self._navigate("first"))
        self._prev = self._nav("diff_prev", "Previous difference (Alt+Up)",
                               lambda: self._navigate("previous"))
        self._next = self._nav("diff_next", "Next difference (Alt+Down)",
                               lambda: self._navigate("next"))
        self._last = self._nav("diff_last", "Last difference (End)",
                               lambda: self._navigate("last"))
        for button in (self._first, self._prev, self._next, self._last):
            box.addWidget(button)
        self.count = QLabel()
        self.count.setProperty("role", "count")
        box.addWidget(self.count)
        box.addStretch(1)

        segments = QWidget()
        segments.setProperty("role", "segments")
        segments.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(segments)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(2)
        self.rules_button = QPushButton("Rules")
        self.rules_button.setProperty("role", "segment")
        self.rules_button.setCheckable(True)
        self.rules_button.setFocusPolicy(Qt.NoFocus)
        self.rules_button.setToolTip("What counts as a difference. Ctrl+I turns them all "
                                     "off and on.")
        self._rules_menu = QMenu(self)
        self._rules_menu.aboutToShow.connect(self._fill_rules_menu)
        self.rules_button.setMenu(self._rules_menu)
        seg.addWidget(self.rules_button)
        self._char = QPushButton("Characters")
        self._word = QPushButton("Words")
        for button, mode in ((self._char, "char"), (self._word, "word")):
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip("Mark what changed inside a line by "
                              + ("character" if mode == "char" else "word"))
            button.clicked.connect(lambda _c=False, m=mode: self._set_intraline(m))
            seg.addWidget(button)
        self._structure = QPushButton("Structure")
        self._structure.setProperty("role", "segment")
        self._structure.setCheckable(True)
        self._structure.setFocusPolicy(Qt.NoFocus)
        kind = self.session.format_kind
        self._structure.setToolTip(
            f"Compare by {formats.names().get(kind, 'structure')}: what the file says, "
            "not how it is laid out. Off compares and edits the plain text.")
        self._structure.clicked.connect(lambda on: self.session.set_structure(bool(on)))
        self._structure.setVisible(kind != formats.PLAIN)
        seg.insertWidget(0, self._structure)
        box.addWidget(segments)
        self._text_segments = segments
        self._view_button = QToolButton()
        self._view_button.setProperty("role", "retry")
        self._view_button.setFocusPolicy(Qt.NoFocus)
        self._view_button.setPopupMode(QToolButton.InstantPopup)
        self._view_button.setToolTip("Show this pair as text, as bytes, or as pictures")
        self._view_menu = QMenu(self)
        self._view_menu.aboutToShow.connect(self._fill_view_menu)
        self._view_button.setMenu(self._view_menu)
        # 1.1: the language the text is coloured as. Detected from the
        # file's name; the menu picks another, or none.
        self._language = QToolButton()
        self._language.setProperty("role", "retry")
        self._language.setFocusPolicy(Qt.NoFocus)
        self._language.setPopupMode(QToolButton.InstantPopup)
        self._language.setToolTip("The language the text is coloured as")
        self._language_menu = QMenu(self)
        self._language_menu.aboutToShow.connect(self._fill_language_menu)
        self._language.setMenu(self._language_menu)
        box.addSpacing(6)
        box.addWidget(self._language)
        box.addSpacing(2)
        box.addWidget(self._view_button)
        box.addSpacing(8)
        self._copy_left = self._nav("copy_left", "Copy this difference to the left (Alt+Left)",
                                    lambda: self._command("copy-left"))
        self._copy_right = self._nav("copy_right",
                                     "Copy this difference to the right (Alt+Right)",
                                     lambda: self._command("copy-right"))
        self._undo = self._nav("undo", "Undo on this side (Ctrl+Z)", lambda: self._command("undo"))
        self._redo = self._nav("redo", "Redo on this side (Ctrl+Y)", lambda: self._command("redo"))
        self._save = self._nav("save", "Save this side (Ctrl+S); both with Ctrl+Shift+S",
                               lambda: self._command("save"))
        self._edit_buttons = (self._copy_left, self._copy_right, self._undo, self._redo,
                              self._save)
        for button in self._edit_buttons:
            box.addWidget(button)
        box.addSpacing(8)
        self._swap = self._nav("swap", "Swap sides (Ctrl+U)", self.session.swap)
        self._reload = self._nav("refresh", "Compare again from disk (Ctrl+R)",
                                 self.session.reload)
        box.addWidget(self._swap)
        box.addWidget(self._reload)
        return row

    def _fill_rules_menu(self) -> None:
        menu = self._rules_menu
        menu.clear()
        rules = self.session.rules
        for value in WHITESPACE:
            action = menu.addAction(WHITESPACE_LABELS[value])
            action.setCheckable(True)
            action.setChecked(rules.whitespace == value)
            action.triggered.connect(
                lambda _c=False, v=value: self._change_rules(whitespace=v))
        menu.addSeparator()
        case = menu.addAction("Ignore case")
        case.setCheckable(True)
        case.setChecked(rules.case)
        case.triggered.connect(lambda c: self._change_rules(case=c))
        blank = menu.addAction("Ignore blank lines")
        blank.setCheckable(True)
        blank.setChecked(rules.blank_lines)
        blank.triggered.connect(lambda c: self._change_rules(blank_lines=c))
        comments = menu.addAction("Ignore comments" + (
            f"  ({' '.join(m.strip() for m in rules.markers)})" if rules.markers
            else "  (not known for this file type)"))
        comments.setCheckable(True)
        comments.setChecked(rules.comments)
        comments.setEnabled(bool(rules.markers))
        comments.triggered.connect(lambda c: self._change_rules(comments=c))
        if rules.patterns:
            menu.addSeparator()
            for pattern in rules.patterns:
                item = menu.addAction(f"Unimportant: {pattern}")
                item.setEnabled(False)
        menu.addSeparator()
        master = menu.addAction("Rules on\tCtrl+I")
        master.setCheckable(True)
        master.setChecked(rules.enabled)
        master.triggered.connect(lambda _c=False: self._command("rules"))

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
            if self.view.state.current is not None:
                self._copy_block(self.view.state.current, 0 if name == "copy-left" else 1)
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
        elif name == "edit":
            if self._can_edit(side) and self._current_or_say():
                self.view.begin_edit()
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
        self.session.reload()
        if self.folders is not None:
            self.folders.session.start()

    def _reload_side(self, index: int) -> None:
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
        s = self.session
        side = s.sides[index]
        menu = QMenu(self)
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
        head = self.heads[index]
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(head.facts.mapToGlobal(head.facts.rect().bottomLeft()))

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
        for button in self._navs + [self.find.previous, self.find.next, self.find.close_button]:
            button.setIcon(glyphs.icon(button.property("glyph"), colour=tokens["txt_1"],
                                       muted=tokens["txt_2"], size=16, ratio=ratio))
        self.view.apply_tokens(tokens)
        if self.folders is not None:
            self.folders.apply_tokens(tokens)
        self.hex.apply_tokens(tokens)
        self.images.apply_tokens(tokens)
        self.table.apply_tokens(tokens)
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

    def refresh(self) -> None:
        s = self.session
        for index, (head, side) in enumerate(zip(self.heads, s.sides)):
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
        elif kind == core.TEXT and s.result is not None:
            if s.result is not self._shown_result:
                self._shown_result = s.result
                left, right = s.result_lines
                self.view.set_comparison(s.result, left, right, s.options.intraline, s.pins)
                self._colour()
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
        current = self.stack.currentWidget()
        self._toolrow.setVisible(current in (self.view, self.message, self.hex, self.images,
                                             self.table))
        texty = current in (self.view, self.message)
        self._text_segments.setVisible(texty)
        for button in self._edit_buttons:
            button.setVisible(texty)
        for button in (self._first, self._prev, self._next, self._last):
            button.setVisible(current is not self.images)
        self._view_button.setText("View: " + VIEW_LABELS.get(shown, "Text"))
        self._view_button.setVisible(kind in (core.TEXT, core.BINARY))
        self._language.setVisible(current is self.view)
        self._language.setText(self._language_label())
        self._update_position()
        self.titleChanged.emit()

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

    def _language_label(self) -> str:
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
        self._language.setText(self._language_label())

    def set_language(self, language: str) -> None:
        self.language = language
        self._colour()

    def _fill_language_menu(self) -> None:
        menu = self._language_menu
        menu.clear()
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

    def _fill_view_menu(self) -> None:
        self._view_menu.clear()
        shown = self.shown_mode()
        for mode in self.available_modes():
            action = self._view_menu.addAction(VIEW_LABELS[mode])
            action.setCheckable(True)
            action.setChecked(mode == shown)
            action.triggered.connect(lambda _c=False, m=mode: self.set_mode(m))

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
            self.folders = FolderView(folder, self._tokens, mask=s.options.folder_mask)
            self.folders.openPair.connect(self.openPair)
            self.folders.openExtracted.connect(self.openExtracted)
            self.folders.status.connect(self.status)
            self.folders.setting.connect(self.setting)
            self.folders.command.connect(self._command)
            self.stack.addWidget(self.folders)
            folder.start()
        return self.folders

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
        rules = self.session.rules
        self.rules_button.setChecked(rules.enabled and rules.any)
        self.rules_button.setText("Rules" if not (rules.enabled and rules.any)
                                  else "Rules on")
        self._structure.setChecked(self.session.structure)
        mode = self.session.options.intraline
        self._char.setChecked(mode == "char")
        self._word.setChecked(mode == "word")
        self.heads[0].set_focused(self.view.focused_side == 0)
        self.heads[1].set_focused(self.view.focused_side == 1)

    def _update_position(self) -> None:
        s = self.session
        if self.stack.currentWidget() is self.table:
            result = self.table.model.result
            total = len(result.differences) if result else 0
            for button in (self._first, self._prev, self._next, self._last):
                button.setEnabled(total > 0)
            self.count.setText(f"{total:,} record{'s' if total != 1 else ''} differ"
                               if result else "Comparing...")
            return
        if self.stack.currentWidget() is self.hex:
            current, total = self.hex.position()
            for button in (self._first, self._prev, self._next, self._last):
                button.setEnabled(total > 0)
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
            return
        result = s.result if s.kind == core.TEXT else None
        has = bool(result and result.differences)
        for button in (self._first, self._prev, self._next, self._last):
            button.setEnabled(has)
        side = s.sides[self.view.focused_side]
        on_block = has and self.view.state.current is not None
        self._copy_left.setEnabled(on_block and s.sides[0].editable)
        self._copy_right.setEnabled(on_block and s.sides[1].editable)
        self._undo.setEnabled(side.doc is not None and side.doc.can_undo)
        self._redo.setEnabled(side.doc is not None and side.doc.can_redo)
        self._save.setEnabled(side.editable and (side.dirty or s.encoding_changed(
            self.view.focused_side)))
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
        self.heads[0].set_focused(self.view.focused_side == 0)
        self.heads[1].set_focused(self.view.focused_side == 1)
        if result is not None:
            self.status.emit(self._status_line(result))

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

    def focus_view(self) -> None:
        current = self.stack.currentWidget()
        if self.folders is not None and current is self.folders:
            self.folders.focus()
        elif current in (self.hex, self.images):
            current.setFocus(Qt.OtherFocusReason)
        elif current is self.table:
            self.table.grid.setFocus(Qt.OtherFocusReason)
        else:
            self.view.setFocus(Qt.OtherFocusReason)

    def set_rules(self, rules: Rules) -> None:
        self.session.set_rules(rules)
