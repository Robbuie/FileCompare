"""The menu bar and the labelled toolbar, built from `ui/commands.py` (1.17).

Both ask a provider -- the window -- what each command can do right now, and
tell it when one is chosen. Neither knows what a command does. The menus are
brought up to date as each one opens; the toolbar whenever the window says
the current page changed.

The toolbar's buttons are Beyond Compare's: an icon with a word under it,
in groups with a thin divider between. A button with more behind it (Rules,
Contents, Sync, Expand) does its main thing when clicked and opens its menu
from the arrow beside it; the arrow is drawn here, because the one Qt draws
for a styled button sits low and overlaps the label.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QMenuBar,
    QToolButton,
    QWidget,
)

from app.ui import glyphs
from app.ui.commands import COMMANDS, DYNAMIC, MENUS, TOOL_MENUS, TOOLBARS, State, menu_text, tool_tip
from app.ui.diffview import parse_colour


class Provider(Protocol):
    def command_state(self, id: str) -> State: ...  # noqa: A002, E704
    def run_command(self, id: str) -> None: ...  # noqa: A002, E704
    def fill_menu(self, name: str, menu: QMenu) -> None: ...  # noqa: E704


def build_menu(menu: QMenu, items, provider: Provider) -> None:
    """Fill `menu` from a list of ids, "-" and ">dynamic", and keep it up to
    date each time it opens."""
    for item in items:
        if item == "-":
            menu.addSeparator()
            continue
        if item.startswith(">"):
            name = item[1:]
            sub = menu.addMenu(DYNAMIC.get(name, name))
            sub.menuAction().setData(">" + name)
            sub.aboutToShow.connect(lambda s=sub, n=name: _fill(provider, n, s))
            continue
        command = COMMANDS[item]
        action = menu.addAction(menu_text(command))
        action.setData(item)
        action.setCheckable(command.checkable)
        if command.tip:
            action.setToolTip(command.tip)
        action.triggered.connect(lambda _c=False, i=item: provider.run_command(i))
    menu.setToolTipsVisible(True)
    menu.aboutToShow.connect(lambda m=menu: sync_menu(m, provider))


def _fill(provider: Provider, name: str, menu: QMenu) -> None:
    menu.clear()
    provider.fill_menu(name, menu)
    if menu.isEmpty():
        menu.addAction("Nothing here for this tab").setEnabled(False)


def sync_menu(menu: QMenu, provider: Provider) -> None:
    """Visible, enabled, checked and label for every item, from the page."""
    for action in menu.actions():
        data = action.data()
        if not data:
            continue
        state = provider.command_state(data)
        action.setVisible(state.visible)
        action.setEnabled(state.enabled)
        if data.startswith(">"):
            continue
        command = COMMANDS[data]
        if command.checkable:
            action.setChecked(bool(state.checked))
        label = state.label if state.label is not None else command.label
        if state.count is not None:
            label += f"  ({state.count:,})"
        action.setText(menu_text(command).replace(command.label, label, 1))


class MenuBar(QMenuBar):
    def __init__(self, provider: Provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "menubar")
        self.setNativeMenuBar(False)
        self.menus: dict[str, QMenu] = {}
        for title, items in MENUS:
            menu = self.addMenu(title)
            build_menu(menu, items, provider)
            self.menus[title.replace("&", "")] = menu


class ToolButton(QToolButton):
    """A toolbar button that draws its own menu arrow, small and centred on
    the icon, in the theme's muted ink."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.arrow_colour = ""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.menu() is None or not self.arrow_colour:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(parse_colour(self.arrow_colour), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        x = self.width() - 8.5
        y = self.iconSize().height() / 2 + 6
        painter.drawPolyline([QPointF(x - 3, y - 1.5), QPointF(x, y + 1.5), QPointF(x + 3, y - 1.5)])
        painter.end()


class ToolBar(QWidget):
    """The labelled toolbar. `set_kind` picks the buttons for a kind of page,
    `refresh` asks the provider about each one."""

    ICON = 20

    def __init__(self, provider: Provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "toolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.provider = provider
        self.kind = ""
        self.buttons: dict[str, ToolButton] = {}
        self._groups: list[tuple[QFrame | None, list[ToolButton]]] = []
        self._tokens: dict[str, str] = {}
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(8, 3, 8, 3)
        self._row.setSpacing(1)

    def set_kind(self, kind: str) -> None:
        kind = kind if kind in TOOLBARS else "start"
        if kind == self.kind:
            return
        self.kind = kind
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Gone at once, not when the deferred delete gets round to
                # it: until then the old button would still paint where it was.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.buttons = {}
        self._groups = []
        for number, group in enumerate(TOOLBARS[kind]):
            divider = None
            if number:
                divider = QFrame()
                divider.setProperty("role", "tooldiv")
                divider.setFixedWidth(1)
                self._row.addSpacing(4)
                self._row.addWidget(divider)
                self._row.addSpacing(4)
            buttons = []
            for id_ in group:
                button = self._button(id_)
                self._row.addWidget(button)
                buttons.append(button)
            self._groups.append((divider, buttons))
        self._row.addStretch(1)
        if self._tokens:
            self.apply_tokens(self._tokens)
        self.refresh()

    def _button(self, id_: str) -> ToolButton:
        command = COMMANDS[id_]
        button = ToolButton()
        button.setProperty("role", "tool")
        button.setProperty("glyph", command.glyph)
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(self.ICON, self.ICON))
        button.setFocusPolicy(Qt.NoFocus)
        button.setText(command.tool or command.label)
        button.setToolTip(tool_tip(command))
        button.setCheckable(command.checkable)
        button.clicked.connect(lambda _c=False, i=id_: self.provider.run_command(i))
        spec = TOOL_MENUS.get(id_)
        if spec is not None:
            menu = QMenu(button)
            if isinstance(spec, str):
                menu.aboutToShow.connect(lambda m=menu, n=spec: _fill(self.provider, n, m))
                button.setPopupMode(QToolButton.InstantPopup)
            else:
                build_menu(menu, spec, self.provider)
                button.setPopupMode(QToolButton.MenuButtonPopup)
            button.setMenu(menu)
            button.setProperty("menu", "true")
        self.buttons[id_] = button
        return button

    def refresh(self) -> None:
        for id_, button in self.buttons.items():
            command = COMMANDS[id_]
            state = self.provider.command_state(id_)
            button.setVisible(state.visible)
            button.setEnabled(state.enabled)
            if command.checkable:
                button.setChecked(bool(state.checked))
            text = state.label if state.label is not None else (command.tool or command.label)
            if state.count is not None:
                text += f" {state.count:,}"
            if button.text() != text:
                button.setText(text)
            button.setToolTip(state.tip or tool_tip(command))
        seen = False
        for divider, buttons in self._groups:
            shown = any(not b.isHidden() for b in buttons)
            if divider is not None:
                divider.setVisible(shown and seen)
            seen = seen or shown

    def apply_tokens(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens
        ratio = float(self.devicePixelRatioF() or 1.0)
        for button in self.buttons.values():
            glyph = button.property("glyph")
            if glyph:
                button.setIcon(glyphs.icon(glyph, colour=tokens["txt_0"], muted=tokens["txt_2"],
                                           size=self.ICON, ratio=ratio))
            button.arrow_colour = tokens["txt_2"]
            button.update()
