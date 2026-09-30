# Changelog

## 0.2.0 - editing and saving

Both sides can be changed and saved, without a byte changing that nobody
asked to change.

- **Copy across**: Alt+Right and Alt+Left copy the current difference to the
  other side, and the arrows at the top of each difference in the middle strip
  do the same with the mouse. Ctrl+Alt+Right and Left copy everything.
- **Edit in place**: select lines (click, Shift+click, drag, Shift+arrows)
  and press Enter, F2 or double-click. The lines open in an editor over the
  pane; Ctrl+Enter or clicking away keeps them, Escape drops them. Delete
  removes the selected lines. The diff runs again after every edit.
- **Undo and redo** per side (Ctrl+Z, Ctrl+Y), as many steps as there were
  edits. A side back at its saved state is not "Modified" any more.
- **Saving** (Ctrl+S this side, Ctrl+Shift+S both) writes the encoding, byte
  order mark and line endings the file was read with, line by line, so a
  mixed file stays exactly as mixed as it was. The new text goes to a file
  beside the old one and takes its name only once it is all on disk.
- **A file changed by somebody else is not overwritten.** The size and time
  are checked just before the rename; if they moved, it asks: overwrite, save
  as, or leave it. A poll every few seconds also marks a side "Changed on
  disk" with a Reload button while the tab is open.
- **The side's menu** (click the encoding over it): save, save as, the
  encoding and byte order mark to save with, converting line endings (as an
  undoable edit), copy path, reload. Text the chosen encoding cannot hold is
  refused with the line it is on, never saved as question marks.
- **Find** (Ctrl+F): both sides at once, marked while the bar is open, with
  match case and regular expressions; F3 and Shift+F3 step through.
- **Copy text** (Ctrl+C) copies the selected lines of the focused side.
- A read-only side, a side opened with `--readonly`, and a file with bytes
  that did not decode are not edited, and say why when asked to be.
- Closing a tab or the window with unsaved changes asks: save, discard or
  cancel. Reloading over edits asks too.
- `save.backup` in the settings keeps `name.ext.orig` beside a file the first
  time it is saved.

## 0.1.0 - text compare

The first version: two text files side by side, in the family's look.

- **The window** is File Manager's shape: its title bar (Windows snapping,
  shadow and snap layouts kept), tab pills, and status line. Theme, accent and
  density are the family's three axes, and by default are taken from File
  Manager's settings so the two windows match; picking one from the menu
  switches to this application's own.
- **The start page** takes a path for each side, by typing, pasting, Browse
  or dropping files, and turns into the comparison in the same tab.
- **The command line** takes two paths, `--left-title`, `--right-title`,
  `--readonly` and `--mode`, in the shape File Manager's `%C` already passes to
  Beyond Compare and WinMerge. A second launch hands its paths to the window
  already open, as a new tab.
- **The engine** aligns on lines that are unique to both sides first and
  splits what is left by its rarest shared line (patience, then histogram), so
  a function inserted above another does not steal its closing brace. Inside
  a changed block, lines are put opposite the line they most resemble. 200,000
  lines with a few hundred scattered edits compare in under half a second.
- **Rules**: whitespace (trailing, changes, all), case, blank lines, and
  regular expressions for unimportant text. A difference a rule looks past is
  still shown, in grey, and is not counted. Ctrl+I turns the rules off and on.
- **The view** paints only the rows on screen. Changed lines are washed amber,
  lines on one side only red or green, with the characters or words that
  differ marked inside; the difference colours never follow the accent. The
  map down the right shows every difference and where the view is, and moves
  the view when clicked.
- **Reading** detects a byte order mark, UTF-16 without one, UTF-8 and
  Windows-1252, and the line endings, and shows all of it over each side. Two
  files with the same text and different bytes say which part differs.
- **Nothing on the window's thread touches a file.** Each side loads on its
  own with a deadline; a side on a share that stops answering says so and
  offers Retry, and the other side stays put.
- Binary files are compared by content hash and said to match or not. Two
  folders are recognised and said to be a later version's job.
