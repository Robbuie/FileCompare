"""The start page: two sides to fill in, and the button that compares them.

What a new tab shows (Ctrl+T), and what the window shows when it was started
with nothing to compare. Most comparisons arrive from File Manager with both
paths already chosen, so this is the less travelled way in and is kept plain:
a path field per side, a browse button, and dropping files.

Nothing here checks that a path exists. A typed path is handed to the session
as it is, and the session finds out off the UI thread; a missing file becomes
a side that says "Not found", which is a better answer than a field that turns
red while somebody is still typing into it. The browse button is the one
exception to the rule about the filesystem, and a narrow one: it is Windows'
own file dialog, which runs its own loop and is somebody asking.
"""

from __future__ import annotations

import ntpath

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StartTab(QWidget):
    compareRequested = Signal(str, str)
    browsed = Signal(int, str)          # side, the folder browsed from
    sessionRequested = Signal(str)      # 1.10: a .fcsession file to open

    def __init__(self, folders: tuple[str, str] = ("", ""),
                 parent: QWidget | None = None, *,
                 recent: list[tuple[str, str]] | None = None) -> None:
        super().__init__(parent)
        self._folders = list(folders)
        self._recent = list(recent or [])
        self.setAcceptDrops(True)

        card = QFrame()
        card.setProperty("role", "start")
        card.setMaximumWidth(760)
        title = QLabel("Compare")
        title.setProperty("role", "starttitle")
        note = QLabel("Choose a file for each side, paste two paths, or drop two files here.")
        note.setProperty("role", "note")

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.fields: list[QLineEdit] = []
        for row, name in enumerate(("LEFT", "RIGHT")):
            label = QLabel(name)
            label.setProperty("role", "sidelabel")
            field = QLineEdit()
            field.setProperty("role", "pathfield")
            field.setPlaceholderText("C:\\path\\to\\file.txt  or  \\\\server\\share\\file.txt")
            field.textChanged.connect(self._update)
            field.returnPressed.connect(self._go)
            browse = QPushButton("Browse")
            browse.clicked.connect(lambda _c=False, r=row: self._browse(r))
            grid.addWidget(label, row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(browse, row, 2)
            self.fields.append(field)

        self.go = QPushButton("Compare")
        self.go.setProperty("role", "primary")
        self.go.clicked.connect(self._go)
        hint = QLabel("From File Manager: Ctrl+F2 compares the two panes, "
                      "Alt+F2 the marked files.")
        hint.setProperty("role", "hint")
        self.open_session = QPushButton("Open session")
        self.open_session.setToolTip("A comparison saved with Ctrl+Alt+S: the same two paths, "
                                     "rules, filter and pins")
        self.open_session.clicked.connect(self._browse_session)
        buttons = QHBoxLayout()
        buttons.addWidget(hint, 1)
        buttons.addWidget(self.open_session)
        buttons.addWidget(self.go)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(28, 24, 28, 24)
        inner.setSpacing(10)
        inner.addWidget(title)
        inner.addWidget(note)
        inner.addSpacing(8)
        inner.addLayout(grid)
        inner.addSpacing(8)
        inner.addLayout(buttons)
        if self._recent:
            # The pairs compared lately, newest first: the second compare of
            # the same two files is usually the next morning.
            label = QLabel("RECENT")
            label.setProperty("role", "sidelabel")
            inner.addSpacing(10)
            inner.addWidget(label)
            for left, right in self._recent[:8]:
                button = QPushButton(f"{ntpath.basename(left) or left}   vs   "
                                     f"{ntpath.basename(right) or right}")
                button.setProperty("role", "recent")
                button.setToolTip(f"{left}\n{right}")
                button.setFocusPolicy(Qt.TabFocus)
                button.clicked.connect(lambda _c=False, l=left, r=right:
                                       self.compareRequested.emit(l, r))
                inner.addWidget(button)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self._update()

    def title(self) -> str:
        return "New comparison"

    def page_kind(self) -> str:
        return "start"

    def command_state(self, id_: str):
        from app.ui.commands import HIDDEN

        return HIDDEN

    def run_command(self, id_: str) -> None:
        pass

    def fill_menu(self, name: str, menu) -> None:
        pass

    def tooltip(self) -> str:
        return ""

    def focus_view(self) -> None:
        self.fields[0].setFocus(Qt.OtherFocusReason)

    def set_paths(self, left: str = "", right: str = "") -> None:
        if left:
            self.fields[0].setText(left)
        if right:
            self.fields[1].setText(right)

    def _update(self) -> None:
        self.go.setEnabled(all(field.text().strip() for field in self.fields))

    def _go(self) -> None:
        left, right = (field.text().strip().strip('"') for field in self.fields)
        if left and right:
            self.compareRequested.emit(left, right)

    def _browse(self, side: int) -> None:
        start = self.fields[side].text().strip() or self._folders[side] or self._folders[1 - side]
        path, _filter = QFileDialog.getOpenFileName(self, "Choose the "
                                                    + ("left" if side == 0 else "right")
                                                    + " file", start)
        if path:
            path = path.replace("/", "\\")
            self.fields[side].setText(path)
            self._folders[side] = ntpath.dirname(path)
            self.browsed.emit(side, self._folders[side])
            if not self.fields[1 - side].text().strip():
                self.fields[1 - side].setFocus()

    def _browse_session(self) -> None:
        start = self._folders[0] or self._folders[1]
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a saved session", start, "File Compare session (*.fcsession)")
        if path:
            self.sessionRequested.emit(path.replace("/", "\\"))

    # ------------------------------------------------------------ dropping

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [url.toLocalFile().replace("/", "\\") for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if not paths:
            return
        event.acceptProposedAction()
        if len(paths) == 1 and paths[0].lower().endswith(".fcsession"):
            self.sessionRequested.emit(paths[0])
            return
        if len(paths) >= 2:
            self.set_paths(paths[0], paths[1])
            self._go()
            return
        # One file: the side it was dropped on, or the empty side.
        over_right = event.position().x() > self.width() / 2
        empty = [i for i, field in enumerate(self.fields) if not field.text().strip()]
        side = 1 if over_right else 0
        if empty and side not in empty:
            side = empty[0]
        self.fields[side].setText(paths[0])
        if all(field.text().strip() for field in self.fields):
            self._go()
