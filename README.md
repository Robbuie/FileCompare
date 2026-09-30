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

## From File Manager

File Manager's compare commands (Ctrl+F2 for the two panes, Alt+F2 for the
marked files) run whichever compare tool is installed and pass it two paths.
Until this has an installer that registers it, point those rows at it by hand
in File Manager's command editor: program `pythonw`, arguments
`-m app %C`, working folder this repository.

## With git

```
[diff]
    tool = filecompare
[difftool "filecompare"]
    cmd = pythonw -m app \"$LOCAL\" \"$REMOTE\"
```

(Run from this folder until the installer puts `FileCompare.exe` on the path.)

## Tests

```
pip install pytest
pytest
```
