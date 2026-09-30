# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**File Compare** -- a Windows side-by-side compare and merge tool, Python +
PySide6, built to replace Beyond Compare and WinMerge for one person's daily
use. Personal use, offline, single user. Repo: `Robbuie/FileCompare` (public,
and it stays public -- see Packaging). Local path
`C:\Users\rjokr\Projects\File Compare`.

It is the fourth app in a family: **Redline PDF** (Electron, PDF markup),
**DWG Viewer** (Python/PyQt6, drawing viewer) and **File Manager**
(Python/PySide6, dual-pane file manager). They are meant to read as one suite,
and this one is meant to be *used from* File Manager more often than on its
own. "Look and feel" and "Working with File Manager" below are specs, not
suggestions.

The question it answers is "what changed inside these", which File Manager
deliberately does not answer. File Manager's pane compare (`core/compare.py`
there) reads no files and decides on size and time; this application opens
the files and says exactly what differs, and lets the differences be merged.
The two are meant to be used together: File Manager marks which files differ,
Ctrl+F2 opens those here.

## Working agreement

- **No emojis.** Not in the UI, not in code, not in comments, not in commit
  messages, not in `CHANGELOG.md`, not in chat responses about this project.
  Status is conveyed by text and colour. Icons are SVG, never emoji glyphs.
- **No decorative output.** No banner comments made of box-drawing characters,
  no ASCII art, no "Done!" flourishes. Comments explain *why* something exists,
  in prose.
- **Claude cannot test the window.** No clicking, no scrolling, no network
  share to compare against. The user is the test loop for behaviour. Two
  things Claude *can* check, and should before calling anything finished:
  - the **diff engine**, which is pure Python with no Qt and is covered by
    `pytest` against the fixture pairs in `tests/data/`;
  - the **look**, through `tools/preview.py`, which renders the real window
    offscreen to a PNG (File Manager's tool, ported). A theme that did not
    apply or a gutter that collapsed shows up there. It says nothing about
    whether the view behaves.
  So: keep changes small enough to verify in one sitting, say plainly what
  needs to be tried, and never report a UI change as working. "This should now
  align the moved block -- worth checking against a real pair" is honest;
  "fixed" is not.
- **Claude has direct read/write access to this folder in Cowork sessions.**
  Edit files in place. Pushing is the user's job -- the session has no GitHub
  credentials and no `gh`.
- **Ask before adding a dependency.** Every addition ships inside the
  installer. The candidates already weighed are listed under Stack.
- Every user-visible change gets a `CHANGELOG.md` entry and a version bump.
- **A change to File Manager is a change in the other repo.** When a feature
  needs something on the File Manager side (a command row, a handoff), make it
  there as its own commit with its own changelog entry, following that repo's
  `CLAUDE.md`. Never reach into it from here.

## Commands

```
python -m venv .venv                    # once
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest                      # tests only, not shipped
pip install -r packaging/requirements-build.txt   # building an installer

pytest                                  # engine, reader, rules, CLI, session, window
python -m app                           # empty window, the start page
python -m app left.txt right.txt        # a text compare
python -m app C:\A D:\B                 # two folders: says folder compare is not here yet

python -m app.harness diff left.txt right.txt              # the engine alone, as text
python -m app.harness diff a.log b.log --time              # counts and timing only
python -m app.harness diff a.ini b.ini --whitespace all --case --blank --pattern "ExportDate=\"[^\"]*\""
python -m app.harness load file.txt                        # what the reader decided about a file

python tools/preview.py --out preview.png                  # the settings.ini fixture pair
python tools/preview.py --pair a.txt b.txt --step 3 --out p.png   # three presses of next
python tools/preview.py --all-themes --out-dir previews
python tools/preview.py --start --out start.png            # the start page

python packaging/build.py               # dist/: the folder, the setup exe, latest.json (step 5)
python packaging/build.py --skip-installer
```

`tests/data/text/` holds the fixture pairs. `settings.left.ini` and
`settings.right.ini` are the default preview pair because they exercise every
kind at once: edited lines, a whitespace-only change, a line only on each side.

`pytest` bare and `python -m pytest` have to behave the same, which they do
only with `pythonpath = ["."]` in `pyproject.toml` -- File Manager learned
this one already, and the release workflow runs the bare form.

## The rules everything else follows from

**1. The UI thread never touches the filesystem.** Same rule as File Manager,
same reason: the files being compared are often on a share, and an SMB call to
a dead server blocks for 30-45 seconds. Opening a file, reading it, walking a
folder, checking whether a file changed on disk, saving -- all of it happens
off the UI thread with a timeout and a cancel. If a diff puts `os.`,
`pathlib`, `shutil` or `open(` anywhere under `app/ui/`, it is wrong
regardless of how harmless the call looks.

**2. The diff engine is pure.** `app/core/diff/` takes sequences and returns
data. No Qt, no files, no threads. Everything the tests can prove is proved
there, which is the only part of this application Claude can verify alone.

**3. A file is never changed except by a save somebody asked for, and a save
never loses a byte it did not mean to change.** See "Text, bytes and saving".

## Architecture

Three layers, mirroring File Manager, and the boundary between them is the
point.

**`app/ui/`** -- the window, tabs, the compare views, dialogs. Presentation and
input. Never touches the filesystem.

**`app/core/`** -- the compare session model, the diff engine, rules, config.
Holds what the UI renders.

- `core/diff/lines.py` -- which lines match: patience anchors on unique
  lines, histogram inside what is left, `SequenceMatcher` only as the
  fallback for small unsplittable regions.
- `core/diff/intraline.py` -- character and word differences inside a changed
  line pair, computed lazily for lines on screen.
- `core/diff/align.py` -- turns opcodes into the **row model** (below).
- `core/diff/merge3.py` -- three-way merge and conflict detection.
- `core/rules.py` -- what counts as a difference: whitespace, case, line
  endings, regex "unimportant" text, per-format rules.
- `core/formats/` -- format-aware comparers that normalise before the line
  diff (L5X, XML, JSON, INI). Each returns canonical lines, a crumb per line
  (where it is in the file's structure) and what it ignored. The session runs
  them in the compare job; a side shown through one is read-only.
- `core/siblings.py` -- which pairs Redline PDF and DWG Viewer compare better,
  and where those install; `io/launch.py` starts them.
- `core/session.py` -- one open comparison: its sides, its deadlines, its
  result, its edits and saves.
- `core/folders.py` -- folder compare's merged tree and its verdicts, masks
  and show filters. Pure, like the engine.
- `core/folderdiff.py` -- one folder comparison: two walks with a stall
  deadline, the tree built off the UI thread, a content compare.
- `core/document.py` -- one side's text while it is edited: lines, their
  endings, and undo/redo as splices. Pure; the tests prove it alone.
- `core/loader.py` -- runs work off the UI thread and hands the answer back
  on it, always as a queued event (see "Things that will bite you").
- `core/instance.py` -- the single-instance socket.
- `core/appearance.py` -- ours or File Manager's theme, accent and density.

**`app/io/`** -- every real filesystem call, off the UI thread.

- `io/load.py` -- read a file, detect encoding, BOM and line endings, return
  the decoded lines, the endings, a hash of the bytes and what was detected.
- `io/kind.py` -- file, folder or missing, for a path from the command line.
- `io/longpath.py` -- the `\\?\` rule, ported from File Manager's `paths.py`.
- `io/save.py` -- encode with the side's encoding, mark and per-line
  endings, write beside, check the file did not move, rename.
- `io/walk.py` -- a tree by `os.scandir`, junctions listed and not
  followed, cancellable; and "are these two files the same bytes".
- Later, if dead shares make it worth it: `io/worker.py` / `io/pool.py`
  ported from File Manager, so a walk stuck in SMB can be killed rather than
  abandoned.

### The row model

Everything in the text view hangs off one structure. A comparison is a list
of **rows**; each row is `(left_line | None, right_line | None, kind)`, where
`kind` is equal, changed, added, removed, or ignored. A line that exists on
only one side gets a filler row opposite it.

What follows from that:

- **Scrolling is synchronised for free.** Both panes scroll in row space, not
  line space, so they can never drift apart.
- **The overview map, the gutter connectors, next/previous difference and the
  status counts** are all reads of the same list.
- **Edits re-diff a window, not the file.** After an edit, only the rows
  between the nearest unchanged anchors on either side are recomputed.
- **The view is virtualised.** A custom `QAbstractScrollArea` paints only the
  rows on screen. `QPlainTextEdit` per side cannot keep two documents aligned
  with filler lines and does not survive a 200 MB log, so it is not used for
  the compare view.

### Threads now, worker processes later

Each side loads independently, off the UI thread, under a deadline
(`load.timeout`). A side that misses it shows "not answering" with a Retry,
the other side stays usable, and the late answer is dropped by request id.

In 0.1 the loads run on a small thread pool (`core/loader.py`), not in File
Manager's per-volume worker processes. The window behaves the same either way;
the difference is that a thread stuck in an SMB call cannot be killed, so it
stays stuck until Windows gives up. With a handful of threads and single-file
reads that is a bounded cost. Folder compare walks whole trees on shares, and
that is where File Manager's pool gets ported.

A ported file says at the top which File Manager version it was taken from, so
a fix made there can be found and carried over. Ported so far:
`theme/tokens.py` and `theme/qss.py` (verbatim), `core/scrollmap.py`
(verbatim), `ui/glyphs.py`, `ui/titlebar.py`, `ui/winframe.py`,
`io/longpath.py`, `tests/conftest.py`.

## Compare modes

One window, tabbed; each tab is one comparison of one kind. The kind is chosen
by what was opened and can be switched from the tab's header.

**Text** -- the core, and most of the work.
- Side-by-side and a one-column inline view of the same row model.
- Intraline highlights at character or word level, only for rows on screen.
- Gutter with connector bands between the panes for each difference block.
- Overview map beside the scrollbar (File Manager's `scrollmap` idea): every
  difference as a tick, click to jump.
- Editable on both sides, with undo per side. Copy a block left or right,
  copy all, copy a single line.
- Rules: ignore whitespace (leading, trailing, all), case, line endings, blank
  lines, and regex "unimportant" text shown in grey rather than hidden.
- Moved-block detection shown as its own kind rather than as a delete plus an
  add.
- Syntax colouring by extension, if a dependency is approved for it.

**Folder** -- recursive, both trees side by side.
- Compare by size and time (instant), then by content (queued, cancellable,
  per file). Size-and-time uses File Manager's two-second tolerance and
  case-insensitive names for the same reasons stated in its `core/compare.py`.
- Filters: name masks, show only differences, only one side, hide equal
  folders.
- Enter on a pair opens it in a new tab in the right mode.
- Folder actions (copy across, delete) are **not** in the first versions. See
  Open decisions.

**Hex / binary** -- side by side, aligned by offset, differing bytes marked.
The fallback for anything that will not decode, and the right answer for
firmware images and binary exports.

**Image** -- side by side, overlay, swipe slider, blink, and a difference
mask with a tolerance. Same modes and same chip control as Redline PDF's
compare panel, so the two read as the same tool.

**Three-way merge** -- mine, base, theirs, with the output pane under them.
Conflicts are their own kind with their own navigation. This is also what
makes the app usable as git's `mergetool`.

**Table** -- CSV and, if approved, Excel: rows matched on a key column rather
than by position, so an inserted row is one difference and not every row
after it.

**Format-aware** (normalise, then text compare):
- **L5X (Logix exports)** -- ignore `ExportDate` and other attributes that
  change on every export, compare rung by rung within a routine, and name
  differences by program, routine, rung and tag rather than by line number.
  File Manager's `app/io/logix.py` already reads these; its lessons apply.
- **XML** -- attribute order and insignificant whitespace ignored.
- **JSON / INI** -- key order ignored.

**Handed to a sibling rather than rebuilt here:**
- PDF revisions go to **Redline PDF**, whose compare engine already handles
  alignment, scale and scanner noise far better than a text extract would.
- DWG/DXF go to **DWG Viewer**.
A pair of those opens a tab that says so and offers to launch the sibling on
the same two files.

## Text, bytes and saving

This is where compare tools quietly damage files. The rules:

- **Detect, remember, and write back the same way.** Encoding, BOM, and line
  ending style are detected per side on load and recorded on the session. A
  save writes that encoding, that BOM, and that line ending, unless somebody
  changed one on purpose in the status bar.
- **A file that does not decode cleanly is not editable as text.** It opens
  read-only as text with the undecodable bytes shown, or in hex. Editing a
  decode that contains U+FFFD and saving it would replace real bytes with
  question marks, silently, in a file somebody trusted this tool with.
- **Mixed line endings are shown, not normalised.** A file with both CRLF and
  LF says so in the status bar and keeps both unless told otherwise.
- **Every save is write-beside, then rename.** Nothing half-written ever
  carries the real name. Same invariant as File Manager's copy engine.
- **Before saving, check the file on disk is still the one that was loaded**
  (size and mtime). If it changed, ask: reload, overwrite, or save elsewhere.
- **Read-only files and read-only sessions are respected.** `--readonly` from
  the command line makes a side read-only for the life of the tab.
- **A backup is a setting**, off by default: `name.ext.orig` beside the file on
  first save of a session.

## Performance

- **Lines are hashed once**, and the diff runs on integers, not strings.
- **Intraline and syntax work is lazy**, for rows on screen only, and cached.
- **Large inputs degrade on purpose rather than hang.** Past a line count that
  is a setting, the engine trims the common prefix and suffix first (which is
  most of a log), and if what is left is still too big it says so and offers
  hex or a coarser compare. A progress bar that sits at 90% for four minutes is
  the failure to avoid.
- **The diff runs off the UI thread and can be cancelled.** A second request
  for the same tab cancels the first.
- Folder walks follow File Manager's listing rules: `os.scandir`, never a
  per-file `stat`, streamed in batches, both sides walked in parallel.

## Look and feel

The family shares a design system. Redline PDF's `src/css/app.css` is the
source of truth; File Manager's `app/theme/` is the Qt port of it and is what
this app copies. **Port `app/theme/` from File Manager verbatim** -- tokens,
the QSS template mechanism, the accent derivation -- and add to it only what
compare needs. A grey that changes in Redline PDF changes in all four.

- **Three independent axes: theme, accent, density.** Themes: dark, light,
  warm paper, blueprint, high contrast. Accents as channel triples: redline,
  amber, field green, cyan, drafting blue, violet.
- **Default: dark theme, drafting blue accent, normal density**, matching File
  Manager and DWG Viewer.
- **Optionally follow File Manager's appearance.** A setting (on by default)
  reads File Manager's theme, accent and density from its settings file at
  startup, read-only, so changing the look in one changes both. If the file is
  missing or unreadable, this app's own settings apply. Never write to it.
- **The window chrome is File Manager's**: the custom title bar from
  `ui/winframe.py` (snap layouts, resize edges, shadow), the tab strip, the
  status bar, the command palette on Ctrl+K, and Options on Ctrl+,.
- **No literal colour anywhere outside `app/theme/`.** A test fails the build
  on one, as `verify.js` does in Redline PDF.

### Difference colours are semantic, not accent

File Manager's `CLAUDE.md` already reserved this: "a diff colour in a future
compare view does **not** follow the accent." The difference colours are
fixed, named tokens, defined per theme only so that alpha and lightness suit a
dark or light background:

```
diff_add        green    lines only on the right       (from `good`)
diff_del        red      lines only on the left        (fixed; not the redline accent)
diff_chg        amber    changed line pair             (from `warn`)
diff_moved      violet   moved block
diff_conflict   red, stronger                          three-way only
diff_ignored    txt_2    differences the rules say do not matter
```

Each has a line wash (low alpha, whole row) and an intraline mark (higher
alpha, the characters themselves). The accent is for selection, focus, the
current difference outline, and chrome -- never for "this changed". An accent
set to redline must not make every change look like a deletion.

High contrast restates all of them for contrast, and adds a gutter glyph per
kind so a difference never relies on colour alone.

## Keys

Chosen so File Manager's hands still work here. Where File Manager has a key
for the same idea, it is the same key.

```
Alt+Down / Alt+Up      next, previous difference
Ctrl+Alt+Down / Up     next, previous conflict (three-way)
Alt+Right / Alt+Left   copy this block to the right, to the left
Ctrl+Alt+Right / Left  copy all differences across
Home / End             first, last difference (from the overview map)
Tab                    the other side                    (File Manager's Tab)
Ctrl+U                 swap sides                        (File Manager's swap panes)
Ctrl+R                 compare again from disk           (File Manager's refresh)
F5                     copy to the other side, folder mode  (File Manager's copy)
Enter                  open the pair under the cursor, folder mode
Ctrl+S / Ctrl+Shift+S  save the focused side, save all
Ctrl+Z / Ctrl+Y        undo, redo on the focused side
Ctrl+F / Ctrl+G        find, find next                   (File Manager's Ctrl+G)
Ctrl+I                 toggle the ignore rules on and off
Ctrl+Shift+I           the inline, one-column view
Ctrl+T / Ctrl+W        new tab, close tab
Ctrl+K                 command palette
Ctrl+,                 Options
F1 or ?                the key sheet
```

Keys are handled by the view, not as window shortcuts, for the reason File
Manager gives: a window shortcut takes the key away from the find box.

## Working with File Manager

**The command line is the contract**, and it is Beyond Compare's and
WinMerge's shape so that File Manager's command table needs no new code:

```
FileCompare.exe <left> <right>
FileCompare.exe <left> <right> --left-title "S:\Jobs\old" --right-title "working copy"
FileCompare.exe <left> <right> --readonly left|right|both
FileCompare.exe <left> <right> --mode text|folder|hex|image|table
FileCompare.exe --merge <mine> <theirs> <base> -o <output>
FileCompare.exe --clip                          # clipboard against a new empty side
```

Files or folders alike; which it is decides the mode, and that decision is
made in a worker, not in the argument parser.

- **Single instance.** A second launch hands its arguments to the running
  window over a named local socket (`QLocalServer`) and exits; the pair opens
  as a new tab. Pressing Ctrl+F2 five times in File Manager gives one window
  with five tabs.
- **Found by name.** The installer registers `FileCompare.exe` under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths` *and* puts
  the install folder on the user's PATH. App Paths alone is not enough:
  File Manager's `worker.locate` uses `shutil.which`, which reads PATH and
  never App Paths, and so does git. (A `KNOWN_PROGRAMS` entry in File
  Manager's `io/worker.py` would also do; it was written once and lost to a
  concurrent edit, and PATH makes it unnecessary.)
- **File Manager's side of it** (a commit in that repo): the `compare` and
  `compare-files` rows gain `FileCompare.exe` as their program, with
  `BCompare.exe` and `WinMergeU.exe` kept as alternatives, so a machine without
  this app still compares.
- **git.** `README.md` carries the `difftool` and `mergetool` lines for
  `.gitconfig`; `--merge` exits non-zero if the output was not saved, which is
  what git reads as "merge not resolved".
- **Explorer**, later: "Select left side" and "Compare to <left>" as ordinary
  per-user registry verbs. No shell extension DLL.

## Conventions

- Python 3.11+, 4-space indent, type hints on anything crossing a module
  boundary. A short module docstring at the top of each file explaining *why*
  it exists.
- **Anything crossing a process boundary is a plain picklable dataclass or
  dict.** No `Path`, no Qt types, no open handles.
- **Every worker call returns an envelope**, success or failure, and a timeout
  is a normal result rather than an exception path.
- **Replies carry a request id** so a tab that was closed or re-compared can
  drop a late one.
- New settings go through the config module with a default; a setting
  somebody would change also gets a row in `core/options.py`, as in File
  Manager.
- Every rule in `core/rules.py` says in the UI what it ignored and how many
  times. A compare that reports "identical" while hiding forty differences is
  worse than one that reports them.

## Things that will bite you

- **`difflib.SequenceMatcher` has `autojunk` on by default.** On any sequence
  of 200 or more items it treats an item appearing in more than 1% of
  positions as junk -- which in real files means blank lines, `}` and `end`
  -- and the alignment comes out wrong in ways that look like a bug in the
  view. The engine here does not use `SequenceMatcher` for lines. If it is
  used anywhere (intraline is the likely place), `autojunk=False`.
- **Myers alone aligns code badly** around repeated lines: it will happily
  pair one closing brace with a different one. Patience or histogram diff,
  anchored on lines that are unique on both sides, is what makes moved and
  edited functions line up the way a person expects.
- **A line diff of an L5X is noise.** Logix writes the export date, and
  sometimes reorders elements, on every export. Compare it through the format
  comparer or not at all.
- **Timestamps on shares round.** Two seconds, for FAT's reason, as in File
  Manager. An exact compare calls half the files newer every time.
- **Paths past 260 characters** need the `\\?\` prefix at file calls and must
  never carry it to the shell. `paths.api` from File Manager is the rule and
  the reason to port that module rather than rewrite it.
- **Both sides can be the same file.** A compare of a file with itself, or two
  paths that resolve to the same UNC, is detected before anything is read and
  said plainly, not reported as "identical".
- **A worker's answer must never arrive before the question has an id.** A
  read that finishes before `Loader.submit` returns -- a folder, a missing
  file -- runs its done-callback on the calling thread at once. Emitted
  directly, it reached the session before the session had stored the request
  id, matched nothing, and the side said "Reading..." forever. `Loader`
  therefore relays every answer through a `QueuedConnection`. Anything that
  adds another way of running work keeps that property.
- **A Qt socket belongs to the thread that made it.** A test that called
  `instance.hand_over` from a Python thread crashed Qt a test later. The
  hand-over test starts a real second process, which is also what File
  Manager does.
- **A socket emits `disconnected` from inside its own destructor.** The
  listener detaches its handlers before closing anything, and deletes each
  socket in exactly one place. The first version deleted from two places and
  crashed inside whichever event loop ran next -- in the tests, somebody
  else's.
- **The command line is Windows paths, and the tests are not on Windows.**
  `cli.resolve` uses `ntpath` for anything Windows-shaped and leaves a POSIX
  path alone off Windows; without that, every path in the tests had its
  slashes turned round and was "Not found".
- **The view draws the lines the result was computed from, never the live
  documents.** `Session.result_lines` is the snapshot a comparison ran on.
  After an edit to a large file the new diff runs on the loader, and until it
  answers the documents are ahead of the rows; a view reading the live lines
  would index past the end of a list. For the same reason a block copy or an
  edit is refused (with a status message) while `Session.current` is False.
  Small files (`SYNC_LINES`) are compared on the spot, so that window is
  normally never seen.
- **A file without a final newline keeps not having one.** `Document.replace`
  carries the last line's ending to whichever line is last after the edit,
  and widens the splice by a line when it must change the line before it, so
  undo restores that too. `test_edit.py` has the cases.
- **A save must never outlive its check.** The file's size and time are
  compared with what was read immediately before the rename, after the new
  bytes are on disk, not before writing them: a save to a share takes long
  enough for somebody else's save to land in between.
- **An L5X rung's number is in its crumb, never its line.** Put it in the
  text and inserting one rung makes every later rung a difference. The same
  goes for structured text line numbers. `test_formats.py` holds the fixture
  pair that proves the four real changes are the only four differences.
- **Folder compare's deadline is a stall, not a total.** A walk that is still
  finding files is a slow share, not a dead one; `FolderSession._tick` marks
  a side not answering only when its count has not moved for the timeout.
- **A tree view's `::item` rule in QSS switches off the model's background
  role.** The folder tree's row washes vanished the moment the sheet styled
  `::item`; the verdict colours are carried by the text colour instead. A
  delegate is the way back to washes if they are wanted.
- **A file can change under an open tab.** Poll the two files on an interval
  (not a watcher; SMB change notification is unreliable) and offer a reload
  when one changes. Never reload over unsaved edits without asking.

## Build order

0. Done so far: steps 1 to 6 and the L5X/XML/JSON/INI half of step 9
   (0.4.0: folder compare; 0.5.0: format-aware compare and the sibling
   handoff) (0.2.0 added editing, saving and find; 0.3.0
   the installer, updates, Explorer verbs and File Manager's compare rows,
   which shipped in File Manager 0.41.0).
   The window, title bar, tabs, start page, the command line and the
   single-instance hand-over; the engine with whitespace, case, blank-line
   and pattern rules; the reader; the side-by-side view with the gutter, the
   overview map, intraline marks by character or word, next and previous.

1. **Skeleton.** Window, custom title bar, tabs, theme ported from File
   Manager, Options, command palette, `tools/preview.py`, the command line and
   single-instance handoff. Opening a pair shows the two files as text, not
   yet compared.
2. **The text engine, headless.** Line hashing, histogram diff, the row model,
   ignore rules, and `app.harness diff`. Fixture pairs in
   `tests/data/text/` for each case that has bitten other tools: moved blocks,
   repeated lines, whitespace-only changes, mixed line endings, a 100 MB log
   with a one-line change.
3. **The text view.** Side by side, gutter, overview map, intraline,
   next/previous, find. (Find, text selection and copy are not in 0.1.)
4. **Editing and saving.** Copy blocks, undo, encodings, the save rules.
5. **Installer and the File Manager handoff.** App Paths, the command rows
   changed in File Manager, auto-update. From here it replaces Beyond Compare
   for single files.
6. **Folder compare.** Walk, size and time, then content, filters, open a pair
   in a tab.
7. **Hex and image.**
8. **Three-way merge** and the git tool configuration.
9. **Format-aware:** L5X first, then XML, JSON, CSV and Excel tables.
10. Later: reports (HTML, unified patch), saved sessions, archive compare,
    Explorer verbs, folder sync actions.

## Open decisions

- **Folder sync actions.** Copying and deleting from the folder view is what
  Beyond Compare does, and File Manager's rule is that there is never a second
  implementation of a destructive operation. The two ways out: hand the plan
  to File Manager's queue (needs a handoff File Manager does not have yet), or
  vendor File Manager's copy engine here with its invariants intact. Decide
  before step 10, not during it.
- **Dependencies to approve**, each only when its step arrives:
  `Pillow` (image compare; File Manager already ships it),
  `charset-normalizer` (encoding detection beyond BOM and UTF-8),
  `Pygments` (syntax colouring), `openpyxl` (Excel tables).

## Packaging and releasing

Same shape as File Manager and Redline PDF: **public GitHub repo, installer
with auto-update from GitHub releases, built iteratively across sessions.**

- PyInstaller freezes a **folder**, not a single file -- this is launched from
  File Manager many times a day and a onefile build unpacks on every launch.
- `packaging/entry.py` calls `multiprocessing.freeze_support()` first, or
  every worker re-launches the window.
- Inno Setup installs **per user** into `%LOCALAPPDATA%`, so updates need no
  UAC prompt. It registers App Paths.
- **The build tool builds and `gh` publishes, never both.** `packaging/build.py`
  makes no network call; the release workflow publishes; both fail if
  `latest.json` is missing or names a file not in `dist/`.
- Output filenames carry no spaces (GitHub turns them into dots on upload).
- `app/core/updates.py` is ported from File Manager: reads `latest.json` from
  this repo's `releases/latest/download/`, refuses URLs outside it, verifies
  size and SHA-256 before running anything.
- Bumping a version means three files: `app/__init__.py`, `pyproject.toml`
  and `CHANGELOG.md`. The release workflow refuses a tag that disagrees with
  the first.

## Scope

Offline, single-user, local-file desktop app. No accounts, no telemetry, no
cloud anything. Nothing about the files compared leaves the machine.

**The one exception is the update check**: one request to the release feed
shortly after launch, only when auto-update is on, nothing downloaded without
a prompt, nothing sent outward. A second network call is a new decision, not
an extension of this one.

This is not being built for Encore machines. Leave that environment out of
design decisions entirely.
