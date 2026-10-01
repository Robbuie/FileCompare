"""The table compare view: one grid, rows matched on a key.

One grid rather than two, because the rows are already matched: a row in it
is one record, and each cell is what that record holds in that column. A cell
that differs shows both values, `old -> new`, in the change amber; a row on
one side only is red or green, as everywhere else in the application. The key
column is bold. The row header says which line of each file the record is on.

The comparison is `core/tables.py`'s and runs off the UI thread; this only
draws it and turns the bar's choices into a new request.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.core import tables as T
from app.ui.diffview import mono_font, parse_colour

ARROW = "  ->  "


class TableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.result: T.TableResult | None = None
        self.only_differences = False
        self.tokens: dict[str, str] = {}
        self._rows: list[T.Row] = []
        self._bold = QFont()
        self._bold.setBold(True)

    def set_result(self, result: T.TableResult | None) -> None:
        self.beginResetModel()
        self.result = result
        self._filter()
        self.endResetModel()

    def set_only_differences(self, on: bool) -> None:
        self.beginResetModel()
        self.only_differences = on
        self._filter()
        self.endResetModel()

    def _filter(self) -> None:
        rows = self.result.rows if self.result else []
        self._rows = [r for r in rows if r.status != T.SAME] if self.only_differences else list(rows)

    def row_at(self, index: int) -> T.Row:
        return self._rows[index]

    def rowCount(self, parent=QModelIndex()):  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802, B008
        return 0 if parent.isValid() or not self.result else len(self.result.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if not self.result:
            return None
        if orientation == Qt.Horizontal:
            column = self.result.columns[section]
            if role == Qt.DisplayRole:
                if column.left is None:
                    return f"{column.name} (right only)"
                if column.right is None:
                    return f"{column.name} (left only)"
                return column.name + ("  [key]" if section == self.result.key else "")
            if role == Qt.ForegroundRole:
                if column.left is None:
                    return QBrush(parse_colour(self.tokens.get("diff_add_bar")))
                if column.right is None:
                    return QBrush(parse_colour(self.tokens.get("diff_del_bar")))
            return None
        if role == Qt.DisplayRole and 0 <= section < len(self._rows):
            row = self._rows[section]
            left = f"L{row.left + 2 if self.result.left.header else row.left + 1}" \
                if row.left is not None else "  "
            right = f"R{row.right + 2 if self.result.right.header else row.right + 1}" \
                if row.right is not None else "  "
            return f"{left} {right}"
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not self.result:
            return None
        row = self._rows[index.row()]
        column = index.column()
        left = self.result.cell(row, column, 0)
        right = self.result.cell(row, column, 1)
        changed = column in row.cells
        if role == Qt.DisplayRole:
            if row.status == T.ONLY_RIGHT:
                return right
            if changed:
                return f"{left}{ARROW}{right}"
            return left
        if role == Qt.ToolTipRole and changed:
            return f"Left:  {left}\nRight: {right}"
        if role == Qt.ForegroundRole:
            name = {T.ONLY_LEFT: "diff_del_bar", T.ONLY_RIGHT: "diff_add_bar"}.get(row.status)
            if changed:
                name = "diff_chg_bar"
            return QBrush(parse_colour(self.tokens.get(name))) if name else None
        if role == Qt.FontRole and (changed or column == self.result.key):
            return self._bold
        return None


class TableView(QWidget):
    """Emits `optionsChanged(options)` when the comparison should run again."""

    optionsChanged = Signal(object)
    status = Signal(str)
    command = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.options = T.Options()
        self.model = TableModel(self)
        self.grid = QTableView()
        self.grid.setProperty("role", "grid")
        self.grid.setModel(self.model)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setWordWrap(False)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.verticalHeader().setDefaultSectionSize(22)

        self.key = QComboBox()
        self.key.setToolTip("The column that says which rows are the same record")
        self.key.activated.connect(self._key_chosen)
        # 1.3: workbooks. The sheet, matched by name, and values or formulas.
        self.sheet_label = QLabel("Sheet")
        self.sheet = QComboBox()
        self.sheet.setToolTip("The sheet compared. Sheets are matched by name; the "
                              "list says which differ.")
        self.sheet.activated.connect(self._sheet_chosen)
        self.sheet.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.key.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.formulas = self._toggle("Formulas", False, "formulas")
        self.formulas.setToolTip("Compare what was typed in each cell rather than "
                                 "the value Excel last calculated")
        self.note = ""
        self.header = self._toggle("First row is names", True, "header")
        self.case = self._toggle("Ignore case", False, "ignore_case")
        self.numbers = self._toggle("Numbers by value", True, "numeric")
        self.only = QPushButton("Differences only")
        self.only.setProperty("role", "segment")
        self.only.setCheckable(True)
        self.only.setFocusPolicy(Qt.NoFocus)
        self.only.toggled.connect(self.model.set_only_differences)
        self.line = QLabel()
        self.line.setProperty("role", "count")

        segments = QWidget()
        segments.setProperty("role", "segments")
        segments.setAttribute(Qt.WA_StyledBackground, True)
        seg = QHBoxLayout(segments)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(2)
        for button in (self.only, self.header, self.case, self.numbers, self.formulas):
            seg.addWidget(button)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(6)
        bar.addWidget(self.sheet_label)
        bar.addWidget(self.sheet)
        bar.addWidget(QLabel("Key"))
        bar.addWidget(self.key)
        bar.addWidget(segments)
        bar.addStretch(1)
        top = QWidget()
        top.setProperty("role", "folderbar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setLayout(bar)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(top)
        box.addWidget(self.line)
        box.addWidget(self.grid, 1)
        self.set_workbook(False)

    def set_workbook(self, on: bool) -> None:
        """Show the sheet list and the Formulas switch for a workbook pair."""
        for widget in (self.sheet_label, self.sheet, self.formulas):
            widget.setVisible(on)

    def set_sheets(self, states, current: str, note: str = "") -> None:
        """The sheet list, each name saying whether it differs."""
        self.note = note
        self.sheet.blockSignals(True)
        self.sheet.clear()
        for state in states:
            if not state.left:
                tag = "right only"
            elif not state.right:
                tag = "left only"
            else:
                tag = "same" if state.same else "differs"
            self.sheet.addItem(f"{state.name}  ({tag})", state.name)
        at = self.sheet.findData(current)
        self.sheet.setCurrentIndex(max(0, at))
        self.sheet.blockSignals(False)

    def _sheet_chosen(self, index: int) -> None:
        self._change(sheet=self.sheet.itemData(index) or "", key=None)

    def _toggle(self, label: str, on: bool, field: str) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("role", "segment")
        button.setCheckable(True)
        button.setChecked(on)
        button.setFocusPolicy(Qt.NoFocus)
        button.toggled.connect(lambda value, f=field: self._change(**{f: bool(value)}))
        return button

    def _change(self, **changes) -> None:
        from dataclasses import replace

        if "header" in changes:
            changes["key"] = None
        self.options = replace(self.options, **changes)
        self.optionsChanged.emit(self.options)

    def _key_chosen(self, index: int) -> None:
        value = self.key.itemData(index)
        self._change(key=value)

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self.model.tokens = tokens
        self.grid.setFont(mono_font(tokens))
        self.grid.viewport().update()

    def set_result(self, result: T.TableResult) -> None:
        self.model.set_result(result)
        self.key.blockSignals(True)
        self.key.clear()
        self.key.addItem("Row position", T.POSITION)
        for number, column in enumerate(result.columns):
            if column.left is not None and column.right is not None:
                self.key.addItem(column.name, number)
        at = self.key.findData(result.key)
        self.key.setCurrentIndex(max(0, at))
        self.key.blockSignals(False)
        self.grid.resizeColumnsToContents()
        self.line.setText(self.describe())
        self.status.emit(self.describe())

    def describe(self) -> str:
        r = self.model.result
        if r is None:
            return ""
        c = r.counts
        parts = [f"{len(r.rows):,} records"]
        for key, label in ((T.CHANGED, "changed"), (T.ONLY_LEFT, "only left"),
                           (T.ONLY_RIGHT, "only right")):
            if c.get(key):
                parts.append(f"{c[key]:,} {label}")
        if not r.differences:
            parts.append("no differences")
        matched = "by position" if r.key == T.POSITION else f"matched on {r.columns[r.key].name}"
        text = "  ·  ".join(parts) + f"  ·  {matched}"
        if self.sheet.isVisibleTo(self) and self.sheet.currentData():
            text = f"{self.sheet.currentData()}  ·  " + text
        text += f"  ·  {r.key_problem}" if r.key_problem else ""
        return text + (f"  ·  {self.note}" if self.note else "")

    def step(self, direction: int) -> None:
        rows = [i for i in range(self.model.rowCount())
                if self.model.row_at(i).status != T.SAME]
        if not rows:
            return
        current = self.grid.currentIndex().row()
        if direction > 0:
            target = next((r for r in rows if r > current), rows[0])
        else:
            target = next((r for r in reversed(rows) if r < current), rows[-1])
        self.grid.selectRow(target)
        self.grid.scrollTo(self.model.index(target, 0), QAbstractItemView.PositionAtCenter)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        mods = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
        key = event.key()
        if mods == Qt.AltModifier and key in (Qt.Key_Down, Qt.Key_Up):
            self.step(1 if key == Qt.Key_Down else -1)
        elif mods == Qt.ControlModifier and key == Qt.Key_U:
            self.command.emit("swap")
        elif mods == Qt.ControlModifier and key == Qt.Key_R:
            self.command.emit("reload")
        else:
            super().keyPressEvent(event)
            return
        event.accept()
