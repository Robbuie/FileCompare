"""Every command the window offers, in one table, and where each one appears.

The menu bar and the labelled toolbar (1.17) are both built from this module,
so a command has one label, one key and one icon wherever it shows up, and
adding one is a row here plus whatever runs it. Nothing in this file imports
Qt: it is data, and `ui/chrome.py` turns it into widgets.

A command is run by whichever page is current, through `run_command(id)`,
and asked about through `command_state(id)`; the window answers the few that
belong to it (new tab, the look, help). A page that does not know a command
leaves it disabled -- or, for commands that only make sense in some kind of
page (`ONLY`), hidden, so a folder tab's View menu is not full of text-view
items that do nothing.

The keys are written beside menu items as text and are never registered as
shortcuts. The views handle their own keys, for the reason given under Keys
in CLAUDE.md: a window shortcut takes the key from the find box.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    id: str
    #: The menu text. The toolbar uses `tool` when it is set.
    label: str
    key: str = ""
    glyph: str = ""
    #: The word under the toolbar icon; "" when the command is never a button.
    tool: str = ""
    tip: str = ""
    checkable: bool = False


@dataclass
class State:
    """What a page says about a command right now."""

    enabled: bool = True
    checked: bool | None = None
    visible: bool = True
    #: A label to use instead of the command's own, such as a count.
    label: str | None = None
    #: A tooltip to use instead of the command's own.
    tip: str | None = None
    #: A number to show beside the label: "Diffs 6" on the toolbar,
    #: "Differences (6)" in a menu.
    count: int | None = None


DISABLED = State(enabled=False)
HIDDEN = State(enabled=False, visible=False)


def _c(id: str, label: str, key: str = "", glyph: str = "", tool: str = "", tip: str = "",
       checkable: bool = False) -> Command:  # noqa: A002 - "id" reads best here
    return Command(id, label, key, glyph, tool, tip, checkable)


COMMANDS: dict[str, Command] = {c.id: c for c in (
    # Session
    _c("new", "Home", "Ctrl+T", "home", "Home",
       "Saved sessions, recent comparisons, and a new one, in a new tab (Ctrl+T)"),
    _c("add-to-home", "Add to Home...", "", "", "",
       "Keep this comparison's setup on Home, under a name and a folder"),
    _c("open-session", "Open session...", "Ctrl+O", "sessions", "Sessions",
       "Open a comparison saved as a session file"),
    _c("save-session", "Save session...", "Ctrl+Alt+S", "save", "",
       "Save this comparison's paths and settings as a session file"),
    _c("close-tab", "Close tab", "Ctrl+W"),
    _c("next-tab", "Next tab", "Ctrl+Tab"),
    _c("previous-tab", "Previous tab", "Ctrl+Shift+Tab"),
    _c("exit", "Exit", "Alt+F4"),
    # File
    _c("open-left", "Open left...", "", "open", "",
       "Choose another file or folder for the left side; the right side stays"),
    _c("open-right", "Open right...", "", "open", "",
       "Choose another file or folder for the right side; the left side stays"),
    _c("reload", "Compare again from disk", "Ctrl+R", "refresh", "Reload",
       "Read both sides again and compare (Ctrl+R)"),
    _c("save", "Save this side", "Ctrl+S", "save", "Save", "Save the side you are on (Ctrl+S)"),
    _c("save-all", "Save both sides", "Ctrl+Shift+S"),
    _c("save-as", "Save this side as..."),
    _c("report", "Save a report or patch...", "Ctrl+Shift+H", "report", "Report",
       "Save this comparison as an HTML report or a unified patch"),
    _c("copy-paths", "Copy both paths"),
    # Edit
    _c("undo", "Undo", "Ctrl+Z", "undo", "Undo", "Undo on this side (Ctrl+Z)"),
    _c("redo", "Redo", "Ctrl+Y", "redo", "Redo", "Redo on this side (Ctrl+Y)"),
    _c("copy-text", "Copy", "Ctrl+C"),
    _c("select-all", "Select all", "Ctrl+A"),
    _c("copy-left", "Copy to left", "Alt+Left", "copy_left", "Copy left",
       "Copy the selected lines, or this difference, to the left (Alt+Left)"),
    _c("copy-right", "Copy to right", "Alt+Right", "copy_right", "Copy right",
       "Copy the selected lines, or this difference, to the right (Alt+Right)"),
    _c("copy-all-left", "Copy all to left", "Ctrl+Alt+Left"),
    _c("copy-all-right", "Copy all to right", "Ctrl+Alt+Right"),
    _c("copy-from-side", "Copy from this side", "F5"),
    _c("edit", "Edit lines", "F2", "edit", "Edit",
       "Edit the selected lines in place (F2 or Enter)"),
    _c("insert-line", "Insert line below", "Shift+Enter"),
    _c("delete-lines", "Delete lines", "Del"),
    _c("align", "Align with a line opposite", "Ctrl+L"),
    _c("unalign", "Remove alignment", "Ctrl+Shift+L"),
    # Search
    _c("find", "Find...", "Ctrl+F", "search", "Find", "Find in both sides (Ctrl+F)"),
    _c("find-next", "Find next", "F3"),
    _c("find-previous", "Find previous", "Shift+F3"),
    _c("next", "Next difference", "Alt+Down", "down", "Next", "Next difference (Alt+Down)"),
    _c("previous", "Previous difference", "Alt+Up", "up", "Previous",
       "Previous difference (Alt+Up)"),
    _c("first", "First difference", "Home"),
    _c("last", "Last difference", "End"),
    _c("move-partner", "Other end of a moved block", "Ctrl+M"),
    _c("next-conflict", "Next conflict", "Ctrl+Alt+Down", "down", "Next conflict",
       "Next conflict (Ctrl+Alt+Down)"),
    _c("previous-conflict", "Previous conflict", "Ctrl+Alt+Up", "up", "Previous conflict",
       "Previous conflict (Ctrl+Alt+Up)"),
    # View, text
    _c("view-all", "All lines", "", "show_all", "All", "Show every line", True),
    _c("view-diffs", "Differences only", "", "show_diffs", "Diffs",
       "Show only the lines that differ", True),
    _c("view-same", "Matching lines only", "", "show_same", "Same",
       "Show only the lines that match", True),
    _c("view-context", "Differences with context", "", "show_context", "Context",
       "Show the differences with a few lines around each", True),
    _c("layout-sbs", "Side by side", "", "layout_sbs", "Side by side",
       "The two files side by side, matching lines on the same row", True),
    _c("layout-fluid", "Fluid", "", "layout_fluid", "Fluid",
       "The two files side by side without filler rows, joined by bands", True),
    _c("layout-unified", "Unified", "Ctrl+Shift+I", "layout_unified", "Unified",
       "One column: each change with the old lines above the new", True),
    _c("details", "Line details", "", "", "", "The current line of each side, one above the other",
       True),
    _c("sidebar", "Differences list", "Ctrl+Shift+D", "outline", "List",
       "Every difference in a list beside the files", True),
    _c("structure", "Compare by structure", "", "structure", "Structure",
       "Compare by what the file says, not how it is laid out", True),
    _c("compare-as", "Compare as", "", "view", "View", "Show this pair as text, bytes, a table "
       "or pictures"),
    _c("mark-chars", "Mark changed characters", "", "", "", "", True),
    _c("mark-words", "Mark changed words", "", "", "", "", True),
    _c("follow-look", "Follow File Manager's look", "", "", "", "", True),
    _c("syntax-default", "Colour code new tabs by language", "", "", "", "", True),
    # View, folders
    _c("show-all", "All files", "", "show_all", "All", "Every file and folder", True),
    _c("show-diffs", "Differences", "", "show_diffs", "Diffs",
       "Only what differs", True),
    _c("show-left", "Left newer or only on the left", "", "left_newer", "Left newer",
       "What is newer on the left, or only on the left", True),
    _c("show-right", "Right newer or only on the right", "", "right_newer", "Right newer",
       "What is newer on the right, or only on the right", True),
    _c("show-same", "Same", "", "show_same", "Same", "Only what is the same", True),
    _c("expand", "Expand differences", "", "expand", "Expand",
       "Open the folders that hold differences"),
    _c("expand-all", "Expand all"),
    _c("collapse", "Collapse all", "", "collapse", "Collapse", "Close every folder"),
    _c("open-expanded", "Open new comparisons expanded", "", "", "", "", True),
    _c("filter", "Filter names...", "", "filter", "Filter",
       "Which names take part, as patterns separated by ;"),
    # View, folders: the two layouts and the sync list's categories (1.20)
    _c("folder-trees", "Two trees", "", "layout_sbs", "Two trees",
       "Each folder as its own tree, side by side", True),
    _c("folder-list", "Sync list", "", "layout_unified", "Sync list",
       "One list with what would be copied each way, as Synchronize Directories", True),
    _c("cat-lonly", "Only on the left", "", "left_only", "Left only", "", True),
    _c("cat-lnew", "Newer on the left", "", "left_newer", "Left newer", "", True),
    _c("cat-diff", "Different", "", "show_diffs", "Different",
       "Same time and different size or contents: no clock says which is right", True),
    _c("cat-same", "Same", "", "show_same", "Same", "", True),
    _c("cat-rnew", "Newer on the right", "", "right_newer", "Right newer", "", True),
    _c("cat-ronly", "Only on the right", "", "right_only", "Right only", "", True),
    _c("run-list", "Run the sync list...", "", "sync", "Run",
       "Hand the list's copies to File Manager's queue"),
    # Rules
    _c("rules", "Use rules", "Ctrl+I", "rules", "Rules",
       "What counts as a difference. Ctrl+I turns the rules off and on.", True),
    _c("ignore-case", "Ignore case", "", "", "", "", True),
    _c("ignore-blank", "Ignore blank lines", "", "", "", "", True),
    _c("ignore-comments", "Ignore comments", "", "", "", "", True),
    _c("ignore-hour", "Ignore a one-hour shift (clock change)", "", "", "", "", True),
    _c("always-contents", "Always compare contents", "", "", "", "", True),
    _c("look-in-zips", "Look inside .zip files", "", "", "", "", True),
    # Tools, folders
    _c("contents", "Compare contents of undecided files", "", "contents", "Contents",
       "Read the files whose size and time cannot settle it"),
    _c("contents-all", "Compare contents of every pair"),
    _c("contents-selected", "Compare contents of the selected rows"),
    _c("contents-stop", "Stop comparing contents"),
    _c("sync", "Update right from left...", "", "sync", "Sync",
       "Make one side match the other: previewed here, then run by File Manager's queue"),
    _c("sync-update-left", "Update left from right..."),
    _c("sync-mirror-right", "Mirror left to right..."),
    _c("sync-mirror-left", "Mirror right to left..."),
    _c("sync-stop", "Stop waiting for File Manager"),
    # Tools, general
    _c("keep-orig", "Keep a .orig copy on first save", "", "", "", "", True),
    _c("updates-on-launch", "Check for updates on launch", "", "", "", "", True),
    # Window and help
    _c("swap", "Swap sides", "Ctrl+U", "swap", "Swap", "Swap the two sides (Ctrl+U)"),
    _c("keys", "Keys", "F1"),
    _c("check-updates", "Check for updates"),
    _c("about", "About File Compare"),
)}

#: Submenus filled when they open, by the page or the window: (id, title).
#: The page's `fill_menu(id, menu)` is asked first; the window answers the
#: look and recent ones itself.
DYNAMIC = {
    "recent": "Recent",
    "side-left": "Left side",
    "side-right": "Right side",
    "compare-as-menu": "Compare as",
    "syntax": "Syntax colour",
    "whitespace": "Whitespace",
    "patterns": "Unimportant text",
    "theme": "Theme",
    "accent": "Accent",
    "density": "Density",
    "colours": "Difference colours",
}

#: The menu bar: (title, items). An item is a command id, "-" for a
#: separator, or ">name" for a submenu from DYNAMIC.
MENUS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("&Session", ("new", "open-session", "save-session", "add-to-home", ">recent", "-",
                  "next-tab", "previous-tab", "close-tab", "-", "exit")),
    ("&File", ("open-left", "open-right", "reload", "-", "save", "save-all", "save-as", "-",
               ">side-left", ">side-right", "-", "report", "copy-paths")),
    ("&Edit", ("undo", "redo", "-", "copy-text", "select-all", "-",
               "copy-left", "copy-right", "copy-all-left", "copy-all-right", "copy-from-side",
               "-", "edit", "insert-line", "delete-lines", "-", "align", "unalign")),
    ("Searc&h", ("find", "find-next", "find-previous", "-", "next", "previous", "first",
                 "last", "move-partner", "-", "next-conflict", "previous-conflict")),
    ("&View", ("view-all", "view-diffs", "view-same", "view-context", "-",
               "show-all", "show-diffs", "show-left", "show-right", "show-same",
               "cat-lonly", "cat-lnew", "cat-diff", "cat-same", "cat-rnew", "cat-ronly", "-",
               "folder-trees", "folder-list", "-",
               "layout-sbs", "layout-fluid", "layout-unified", "-",
               ">compare-as-menu", ">syntax", "structure", "mark-chars", "mark-words", "-",
               "sidebar", "details", "-", "expand", "expand-all", "collapse",
               "open-expanded", "-",
               ">theme", ">accent", ">density", ">colours", "follow-look")),
    ("&Rules", ("rules", "-", ">whitespace", "ignore-case", "ignore-blank", "ignore-comments",
                ">patterns", "-", "filter", "ignore-hour", "always-contents", "look-in-zips")),
    ("&Tools", ("contents", "contents-all", "contents-selected", "contents-stop", "-",
                "sync", "sync-update-left", "sync-mirror-right", "sync-mirror-left",
                "sync-stop", "run-list", "-", "swap", "-", "syntax-default", "keep-orig",
                "updates-on-launch")),
    ("H&elp", ("keys", "-", "check-updates", "about")),
)

#: Commands that only mean something in some kinds of page. In any other
#: kind they are hidden rather than greyed, menus included.
TEXT_KINDS = frozenset({"text"})
ONLY: dict[str, frozenset[str]] = {
    **{name: TEXT_KINDS for name in (
        "view-all", "view-diffs", "view-same", "view-context", "layout-sbs", "layout-fluid",
        "layout-unified", "details", "sidebar", "mark-chars", "mark-words", "edit",
        "insert-line", "delete-lines", "align", "unalign", "move-partner", "copy-all-left",
        "copy-all-right", "find", "find-next", "find-previous", "first", "last",
        "undo", "redo", "save-all", "save-as", "report", "structure")},
    **{name: frozenset({"folder"}) for name in (
        "show-all", "show-diffs", "show-left", "show-right", "show-same", "expand",
        "expand-all", "collapse", "open-expanded", "filter", "ignore-hour",
        "always-contents", "look-in-zips", "contents", "contents-all", "contents-selected",
        "contents-stop", "sync", "sync-update-left", "sync-mirror-right", "sync-mirror-left",
        "sync-stop", "copy-from-side", "folder-trees", "folder-list", "cat-lonly", "cat-lnew",
        "cat-diff", "cat-same", "cat-rnew", "cat-ronly", "run-list")},
    **{name: frozenset({"merge"}) for name in ("next-conflict", "previous-conflict")},
}

#: The toolbar for each kind of page: groups of command ids, a divider
#: between groups. A button whose command has a menu in TOOL_MENUS gets an
#: arrow beside it.
TOOLBARS: dict[str, tuple[tuple[str, ...], ...]] = {
    "text": (("new", "open-session"),
             ("view-all", "view-diffs", "view-same", "view-context"),
             ("layout-sbs", "layout-fluid", "layout-unified"),
             ("rules", "structure", "compare-as", "sidebar"),
             ("copy-left", "copy-right", "edit"),
             ("previous", "next"),
             ("swap", "reload", "save")),
    "other": (("new", "open-session"),
              ("compare-as",),
              ("previous", "next"),
              ("swap", "reload")),
    "folder": (("new", "open-session"),
               ("show-all", "show-diffs", "show-left", "show-right", "show-same"),
               ("folder-trees", "folder-list"),
               ("contents",),
               ("copy-left", "copy-right", "sync"),
               ("expand", "collapse"),
               ("reload", "swap")),
    "merge": (("new", "open-session"),
              ("previous-conflict", "next-conflict"),
              ("save",)),
    "start": (("new", "open-session"),),
}

#: The menus behind the toolbar's arrows: a tuple of ids, or a DYNAMIC name.
TOOL_MENUS: dict[str, tuple[str, ...] | str] = {
    "rules": ("rules", "-", ">whitespace", "ignore-case", "ignore-blank", "ignore-comments",
              ">patterns", "-", "mark-chars", "mark-words"),
    "compare-as": "compare-as-menu",
    "contents": ("contents", "contents-all", "contents-selected", "contents-stop", "-",
                 "always-contents", "ignore-hour", "look-in-zips"),
    "sync": ("sync", "sync-update-left", "-", "sync-mirror-right", "sync-mirror-left", "-",
             "sync-stop"),
    "expand": ("expand", "expand-all", "collapse", "-", "open-expanded"),
}


def menu_text(command: Command) -> str:
    """The menu item's text with its key after a tab, which a menu draws as
    the shortcut column without the key being registered."""
    return f"{command.label}\t{command.key}" if command.key else command.label


def tool_tip(command: Command) -> str:
    if command.tip:
        return command.tip
    return f"{command.label} ({command.key})" if command.key else command.label


def ids_in_menus() -> set[str]:
    out: set[str] = set()
    for _title, items in MENUS:
        out.update(i for i in items if i != "-" and not i.startswith(">"))
    return out
