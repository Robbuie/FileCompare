"""The QSS template and the one function that applies it.

Built from File Manager's `app/theme/sheet.py` (0.38.0): the chrome rules are
the same rules with the same numbers, so a button, a menu, a tab and the title
bar look identical in both applications. What is new is at the bottom, under
"compare", and follows the same habits -- no colour literal anywhere, braces
doubled because the render is a `str.format`, a border only where it separates
two things that behave differently.

The text panes are painted, not styled: QSS cannot put a wash behind one row
or a mark behind three characters. `tokens()` hands the painter the same
values this sheet was rendered from, which is what keeps the two in step.
"""

from __future__ import annotations

from typing import Any

from app.theme import diff, qss, syntax
from app.theme.tokens import DENSITIES, DEFAULTS

TEMPLATE = """
QWidget {{
    background: {backdrop};
    color: {txt_0};
    font-family: {font};
    font-size: {ui_font};
    selection-background-color: {accent};
    selection-color: {bg_0};
}}

QMainWindow {{ background: {backdrop}; }}
QDialog {{ background: {bg_0}; }}
QToolTip {{
    background: {bg_2};
    color: {txt_0};
    border: 1px solid {line};
    border-radius: {radius_sm};
    padding: 4px 7px;
}}

/* ------------------------------------------------------------------ chrome */

QMenu {{
    background: {bg_2};
    border: 1px solid {line};
    border-radius: {radius};
    padding: 5px;
}}
QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: {radius_sm}; }}
QMenu::item:selected {{ background: {accent_soft}; color: {accent_text}; }}
QMenu::item:disabled {{ color: {txt_2}; }}
QMenu::separator {{ height: 1px; background: {line_soft}; margin: 4px 8px; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 5px; }}
QStatusBar {{
    background: {backdrop};
    border: none;
    color: {txt_2};
    min-height: {status_h};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ background: transparent; color: {txt_2}; padding: 0px 6px; }}

/* ----------------------------------------------------------------- buttons */

QToolButton, QPushButton {{
    background: {bg_2};
    border: 1px solid {line};
    border-radius: {radius_sm};
    color: {txt_0};
    padding: 3px 10px;
    min-height: {button_h};
}}
QToolButton:hover, QPushButton:hover {{ background: {bg_3}; }}
QToolButton:pressed, QPushButton:pressed {{ background: {bg_4}; }}
QToolButton:disabled, QPushButton:disabled {{ color: {txt_2}; background: {bg_1}; }}
QToolButton:focus, QPushButton:focus {{ border: 1px solid {accent_line}; }}
QPushButton[role="primary"] {{
    background: {accent_soft};
    border: 1px solid {accent_line};
    color: {accent_text};
}}
QPushButton[role="primary"]:hover {{ background: {accent_wash}; }}
QPushButton[role="primary"]:disabled {{ background: {bg_1}; border: 1px solid {line}; color: {txt_2}; }}

QToolButton[role="nav"] {{
    background: transparent;
    border: none;
    border-radius: {radius};
    color: {txt_1};
    padding: 0px;
    min-width: {button_h};
    max-width: {button_h};
    min-height: {button_h};
    max-height: {button_h};
}}
QToolButton[role="nav"]:hover {{ background: {bg_3}; color: {txt_0}; }}
QToolButton[role="nav"]:pressed {{ background: {bg_4}; }}
QToolButton[role="nav"]:disabled {{ color: {txt_2}; background: transparent; }}
QToolButton[role="nav"][state="on"] {{ background: {accent_soft}; color: {accent_text}; }}
QToolButton[role="nav"]::menu-indicator {{ image: none; width: 0px; }}

QLineEdit {{
    background: {bg_1};
    border: 1px solid {line_soft};
    border-radius: {radius};
    color: {txt_0};
    padding: 3px 8px;
    min-height: {button_h};
    selection-background-color: {accent};
    selection-color: {bg_0};
}}
QLineEdit:focus {{ border: 1px solid {accent_line}; background: {bg_1}; }}

QWidget[role="segments"] {{
    background: {bg_1};
    border: 1px solid {line_soft};
    border-radius: {radius};
}}
QPushButton[role="segment"] {{
    background: transparent;
    border: none;
    border-radius: {radius_sm};
    color: {txt_1};
    padding: 2px 10px;
    min-height: 22px;
}}
QPushButton[role="segment"]:hover {{ background: {bg_3}; color: {txt_0}; }}
QPushButton[role="segment"]:checked {{ background: {accent_soft}; color: {accent_text}; }}
QPushButton[role="segment"]::menu-indicator {{ image: none; width: 0px; }}

/* -------------------------------------------------------------------- tabs */

QWidget[role="tabstrip"] {{ background: {backdrop}; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {txt_2};
    border: none;
    border-top-left-radius: {radius};
    border-top-right-radius: {radius};
    padding: 3px 8px 3px 12px;
    min-height: {tab_h};
    max-width: 320px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ background: {bg_3}; color: {txt_1}; }}
QTabBar::tab:selected {{ background: {bg_2}; color: {txt_0}; }}
QToolButton[role="tabclose"] {{
    background: transparent;
    border: none;
    color: {txt_2};
    padding: 0px;
    margin: 0px 0px 0px 4px;
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
}}
QToolButton[role="tabclose"]:hover {{
    color: {txt_0};
    background: {bg_4};
    border-radius: 3px;
}}

/* --------------------------------------------------------------- title bar */

QWidget[role="titlebar"] {{ background: {backdrop}; }}
QToolButton[role="mark"] {{
    background: {accent};
    border: none;
    border-radius: {radius};
    min-width: 24px; max-width: 24px;
    min-height: 24px; max-height: 24px;
    padding: 0px;
}}
QToolButton[role="mark"]:hover {{ background: {accent_lift}; }}
QToolButton[role="caption"] {{
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
}}
QToolButton[role="caption"]:hover, QToolButton[role="caption"][hot="true"] {{
    background: {bg_3};
}}
QToolButton[role="caption"]:pressed {{ background: {bg_4}; }}
QToolButton[role="caption"][kind="close"]:hover {{ background: {close_hover}; }}
QToolButton[role="caption"][kind="close"]:pressed {{ background: {close_press}; }}
QPushButton[role="gobox"] {{
    background: {bg_2};
    border: 1px solid {line};
    border-radius: 9px;
    min-height: 28px; max-height: 28px;
    padding: 0px;
    text-align: left;
}}
QPushButton[role="gobox"]:hover {{ border: 1px solid {accent_line}; }}
QLabel[role="goicon"] {{ background: transparent; }}
QLabel[role="gotext"] {{ background: transparent; color: {txt_2}; }}
QLabel[role="apptitle"] {{ background: transparent; color: {txt_1}; padding-left: 10px; }}
QLabel[role="keycap"] {{
    background: transparent;
    color: {txt_1};
    font-family: {mono};
    font-size: 10px;
    border: 1px solid {line};
    border-bottom: 2px solid {line};
    border-radius: 4px;
    padding: 0px 5px;
}}

/* ------------------------------------------------- menu bar, toolbar (1.17) */

QMenuBar[role="menubar"] {{ background: transparent; border: none; padding: 0px; }}
QMenuBar[role="menubar"]::item {{
    background: transparent;
    color: {txt_0};
    padding: 5px 9px;
    border-radius: {radius_sm};
}}
QMenuBar[role="menubar"]::item:selected {{ background: {bg_3}; }}
QMenuBar[role="menubar"]::item:pressed {{ background: {accent_soft}; color: {accent_text}; }}
QWidget[role="toolbar"] {{ background: {bg_1}; border-bottom: 1px solid {line_soft}; }}
QToolButton[role="tool"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {radius};
    color: {txt_0};
    padding: 3px 6px 2px 6px;
    min-width: 46px;
    min-height: 0px;
    font-size: {tool_font};
}}
QToolButton[role="tool"][menu="true"] {{ padding-right: 16px; }}
QToolButton[role="tool"]:hover {{ background: {bg_3}; }}
QToolButton[role="tool"]:pressed {{ background: {bg_4}; }}
QToolButton[role="tool"]:checked {{ background: {accent_soft}; border: 1px solid {accent_line}; color: {accent_text}; }}
QToolButton[role="tool"]:disabled {{ color: {txt_2}; background: transparent; }}
QToolButton[role="tool"]::menu-indicator {{ image: none; width: 0px; }}
QToolButton[role="tool"]::menu-button {{ border: none; background: transparent; width: 14px; }}
QToolButton[role="tool"]::menu-arrow {{ image: none; }}
QFrame[role="tooldiv"] {{ background: {line}; border: none; margin: 6px 0px; }}
QLabel[role="position"] {{ color: {txt_1}; padding: 0px 10px; }}

/* ----------------------------------------------------------------- dialogs */

QDialog QLabel {{ background: transparent; color: {txt_0}; }}
QLabel[role="note"] {{ background: transparent; color: {txt_1}; }}
QLabel[role="warn"] {{ background: transparent; color: {warn}; }}
QDialogButtonBox QPushButton {{ min-width: 92px; }}
QCheckBox {{ background: transparent; color: {txt_0}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {line};
    border-radius: 4px;
    background: {bg_2};
}}
QCheckBox::indicator:hover {{ border: 1px solid {accent_line}; }}
QCheckBox::indicator:checked {{ background: {accent}; border: 1px solid {accent}; }}

/* ------------------------------------------------------- splitter, scrollbars */

QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px 2px 2px 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 0px 2px 2px 2px;
}}
QScrollBar::handle {{
    background: {bg_4};
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:hover {{ background: {accent_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ----------------------------------------------------------------- compare */

/* A comparison is a card on the backdrop, like a File Manager pane: the
   radius is the container's, larger than a control's, so the buttons inside
   do not read as the same flat object. */
QFrame[role="card"] {{
    background: {bg_2};
    border: 1px solid {line_soft};
    border-radius: {radius_lg};
}}
QFrame[role="card"] QLabel {{ background: transparent; }}
QWidget[role="toolrow"] {{ background: transparent; }}
QLabel[role="count"] {{ color: {txt_1}; padding: 0px 8px; }}
QLabel[role="count"][state="same"] {{ color: {good}; }}

/* The strip over each side: the name, where it is, and what was detected
   about it. It separates the file from the chrome above, so it has a rule. */
QWidget[role="sidehead"] {{
    background: {bg_1};
    border-bottom: 1px solid {line_soft};
}}
QWidget[role="sidehead"][active="true"] {{ border-bottom: 1px solid {accent_line}; }}
QLabel[role="sidename"] {{ font-weight: 600; color: {txt_0}; }}
QLabel[role="sidewhere"] {{ color: {txt_2}; }}
QToolButton[role="sidefacts"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {txt_2};
    font-family: {mono};
    font-size: 11px;
    padding: 1px 6px;
    min-height: 18px;
}}
QToolButton[role="sidefacts"]:hover {{ background: {bg_3}; border: 1px solid {line}; color: {txt_1}; }}
QLabel[role="sidestate"] {{ color: {txt_1}; }}
QLabel[role="sidestate"][state="bad"] {{ color: {warn}; }}
QLabel[role="sidestate"][state="dirty"] {{ color: {accent_text}; font-weight: 600; }}

/* Folder compare and table compare: item views inside the card, on the
   card's own surface, with File Manager's quiet column headers. */
QWidget[role="folderbar"] {{ background: {bg_1}; border-bottom: 1px solid {line_soft}; }}
QTreeView[role="foldertree"], QTableView[role="grid"] {{
    background: {bg_2};
    alternate-background-color: {bg_2};
    border: none;
    outline: none;
    gridline-color: {line_soft};
    selection-background-color: {accent_row};
    selection-color: {txt_0};
}}
QTreeView[role="foldertree"]::item {{ padding: 1px 4px; border: none; }}
QTreeView[role="foldertree"]::item:selected, QTableView[role="grid"]::item:selected {{
    background: {accent_row};
    color: {txt_0};
}}
QHeaderView {{ background: {bg_1}; border: none; }}
QHeaderView::section {{
    background: {bg_1};
    color: {txt_2};
    border: none;
    border-bottom: 1px solid {line_soft};
    border-right: 1px solid {line_soft};
    padding: 3px 6px;
    font-size: {head_font};
}}
QTableCornerButton::section {{ background: {bg_1}; border: none; }}

/* The merge tab's passages and output: text surfaces inside the card. */
QPlainTextEdit[role="passage"] {{
    font-family: {mono};
    background: {bg_2};
    color: {txt_0};
    border: 1px solid {line_soft};
    border-radius: {radius_sm};
}}

/* Find: a strip over the card, only while it is open. */
QWidget[role="findbar"] {{ background: transparent; }}

/* Text the user reads by column: a stylesheet family beats `setFont`, so a
   widget that wants the mono face has to be given it here (1.11.1). */
QTableView[role="grid"] {{ font-family: {mono}; }}
QLineEdit[role="findfield"] {{ font-family: {mono}; padding: 3px 8px; }}

/* Editing lines in place: the same surface as the pane, outlined in the
   accent so it is plainly not part of the file until it is committed. */
QPlainTextEdit[role="lineeditor"] {{
    font-family: {mono};
    background: {bg_2};
    color: {txt_0};
    border: 1px solid {accent_line};
    border-radius: {radius_sm};
    padding: 0px;
}}
QToolButton[role="retry"] {{
    background: transparent;
    border: 1px solid {line};
    border-radius: {radius_sm};
    color: {txt_0};
    padding: 1px 10px;
    min-height: 20px;
}}
QToolButton[role="retry"]:hover {{ background: {bg_3}; }}

/* The start page: two sides to fill in, and the button that compares them. */
QFrame[role="start"] {{
    background: {bg_2};
    border: 1px solid {line_soft};
    border-radius: {radius_lg};
}}
QFrame[role="start"] QLabel {{ background: transparent; }}
QLabel[role="starttitle"] {{ font-size: 20px; font-weight: 600; }}
QLabel[role="sidelabel"] {{ color: {txt_2}; font-size: {head_font}; font-weight: 600; letter-spacing: 1px; }}
QLineEdit[role="pathfield"] {{ font-family: {mono}; padding: 4px 10px; }}
QLabel[role="hint"] {{ color: {txt_2}; }}
QPushButton[role="recent"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {txt_1};
    text-align: left;
    padding: 3px 8px;
    font-family: {mono};
}}
QPushButton[role="recent"]:hover {{ background: {bg_3}; color: {txt_0}; }}
"""


def metrics(density: str | None = None) -> dict[str, int]:
    """Density numbers a widget has to apply itself, as ints."""
    values = DENSITIES.get(density or DEFAULTS["density"], DENSITIES[DEFAULTS["density"]])
    return {key: int(value) for key, value in values.items()}


def tokens(
    theme: str | None = None,
    accent: str | None = None,
    density: str | None = None,
    colours: str = "classic",
) -> dict[str, str]:
    """Every token for one combination, the difference colours included.

    The painters use this rather than reading the theme dictionaries, so there
    is one place that knows how a tint is derived.
    """
    values = qss.build(theme, accent, density)
    # 1.17: the word under a toolbar icon, a step under the interface size.
    ui = float(str(values.get("ui_font", "13px")).rstrip("px") or 13)
    values["tool_font"] = f"{max(9.0, ui - 1.5):g}px"
    values.update(diff.build(values, colours))
    values.update(syntax.build(values))
    return values


def render(values: dict[str, str]) -> str:
    return qss.render(TEMPLATE, values)


def apply(
    app: Any,
    *,
    theme: str | None = None,
    accent: str | None = None,
    density: str | None = None,
    colours: str = "classic",
) -> dict[str, str]:
    """Render the sheet for one combination and put it on the application.

    Returns the tokens, because the painted panes need the same values and
    an unknown name falls back rather than raising -- so what was asked for
    and what was applied can differ.
    """
    from PySide6.QtGui import QColor, QFont, QPalette

    values = tokens(theme, accent, density, colours)
    # Qt's stylesheet keeps only the first family of a `font-family` list, so
    # `{mono}` is in effect "Cascadia Mono" alone, and a machine without it
    # (Windows 10 before Terminal) got a proportional face in every mono
    # field. A substitution makes the rest of the list real (1.11.1).
    QFont.insertSubstitutions("Cascadia Mono", ["Consolas", "DejaVu Sans Mono", "Liberation Mono"])
    app.setStyleSheet(render(values))

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(values["bg_0"]))
    palette.setColor(QPalette.WindowText, QColor(values["txt_0"]))
    palette.setColor(QPalette.Base, QColor(values["bg_2"]))
    palette.setColor(QPalette.AlternateBase, QColor(values["bg_2"]))
    palette.setColor(QPalette.Text, QColor(values["txt_0"]))
    palette.setColor(QPalette.Button, QColor(values["bg_2"]))
    palette.setColor(QPalette.ButtonText, QColor(values["txt_0"]))
    palette.setColor(QPalette.Highlight, QColor(values["accent_row"]))
    palette.setColor(QPalette.HighlightedText, QColor(values["txt_0"]))
    palette.setColor(QPalette.ToolTipBase, QColor(values["bg_2"]))
    palette.setColor(QPalette.ToolTipText, QColor(values["txt_0"]))
    palette.setColor(QPalette.PlaceholderText, QColor(values["txt_2"]))
    app.setPalette(palette)
    return values
