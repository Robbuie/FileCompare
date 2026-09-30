"""The sync preview: every action with a box beside it, before anything moves.

File Manager's rule is that a destructive operation is seen before it runs,
and that rule is kept here because File Manager does not show this plan
again: once it is sent, it is queued. So the list is complete -- every copy,
every removal, and everything left alone with the reason -- and nothing is
sent that somebody could not have unticked.

Nothing here reads the disk. The plan is `core/syncplan.py`'s, from the tree
the folder view already holds; whether a side is on a share (removals there
skip the Recycle Bin) arrives from the loader after the dialog is open.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import folders as F
from app.core import syncplan as S
from app.ui.diffview import parse_colour

ACT_LABELS = {S.ACT_COPY: "Copy", S.ACT_REMOVE: "Remove", S.ACT_SKIP: "Leave"}


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return ""


def _when(t: float) -> str:
    return _dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else ""


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


class SyncDialog(QDialog):
    """`request` holds the jobs to send once the dialog is accepted."""

    def __init__(self, tree: F.Node, left: str, right: str, *, direction: str = S.TO_RIGHT,
                 mode: str = S.UPDATE, nodes: list[F.Node] | None = None,
                 titles: tuple[str, str] = ("", ""), tokens: dict[str, str] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Synchronize folders")
        self.resize(860, 560)
        self.tree_root = tree
        self.left, self.right = left, right
        self.titles = (titles[0] or left, titles[1] or right)
        self.nodes = nodes
        self.direction = direction
        self.mode = mode
        self.tokens = tokens or {}
        self.remote: tuple[bool, bool] | None = None
        self.request: dict | None = None
        self.plan: S.Plan | None = None

        self.directions: dict[str, QPushButton] = {}
        self.modes: dict[str, QPushButton] = {}
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self._segments(
            self.directions, ((S.TO_RIGHT, "Left to right"), (S.TO_LEFT, "Right to left")),
            self.set_direction))
        if mode in (S.UPDATE, S.MIRROR):
            top.addWidget(self._segments(
                self.modes, ((S.UPDATE, "Update"), (S.MIRROR, "Mirror")), self.set_mode))
        else:
            label = QLabel("Copy the selected rows" if mode == S.COPY
                           else "Remove the selected rows")
            label.setProperty("role", "note")
            top.addWidget(label)
        top.addStretch(1)
        self.where = QLabel()
        self.where.setProperty("role", "note")
        self.where.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.list = QTreeWidget()
        self.list.setProperty("role", "foldertree")
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setHeaderLabels(["", "Path", "Size", "Source", "Target", "Why"])
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.list.itemChanged.connect(lambda _i, _c: self._summarise())

        self.warning = QLabel()
        self.warning.setProperty("role", "warn")
        self.warning.setWordWrap(True)
        self.summary = QLabel()
        self.summary.setProperty("role", "note")

        self.all = QPushButton("Tick all")
        self.all.clicked.connect(lambda: self._tick(True))
        self.none = QPushButton("Untick all")
        self.none.clicked.connect(lambda: self._tick(False))
        self.go = QPushButton("Send to File Manager")
        self.go.setProperty("role", "primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self._send)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.all)
        buttons.addWidget(self.none)
        buttons.addStretch(1)
        buttons.addWidget(self.summary)
        buttons.addSpacing(12)
        buttons.addWidget(cancel)
        buttons.addWidget(self.go)

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        box.addLayout(top)
        box.addWidget(self.where)
        box.addWidget(self.list, 1)
        box.addWidget(self.warning)
        box.addLayout(buttons)

        self._fill()

    def _segments(self, store: dict, choices, choose) -> QWidget:
        holder = QWidget()
        holder.setProperty("role", "segments")
        holder.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(holder)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        for value, label in choices:
            button = QPushButton(label)
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, v=value: choose(v))
            row.addWidget(button)
            store[value] = button
        return holder

    # ------------------------------------------------------------ choices

    def set_direction(self, direction: str) -> None:
        self.direction = direction
        self._fill()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._fill()

    def set_remote(self, remote: tuple[bool, bool]) -> None:
        """Whether each side is on a share, once the loader has said."""
        self.remote = remote
        self._summarise()

    # ------------------------------------------------------------ the list

    def _fill(self) -> None:
        for value, button in self.directions.items():
            button.setChecked(value == self.direction)
        for value, button in self.modes.items():
            button.setChecked(value == self.mode)
        source, target = (self.titles if self.direction == S.TO_RIGHT
                          else self.titles[::-1])
        if self.mode == S.REMOVE:
            self.where.setText(f"From  {target}")
        else:
            self.where.setText(f"From  {source}\nTo    {target}")
        self.plan = S.plan(self.tree_root, self.direction, self.mode, nodes=self.nodes)
        ink = {
            S.ACT_COPY: self.tokens.get("diff_add_bar" if self.direction == S.TO_RIGHT
                                        else "diff_del_bar"),
            S.ACT_REMOVE: self.tokens.get("warn"),
            S.ACT_SKIP: self.tokens.get("txt_2"),
        }
        self.list.blockSignals(True)
        self.list.clear()
        items = []
        for action in self.plan.actions:
            label = ACT_LABELS[action.act]
            name = action.rel + ("\\" if action.is_dir else "")
            size = ""
            if action.act == S.ACT_COPY:
                size = _size(action.size)
            if action.is_dir and action.act != S.ACT_SKIP:
                size = (f"{_count(action.files, 'file')}, {size}" if size
                        else _count(action.files, "file"))
            item = QTreeWidgetItem([label, name, size, _when(action.source_mtime),
                                    _when(action.target_mtime), action.why])
            item.setData(0, Qt.UserRole, action)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            if action.act == S.ACT_SKIP:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            else:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked)
            colour = ink.get(action.act)
            if colour:
                brush = QBrush(parse_colour(colour))
                for column in (0, 5):
                    item.setForeground(column, brush)
            items.append(item)
        self.list.addTopLevelItems(items)
        self.list.blockSignals(False)
        self._summarise()

    def _tick(self, on: bool) -> None:
        self.list.blockSignals(True)
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)
        self._summarise()

    def chosen(self) -> list[S.Action]:
        out = []
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            if item.flags() & Qt.ItemIsUserCheckable and item.checkState(0) == Qt.Checked:
                out.append(item.data(0, Qt.UserRole))
        return out

    def _summarise(self) -> None:
        plan = self.plan
        chosen = self.chosen()
        copies = [a for a in chosen if a.act == S.ACT_COPY]
        removals = [a for a in chosen if a.act == S.ACT_REMOVE]
        parts = []
        if copies:
            files = sum(a.files for a in copies)
            parts.append(f"copy {_count(files, 'file')}, {_size(sum(a.size for a in copies))}")
        if removals:
            parts.append(f"remove {_count(len(removals), 'item')}")
        skipped = len(plan.skipped) if plan else 0
        if skipped:
            parts.append(f"{skipped:,} left alone")
        if plan is not None and plan.empty and not skipped:
            self.summary.setText("Already in step: nothing to copy or remove.")
        else:
            self.summary.setText("  ·  ".join(parts) if parts else "Nothing ticked.")

        warnings = []
        refusal = S.refusal(self.left, self.right)
        if refusal:
            warnings.append(refusal)
        if plan is not None and plan.no_removals:
            warnings.append(plan.no_removals)
        if removals:
            target_remote = None
            if self.remote is not None:
                target_remote = self.remote[1] if self.direction == S.TO_RIGHT else self.remote[0]
            if target_remote:
                warnings.append("The target is on a network share: Windows removes files "
                                "there permanently, without the Recycle Bin.")
            else:
                warnings.append("Removed items go to the Recycle Bin.")
        if plan is not None and plan.mode == S.COPY and copies:
            warnings.append("Picked rows replace what is on the target, whichever is newer.")
        self.warning.setText("  ".join(warnings))
        self.warning.setVisible(bool(warnings))
        self.go.setEnabled(bool(copies or removals) and not refusal)
        self.go.setText(f"Send to File Manager, removing {len(removals):,}" if removals
                        else "Send to File Manager")

    def _send(self) -> None:
        chosen = self.chosen()
        if not chosen or self.plan is None:
            return
        source, target = (self.titles if self.direction == S.TO_RIGHT
                          else self.titles[::-1])
        self.request = S.request(self.plan, chosen, self.left, self.right,
                                 title=f"{source} -> {target}")
        self.accept()
