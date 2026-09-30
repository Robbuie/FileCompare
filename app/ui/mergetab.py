"""The three-way merge tab: one change at a time above, the whole output below.

Top: the current change as it is in **mine**, the **base** and **theirs**,
each with a few lines of the file around it in grey, so a conflict is read as
three short passages rather than hunted for in three long files. Under them,
the buttons that settle it: take mine, take theirs, both in either order, the
base, or edit it by hand.

Bottom: the output file as it stands, with every change washed in its
colour -- conflicts red until settled -- and the current one outlined. Git's
markers stand in for an unsettled conflict, so an output saved before the end
is obviously not finished. "Edit freely" turns the output into an ordinary
text editor for the last touches; the chunk buttons stop there, since the
text no longer comes from them.

Keys: Ctrl+Alt+Down and Up for the next and previous conflict, Alt+Down and
Up for any change, Alt+Left takes mine and Alt+Right theirs -- the copy keys of
the text view, in the direction the text travels -- and Ctrl+S saves.
"""

from __future__ import annotations

import ntpath

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.diff import merge3 as M
from app.core.mergesession import MergeSession
from app.io.longpath import display
from app.ui.diffview import mono_font, parse_colour

CONTEXT = 3

KIND_WORDS = {
    M.MINE: "changed in mine only -- taken",
    M.THEIRS: "changed in theirs only -- taken",
    M.BOTH: "the same change on both sides -- taken",
    M.CONFLICT: "a conflict",
}


class _Passage(QWidget):
    """One of the three: a title and the lines of the current change."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = QLabel(title)
        self.title.setProperty("role", "sidename")
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setProperty("role", "passage")
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(self.title)
        box.addWidget(self.text, 1)

    def show_lines(self, before: list[str], body: list[str], after: list[str],
                   colours: dict[str, QColor]) -> None:
        self.text.setPlainText("\n".join(before + (body or ["(nothing)"]) + after))
        selections = []
        for start, count, colour in ((0, len(before), None),
                                     (len(before), max(1, len(body)), colours["body"]),
                                     (len(before) + max(1, len(body)), len(after), None)):
            for number in range(start, start + count):
                block = self.text.document().findBlockByNumber(number)
                if not block.isValid():
                    continue
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(block)
                selection.format.setProperty(QTextFormat.FullWidthSelection, True)
                if colour is not None:
                    selection.format.setBackground(colour)
                    if not body:
                        selection.format.setForeground(colours["muted"])
                else:
                    selection.format.setForeground(colours["muted"])
                selections.append(selection)
        self.text.setExtraSelections(selections)


class MergeTab(QWidget):
    titleChanged = Signal()
    status = Signal(str)
    savesFinished = Signal(bool)
    #: The merge ended: True when the output was saved with nothing unresolved.
    finished = Signal(bool)

    def __init__(self, session: MergeSession, tokens: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = tokens
        self.current: int | None = None
        self._spans: list[tuple[int, int]] = []

        self.count = QLabel()
        self.count.setProperty("role", "count")
        self.kind = QLabel()
        self.kind.setProperty("role", "note")
        buttons = [
            ("Take mine", "Alt+Left", M.TAKE_MINE),
            ("Take theirs", "Alt+Right", M.TAKE_THEIRS),
            ("Mine, then theirs", "", M.MINE_THEN_THEIRS),
            ("Theirs, then mine", "", M.THEIRS_THEN_MINE),
            ("Base", "", M.TAKE_BASE),
        ]
        self.choices: list[QPushButton] = []
        bar = QHBoxLayout()
        bar.setSpacing(4)
        nav = [("Previous conflict", "Ctrl+Alt+Up", lambda: self.step(-1, True)),
               ("Next conflict", "Ctrl+Alt+Down", lambda: self.step(1, True))]
        for label, keys, slot in nav:
            button = QPushButton(label)
            button.setToolTip(keys)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, s=slot: s())
            bar.addWidget(button)
        bar.addWidget(self.count)
        bar.addStretch(1)
        for label, keys, resolution in buttons:
            button = QPushButton(label)
            button.setToolTip(keys or label)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, r=resolution: self.take(r))
            bar.addWidget(button)
            self.choices.append(button)
        self.edit_chunk = QPushButton("Edit...")
        self.edit_chunk.setToolTip("Write this part of the output by hand")
        self.edit_chunk.setFocusPolicy(Qt.NoFocus)
        self.edit_chunk.clicked.connect(lambda _c=False: self.edit_current())
        bar.addWidget(self.edit_chunk)
        self.choices.append(self.edit_chunk)

        self.passages = (_Passage("Mine"), _Passage("Base"), _Passage("Theirs"))
        three = QHBoxLayout()
        three.setSpacing(8)
        for passage in self.passages:
            three.addWidget(passage, 1)
        top = QWidget()
        top_box = QVBoxLayout(top)
        top_box.setContentsMargins(10, 8, 10, 8)
        top_box.addLayout(bar)
        top_box.addWidget(self.kind)
        top_box.addLayout(three, 1)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.output.setProperty("role", "passage")
        self.output.cursorPositionChanged.connect(self._clicked_output)
        self.freehand = QPushButton("Edit freely")
        self.freehand.setCheckable(True)
        self.freehand.setFocusPolicy(Qt.NoFocus)
        self.freehand.setToolTip("Edit the output as text. The buttons above stop "
                                 "applying once it is edited by hand.")
        self.freehand.toggled.connect(self._freehand)
        self.save_button = QPushButton("Save")
        self.save_button.setProperty("role", "primary")
        self.save_button.setToolTip("Ctrl+S")
        self.save_button.clicked.connect(lambda _c=False: self.save())
        self.where = QLabel()
        self.where.setProperty("role", "sidewhere")
        out_bar = QHBoxLayout()
        title = QLabel("Output")
        title.setProperty("role", "sidename")
        out_bar.addWidget(title)
        out_bar.addWidget(self.where, 1)
        out_bar.addWidget(self.freehand)
        out_bar.addWidget(self.save_button)
        bottom = QWidget()
        bottom_box = QVBoxLayout(bottom)
        bottom_box.setContentsMargins(10, 8, 10, 8)
        bottom_box.addLayout(out_bar)
        bottom_box.addWidget(self.output, 1)

        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setSizes([300, 400])
        card = QFrame()
        card.setProperty("role", "card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(1, 1, 1, 1)
        inner.addWidget(split)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 2, 8, 0)
        outer.addWidget(card, 1)

        session.changed.connect(self.refresh)
        session.saved.connect(self._saved)
        self.apply_tokens(tokens)
        self.refresh()

    # ---------------------------------------------------------- for window

    def title(self) -> str:
        name = ntpath.basename(display(self.session.output_path or self.session.paths["mine"]))
        return f"{'* ' if self.session.dirty else ''}Merge  {name}"

    def tooltip(self) -> str:
        p = self.session.paths
        return (f"mine: {display(p['mine'])}\ntheirs: {display(p['theirs'])}\n"
                f"base: {display(p['base'])}\noutput: {display(self.session.output_path)}")

    def focus_view(self) -> None:
        self.output.setFocus(Qt.OtherFocusReason)

    def stop(self) -> None:
        pass

    def save_all(self) -> bool:
        return self.save()

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        font = mono_font(tokens)
        for widget in [p.text for p in self.passages] + [self.output]:
            widget.setFont(font)
        self.refresh()

    # ------------------------------------------------------------ drawing

    def _colour(self, name: str) -> QColor:
        return parse_colour(self.tokens.get(name))

    def refresh(self) -> None:
        s = self.session
        self.where.setText(display(s.output_path) or "(no output file: Save asks where)")
        if s.merge is None:
            self.count.setText("Could not merge: " + s.problem if s.problem else "Reading...")
            self.titleChanged.emit()
            return
        lines, self._spans = s.output()
        if s.freehand is None:
            scroll = self.output.verticalScrollBar().value()
            self.output.blockSignals(True)
            self.output.setPlainText("\n".join(lines))
            self.output.blockSignals(False)
            self.output.verticalScrollBar().setValue(scroll)
            self._wash_output()
        if self.current is None:
            conflicts = s.merge.conflicts
            changes = s.merge.changes
            if conflicts:
                self.go(conflicts[0])
            elif changes:
                self.go(changes[0])
        self._show_current()
        self._update_count()
        self.titleChanged.emit()

    def _wash_output(self) -> None:
        s = self.session
        washes = {M.MINE: "diff_add_row", M.THEIRS: "diff_add_row", M.BOTH: "diff_add_row"}
        selections = []
        for index, (chunk, (start, stop)) in enumerate(zip(s.merge.chunks, self._spans)):
            if chunk.kind == M.EQUAL:
                continue
            name = washes.get(chunk.kind, "diff_chg_row")
            if chunk.conflict and not chunk.resolved:
                name = "diff_conflict_row"
            for number in range(start, stop):
                block = self.output.document().findBlockByNumber(number)
                if not block.isValid():
                    continue
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(block)
                selection.format.setProperty(QTextFormat.FullWidthSelection, True)
                selection.format.setBackground(self._colour(name))
                if index == self.current:
                    selection.format.setBackground(self._colour(
                        "diff_conflict_mark" if chunk.conflict and not chunk.resolved
                        else "diff_chg_mark"))
                selections.append(selection)
        self.output.setExtraSelections(selections)

    def _show_current(self) -> None:
        s = self.session
        index = self.current
        if s.merge is None or index is None:
            return
        chunk = s.merge.chunks[index]
        colours = {"body": self._colour("diff_conflict_row" if chunk.conflict
                                        else "diff_chg_row"),
                   "muted": self._colour("txt_2")}
        for passage, which in zip(self.passages, ("mine", "base", "theirs")):
            a, b = getattr(chunk, which)
            source = getattr(s.merge, which)
            passage.show_lines(source[max(0, a - CONTEXT):a], source[a:b],
                               source[b:b + CONTEXT], colours)
        words = KIND_WORDS.get(chunk.kind, "")
        if chunk.conflict:
            words += "  --  settled: " + _resolution(chunk) if chunk.resolved \
                else "  --  not settled yet"
        self.kind.setText(words)
        for button in self.choices:
            button.setEnabled(s.freehand is None and chunk.kind != M.EQUAL)

    def _update_count(self) -> None:
        s = self.session
        if s.merge is None:
            return
        conflicts = s.merge.conflicts
        left = s.unresolved
        if conflicts and self.current in conflicts:
            text = f"Conflict {conflicts.index(self.current) + 1} of {len(conflicts)}"
        elif conflicts:
            text = f"{len(conflicts)} conflict{'s' if len(conflicts) != 1 else ''}"
        else:
            text = f"No conflicts  ·  {len(s.merge.changes)} changes merged"
        if left:
            text += f"  ·  {left} unresolved"
        elif conflicts:
            text += "  ·  all resolved"
        self.count.setText(text)
        self.status.emit(text)

    # ------------------------------------------------------------ actions

    def go(self, index: int) -> None:
        s = self.session
        if s.merge is None or not (0 <= index < len(s.merge.chunks)):
            return
        self.current = index
        self._show_current()
        if self._spans and index < len(self._spans):
            start = self._spans[index][0]
            block = self.output.document().findBlockByNumber(start)
            if block.isValid():
                cursor = QTextCursor(block)
                self.output.blockSignals(True)
                self.output.setTextCursor(cursor)
                self.output.blockSignals(False)
                self.output.centerCursor()
            self._wash_output()
        self._update_count()

    def step(self, direction: int, conflicts_only: bool) -> None:
        s = self.session
        if s.merge is None:
            return
        pool = s.merge.conflicts if conflicts_only else s.merge.changes
        if not pool:
            self.status.emit("No conflicts" if conflicts_only else "No changes")
            return
        here = self.current if self.current is not None else -1
        if direction > 0:
            target = next((i for i in pool if i > here), pool[0])
        else:
            target = next((i for i in reversed(pool) if i < here), pool[-1])
        self.go(target)

    def take(self, resolution: str) -> None:
        if self.current is None:
            return
        self.session.resolve(self.current, resolution)
        chunk = self.session.merge.chunks[self.current]
        if chunk.conflict and self.session.merge.unresolved:
            # On to the next thing that needs a decision.
            self.step(1, True)

    def edit_current(self) -> None:
        s = self.session
        if s.merge is None or self.current is None:
            return
        chunk = s.merge.chunks[self.current]
        start = s.merge.chosen(chunk)
        if start is None:
            start = s.merge.lines_of(chunk, "mine")
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit this part of the output")
        editor = QPlainTextEdit("\n".join(start))
        editor.setFont(mono_font(self.tokens))
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box = QVBoxLayout(dialog)
        box.addWidget(editor)
        box.addWidget(buttons)
        dialog.resize(760, 360)
        if dialog.exec() == QDialog.Accepted:
            text = editor.toPlainText()
            s.resolve(self.current, M.CUSTOM, text.split("\n") if text else [])

    def _clicked_output(self) -> None:
        if self.session.freehand is not None or not self._spans:
            return
        line = self.output.textCursor().blockNumber()
        for index, (start, stop) in enumerate(self._spans):
            if start <= line < max(stop, start + 1) and \
                    self.session.merge.chunks[index].kind != M.EQUAL:
                if index != self.current:
                    self.current = index
                    self._show_current()
                    self._wash_output()
                    self._update_count()
                return

    def _freehand(self, on: bool) -> None:
        s = self.session
        if on:
            s.set_freehand(self.output.toPlainText().split("\n"))
            self.output.setReadOnly(False)
            self.output.setExtraSelections([])
            self.output.textChanged.connect(self._typed)
            self._show_current()
        else:
            self.freehand.blockSignals(True)
            self.freehand.setChecked(True)
            self.freehand.blockSignals(False)
            self.status.emit("The output was edited by hand; the chunk buttons stay off. "
                             "Close without saving to start again.")

    def _typed(self) -> None:
        self.session.set_freehand(self.output.toPlainText().split("\n"))
        self._update_count()
        self.titleChanged.emit()

    def save(self) -> bool:
        s = self.session
        if s.merge is None:
            return False
        if s.unresolved:
            answer = QMessageBox.question(
                self, "Unresolved conflicts",
                f"{s.unresolved} conflict{'s are' if s.unresolved != 1 else ' is'} still "
                "unresolved and will be saved with conflict markers. Save anyway?",
                QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Save:
                return False
        path = ""
        if not s.output_path:
            chosen, _f = QFileDialog.getSaveFileName(self, "Save the merge as",
                                                     s.paths["mine"])
            if not chosen:
                return False
            from PySide6.QtCore import QDir

            path = QDir.toNativeSeparators(chosen)
            s.output_path = path
        return s.save(path)

    def _saved(self, result) -> None:
        ok = getattr(result, "ok", False)
        if ok:
            self.status.emit(f"Saved {display(result.path)}")
            self.finished.emit(self.session.unresolved == 0)
        else:
            reason = getattr(result, "error", str(result))
            self.status.emit(f"Not saved: {reason}")
        self.savesFinished.emit(ok)
        self.titleChanged.emit()

    # ---------------------------------------------------------------- keys

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        if mods == (Qt.ControlModifier | Qt.AltModifier) and key in (Qt.Key_Down, Qt.Key_Up):
            self.step(1 if key == Qt.Key_Down else -1, True)
        elif mods == Qt.AltModifier and key in (Qt.Key_Down, Qt.Key_Up):
            self.step(1 if key == Qt.Key_Down else -1, False)
        elif mods == Qt.AltModifier and key == Qt.Key_Left:
            self.take(M.TAKE_MINE)
        elif mods == Qt.AltModifier and key == Qt.Key_Right:
            self.take(M.TAKE_THEIRS)
        elif mods == Qt.ControlModifier and key == Qt.Key_S:
            self.save()
        else:
            super().keyPressEvent(event)
            return
        event.accept()


def _resolution(chunk: M.Chunk) -> str:
    return {M.TAKE_MINE: "mine", M.TAKE_THEIRS: "theirs", M.MINE_THEN_THEIRS: "mine, then theirs",
            M.THEIRS_THEN_MINE: "theirs, then mine", M.TAKE_BASE: "the base",
            M.CUSTOM: "edited by hand"}.get(chunk.resolution, chunk.resolution)

