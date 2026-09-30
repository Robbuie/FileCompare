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

## Status

0.1: text compare. Two files side by side, aligned, with the lines that
differ washed in colour and the characters that differ marked inside them; an
overview of every difference down the right edge; next and previous; rules for
whitespace, case, blank lines and unimportant text. It reads UTF-8, UTF-16
and UTF-32 with or without a byte order mark, and Windows-1252, and says which
it found. It opens from the command line the way Beyond Compare does, and a
second launch opens a tab in the window already open.

Not yet: editing and saving, folder compare, hex, images, three-way merge, the
installer. See `CLAUDE.md` for the order they arrive in.

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
