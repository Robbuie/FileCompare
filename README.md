# File Compare

A Windows side-by-side compare tool. Python + PySide6. Personal use, offline,
single user. The fourth app in a family with Redline PDF, DWG Viewer and
File Manager, and meant mostly to be opened from File Manager.

## Why

Beyond Compare and WinMerge both work. This one exists to be part of the same
suite as File Manager: the same look, the same keys where the ideas match, and
the same refusal to freeze when a network share stops answering. Past that, it
is where compares that matter at work get built properly -- Logix exports
without the export-date noise, CSV schedules matched on a key column rather
than by row.

## What it does

- **Text**: two files side by side, aligned the way a person expects
  (patience and histogram, not Myers), changed lines washed and the changed
  characters or words marked. Edit either side in place, copy differences
  across, undo, and save in exactly the encoding, byte order mark and line
  endings the file was read with. Find in both sides. Rules for whitespace,
  case, blank lines, comments and "unimportant" patterns, which grey a
  difference out rather than hide it.
- **Folders**: both trees merged into one, with File Manager's verdicts
  (names without case, times within two seconds), filters, name masks, and a
  content compare for the pairs size and time cannot settle. **Sync** one
  way or mirror, or copy and remove picked rows: previewed here with a box
  beside every action, then run by File Manager's queue (File Manager 0.46
  or later).
- **Logix exports (.L5X)** by structure: export dates ignored, tags and
  programs sorted, rung numbers kept out of the way, and every difference
  named by program, routine and rung. XML, JSON and INI by structure too.
- **CSV tables** matched on a key column, compared cell by cell.
- **Hex** for binary files, aligned by offset. **Images** side by side,
  overlay, swipe, blink and difference, with a tolerance.
- **Three-way merge** with git's `mergetool` exit codes.
- PDF revisions and drawings are handed to Redline PDF and DWG Viewer.
- HTML reports and unified patches of a text comparison (Ctrl+Shift+H).

It never freezes on a dead share: every file and folder is read off the
window's thread, with a deadline and a Retry.

F1 in the window lists the keys.

## Running

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app                        # the start page
python -m app left.txt right.txt     # compare two files
```

## Installing

Download `FileCompare-Setup-<version>.exe` from the latest release and run it.
It installs per user (no administrator prompt) into
`%LOCALAPPDATA%\Programs\FileCompare`, puts that folder on your PATH,
registers `FileCompare.exe` under App Paths, and checks for updates a few
seconds after launch (turn that off from the menu). An optional installer
task adds "Select left side to compare" and "Compare to left side" to
Explorer's right-click menu.

## From File Manager

File Manager 0.41 and later start File Compare from its compare commands:
Ctrl+F2 compares the two panes, Alt+F2 the marked files. Beyond Compare and
then WinMerge are used on a machine without File Compare. Pressing the key
again while File Compare is open adds a tab to the window already open.

The other way round, File Compare's folder sync is carried out by File
Manager: File Compare shows the plan, and on "Send to File Manager" writes it
to a small file under `%LOCALAPPDATA%\FileCompare\handoff` and starts
`FileManager.exe --queue <file>`. The jobs run in File Manager's queue with
its pause, cancel and retry, and File Compare reads both folders again when
they finish.

## With git

```
[diff]
    tool = filecompare
[difftool "filecompare"]
    cmd = FileCompare.exe \"$LOCAL\" \"$REMOTE\" --readonly left --wait
[merge]
    tool = filecompare
[mergetool "filecompare"]
    cmd = FileCompare.exe --merge \"$LOCAL\" \"$REMOTE\" \"$BASE\" -o \"$MERGED\"
    trustExitCode = true
```

## Tests

```
pip install pytest
pytest
```
