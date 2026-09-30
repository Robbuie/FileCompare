# Changelog

## 0.8.0 - three-way merge, and git

- **Three-way merge**: `FileCompare.exe --merge <mine> <theirs> <base> -o
  <output>` opens a merge tab. Changes made on one side only, and the same
  change made on both, are taken on their own; what both sides changed
  differently is a conflict.
- **One change at a time**: the current change is shown as it is in mine, the
  base and theirs, with a few lines around it, and settled with Take mine
  (Alt+Left), Take theirs (Alt+Right), mine then theirs, theirs then mine,
  the base, or Edit to write it by hand. Settling a conflict moves on to the
  next. Ctrl+Alt+Down and Up step through conflicts, Alt+Down and Up through
  every change.
- **The output** is shown whole under them, every change washed in its
  colour and conflicts red until settled. An unsettled conflict is written
  with git's markers, and saving with one left asks first. Edit freely turns
  the output into a plain editor for the last touches. It is saved in mine's
  encoding and line endings, beside and then renamed.
- **git**: a merge exits 0 only when the output was saved with nothing
  unresolved, which is what `mergetool.trustExitCode` reads. `--wait` keeps a
  compare in its own window until it is closed, which is what `difftool`
  needs; `--merge` always waits. The README has the `.gitconfig` lines.

## 0.7.0 - table compare

- **Two CSV files open as one grid, rows matched on a key.** A tag list or a
  schedule sorted differently from last week's is not every row changed: each
  record is found wherever it is, and compared cell by cell. A cell that
  differs shows `old -> new` in amber; a record on one side only is red or
  green; the row header says which line of each file it is on.
- **The key is chosen for you**: the first column whose values are present
  and unique on both sides. The Key list picks another, or row position.
- **Columns match by their names**, so a column moved in one file is not a
  difference; a column in one file only says so in its heading.
- Numbers compare by value (1.50 and 1.5 are the same) unless that is turned
  off; case can be ignored; the first row can be data rather than names.
  Differences only hides the records that match.
- Semicolon, tab and bar delimiters are recognised as well as commas, and
  quoted fields may hold the delimiter or line breaks, as Excel writes them.
- The View switch moves a CSV pair between the table and plain text (where it
  can be edited and saved). Excel workbooks are not read yet: that needs
  `openpyxl` in the installer, which has not been agreed.

## 0.6.0 - hex and image compare

- **Hex**: two binary files open side by side as rows of sixteen bytes,
  aligned by offset -- the right alignment for firmware images and fixed
  layouts, where byte 0x1F4 means the same thing in both. Differing bytes are
  marked in hex and in the characters beside them; bytes on one side only (a
  longer file) are red or green. Next and previous step through runs of
  differing rows, the count says the offset, and the map shows them all. Two
  60 MB files that differ in one place compare in a few hundredths of a
  second.
- **Images** (PNG, JPEG, BMP, GIF, TIFF, WebP, ICO, SVG and whatever else
  Qt reads): side by side with the differing pixels marked, overlay with an
  opacity slider, swipe, blink (B), and difference, which dims the left image
  and paints every differing pixel red. A tolerance sets how far apart two
  pixels may be and still count as the same, so a re-saved JPEG does not
  light up. The count says how many pixels differ and the box they are in.
  One zoom and pan for both: Ctrl+wheel or + and -, 0 to fit, 1 for actual
  size, drag to pan. Images of different sizes are compared where they
  overlap, and say so.
- **View** switch over each file pair: text, hex, or image, whichever the
  pair can be. `--mode hex`, `--mode image` and `--mode text` open in one.
- Files up to 64 MB keep their bytes for these views; a larger binary pair
  is still compared by hash.

## 0.5.0 - Logix exports, XML, JSON and INI by structure

- **Two .L5X exports compare by what the program says.** Each is rewritten
  as one line per thing a controls engineer names -- the controller, each
  data type and member, module, tag and its value, program, routine, rung and
  its comment, structured text line, AOI and parameter, task -- with tags,
  programs, routines, modules, types and tasks sorted by name. The export
  date, export options and the created and edited dates and users are left
  out, and the status line says so. Rungs keep their order, and their numbers
  are not part of the line: one inserted rung is one difference, not a
  renumbering of every rung after it.
- **Differences are named by where they are.** The count over the view reads
  "Difference 3 of 4 · Program MainProgram / MainRoutine / Rung 1".
- Module configuration data is shown as a short hash, so a changed
  configuration is one line naming the module rather than forty lines of hex.
- **XML, JSON and INI** can be compared the same way from the new
  **Structure** switch: XML with attribute order and layout ignored, JSON
  with key order ignored, INI with section and key order and comments
  ignored. Those three start with the switch off, since they are usually
  edited; an L5X starts with it on. A side shown by structure is read-only,
  and says to switch Structure off to edit.
- A file that is not the format its name claims is compared as text, and the
  status line says why.
- **PDF and drawing pairs** open a page saying which sibling compares them
  properly -- Redline PDF for PDF revisions, DWG Viewer for DWG, DXF and DWF
  -- with a button that opens both files there, and one to compare here
  anyway.

## 0.4.0 - folder compare

Two folders open as one tree, every file and folder given a verdict, all the
way down.

- **Both trees, merged**: one name column, then size and time on the left, a
  verdict, and time and size on the right. Only on the left is red, only on
  the right green, on both and different amber; the newer time is bold on the
  side that is newer. A folder says how many files under it differ.
- **File Manager's rules**: names match without case, and times within two
  seconds are the same time, so the two applications never disagree about
  the same pair of files.
- **Show**: all, differences, left newer (or only on the left), right newer,
  same. A folder stays in view while anything under it does. Folders holding
  differences open by themselves.
- **Names**: a mask such as `*.L5X;*.ini` includes, `-.git;-*.bak` leaves
  out files or whole folders. The default leaves out `.git`, `__pycache__`,
  `Thumbs.db` and `desktop.ini`.
- **Compare contents** reads the pairs size and time cannot settle -- same
  size, different time -- and says which are really the same ("same content,
  different time", in grey, not counted). Its menu reads every pair, or the
  selected rows, or stops.
- **Enter or double-click** opens a pair in a tab of its own. Alt+Down and
  Alt+Up step through the files that differ. A file only on one side opens
  against nothing, and can be saved over there with Save as.
- The walk runs off the window's thread, lists rather than stats, never
  follows a junction, and says "not answering" only when a side has found
  nothing new for the timeout -- a slow share that is still answering is left
  to finish.
- Copying and deleting from the folder view is not here yet (see
  CLAUDE.md's open decisions); File Manager is where files are moved.

## 0.3.0 - installer, updates, File Manager

From here File Compare is installed rather than run from a checkout, and
File Manager's compare keys open it.

- **Installer** (`FileCompare-Setup-<version>.exe`): per user, no
  administrator prompt, into `%LOCALAPPDATA%\Programs\FileCompare`. It
  registers `FileCompare.exe` under App Paths and puts its folder on your
  PATH, so File Manager, git and a terminal all find it by name.
- **Updates**: a few seconds after launch File Compare looks for a newer
  release on GitHub (the only network call it makes) and offers it. It
  downloads in the background, is checked against its size and SHA-256, and
  installs when you quit. The menu can check now, or stop checking on launch.
- **File Manager** 0.41 starts File Compare from Ctrl+F2 and Alt+F2, with
  Beyond Compare and WinMerge as the fallbacks.
- **Explorer**, optionally: "Select left side to compare" on a file or
  folder, then "Compare to left side" on another. No shell extension; two
  ordinary per-user menu entries.
- The icon: two panes with their rows lined up and one difference drawn
  across both in Drafting blue.
- The menu can turn on keeping a `.orig` copy of a file on its first save.

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
