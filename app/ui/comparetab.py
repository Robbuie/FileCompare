"""One comparison tab: the toolbar, a header over each side, and the view.

The tab draws a `core.session.Session` and turns clicks into calls on it. It
never reads a file: which side is loading, which failed and why, and what the
comparison found all arrive through `Session.changed`.

When the two sides are not two text files -- still loading, one missing, two
folders, a binary pair -- the view is swapped for a message that says so in
words. A blank pane is never an answer.
"""

from __future__ import annotations

import ntpath

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import session as core
from app.core.rules import WHITESPACE, WHITESPACE_LABELS, Rules
from app.io.longpath import display
from app.ui import glyphs
from app.ui.diffview import DiffView


class SideHead(QWidget):
    """The strip over one side: name, folder, what was detected, and trouble."""

    retry = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "sidehead")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.name = QLabel()
        self.name.setProperty("role", "sidename")
        self.where = QLabel()
        self.where.setProperty("role", "sidewhere")
        self.where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.facts = QLabel()
        self.facts.setProperty("role", "sidefacts")
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

    def show_side(self, side: core.Side) -> None:
        path = display(side.path)
        folder, name = ntpath.split(path)
        self.name.setText(side.title or name or path or "Nothing chosen")
        self.where.setText(folder if not side.title else path)
        self.where.setToolTip(path)
        facts = side.loaded.facts if side.loaded is not None and side.state == core.READY else ""
        if side.readonly and facts:
            facts += "  ·  read-only"
        self.facts.setText(facts)
        bad = side.state in (core.FAILED, core.SLOW)
        if side.state == core.LOADING:
            self.state.setText("Reading...")
        elif bad:
            self.state.setText(side.error)
        else:
            self.state.setText("")
        self.state.setProperty("state", "bad" if bad else "")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.again.setVisible(bad)

    def set_focused(self, focused: bool) -> None:
        value = "true" if focused else "false"
        if self.property("focus") != value:
            self.setProperty("focus", value)
            self.style().unpolish(self)
            self.style().polish(self)


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


class CompareTab(QWidget):
    """Emits `titleChanged` when the tab's label should change and `status`
    with a line for the window's status bar."""

    titleChanged = Signal()
    status = Signal(str)

    def __init__(self, session: core.Session, tokens: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._tokens = tokens
        self._shown_result = None

        self.view = DiffView()
        self.view.currentChanged.connect(self._update_position)
        self.view.command.connect(self._command)
        self.message = Message()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.message)
        self.stack.addWidget(self.view)

        self.heads = (SideHead(), SideHead())
        self.heads[0].retry.connect(lambda: self.session.retry(core.LEFT))
        self.heads[1].retry.connect(lambda: self.session.retry(core.RIGHT))
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
        outer.addWidget(self._toolbar())
        outer.addWidget(card, 1)

        session.changed.connect(self.refresh)
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
                                self.view.first_difference)
        self._prev = self._nav("diff_prev", "Previous difference (Alt+Up)",
                               self.view.previous_difference)
        self._next = self._nav("diff_next", "Next difference (Alt+Down)",
                               self.view.next_difference)
        self._last = self._nav("diff_last", "Last difference (End)",
                               self.view.last_difference)
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
        box.addWidget(segments)
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
        if name == "swap":
            self.session.swap()
        elif name == "reload":
            self.session.reload()
        elif name == "rules":
            self.session.set_rules(self.session.rules.toggled())

    # --------------------------------------------------------------- theme

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens
        ratio = float(self.devicePixelRatioF() or 1.0)
        for button in self._navs:
            button.setIcon(glyphs.icon(button.property("glyph"), colour=tokens["txt_1"],
                                       muted=tokens["txt_2"], size=16, ratio=ratio))
        self.view.apply_tokens(tokens)
        self._head_spacer.setFixedWidth(self.view.gutter.width())

    # -------------------------------------------------------------- drawing

    def title(self) -> str:
        names = [ntpath.basename(display(side.path)) or "?" for side in self.session.sides]
        titles = [side.title for side in self.session.sides]
        if any(titles):
            names = [t or n for t, n in zip(titles, names)]
        if names[0].lower() == names[1].lower():
            return names[0]
        return f"{names[0]}  vs  {names[1]}"

    def tooltip(self) -> str:
        return "\n".join(display(side.path) for side in self.session.sides)

    def refresh(self) -> None:
        s = self.session
        for head, side in zip(self.heads, s.sides):
            head.show_side(side)
        self._sync_toggles()
        kind = s.kind
        if kind == core.TEXT and s.result is not None:
            if s.result is not self._shown_result:
                self._shown_result = s.result
                left, right = s.sides
                self.view.set_comparison(s.result, left.lines, right.lines,
                                         s.options.intraline)
            self.stack.setCurrentWidget(self.view)
        else:
            self._shown_result = None
            self.stack.setCurrentWidget(self.message)
            self.message.say(*self._explain(kind))
        self._update_position()
        self.titleChanged.emit()

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
        if kind == core.FOLDERS:
            return ("Two folders",
                    "Folder compare arrives in a later version. For now, File Manager's "
                    "Ctrl+Shift+F2 marks what differs between two folders by size and time.")
        if kind == core.MIXED:
            return ("A file and a folder",
                    "One side is a file and the other a folder. Choose two files.")
        if kind == core.BINARY:
            if s.byte_identical:
                return "Identical", "The two files are the same, byte for byte."
            both = all(side.loaded is not None and side.loaded.binary for side in s.sides)
            detail = ("Both files are binary" if both else "One side is binary")
            return ("The files differ",
                    f"{detail}, so they were compared by content hash only. "
                    "Hex compare arrives in a later version.")
        if s.problem:
            return "Could not compare", s.problem
        return "", ""

    def _sync_toggles(self) -> None:
        rules = self.session.rules
        self.rules_button.setChecked(rules.enabled and rules.any)
        self.rules_button.setText("Rules" if not (rules.enabled and rules.any)
                                  else "Rules on")
        mode = self.session.options.intraline
        self._char.setChecked(mode == "char")
        self._word.setChecked(mode == "word")
        self.heads[0].set_focused(self.view.focused_side == 0)
        self.heads[1].set_focused(self.view.focused_side == 1)

    def _update_position(self) -> None:
        s = self.session
        result = s.result if s.kind == core.TEXT else None
        has = bool(result and result.differences)
        for button in (self._first, self._prev, self._next, self._last):
            button.setEnabled(has)
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
        self.count.setText(text)
        self.count.setProperty("state", state)
        self.count.style().unpolish(self.count)
        self.count.style().polish(self.count)
        self.heads[0].set_focused(self.view.focused_side == 0)
        self.heads[1].set_focused(self.view.focused_side == 1)
        if result is not None:
            self.status.emit(self._status_line(result))

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
        if counts["deleted"]:
            parts.append(f"{counts['deleted']:,} only left")
        if counts["inserted"]:
            parts.append(f"{counts['inserted']:,} only right")
        if counts["ignored"]:
            parts.append(f"{counts['ignored']:,} ignored")
        lines = "  ·  ".join(parts) if parts else "no lines differ"
        return (f"{lines}    {self.session.rules.describe()}    "
                f"compared in {result.elapsed * 1000:.0f} ms")

    def focus_view(self) -> None:
        self.view.setFocus(Qt.OtherFocusReason)

    def set_rules(self, rules: Rules) -> None:
        self.session.set_rules(rules)
