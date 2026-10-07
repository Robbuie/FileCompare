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

python -m app a.L5K b.L5K --report r.html                  # 1.11: no window; exit 0/1/2
python -m app C:\A D:\B --report r.html                    # folder report
python -m app saved.fcsession --report r.patch             # a session's paths and rules
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
- `core/diff/merge3.py` -- three-way merge: sync points where both sides
  kept a base line, chunks between them, conflicts, resolutions, output with
  git's markers for anything unresolved. Pure.
- `core/mergesession.py` -- one merge: three reads, the merge, the save.
- `core/rules.py` -- what counts as a difference: whitespace, case, line
  endings, regex "unimportant" text, per-format rules.
- `core/formats/` -- format-aware comparers that normalise before the line
  diff (L5X, XML, JSON, INI). Each returns canonical lines, a crumb per line
  (where it is in the file's structure) and what it ignored. The session runs
  them in the compare job; a side shown through one is read-only.
- `core/hexdiff.py` -- hex compare by offset, chunked so equal regions cost
  one memory compare. Pure.
- `core/imagediff.py` -- decode and compare two images with QImage and
  QPainter's Difference composition, off the UI thread (QImage is safe
  there; QPixmap is not).
- `core/tables.py` -- CSV table compare: sniffed delimiter, columns matched
  by name, rows matched on a key column chosen automatically. Pure.
- `core/workbook.py` -- Excel workbooks (1.3) through openpyxl: every sheet
  read once into `tables.Table`s, cells as a person reads them, values or
  formulas, sheets matched by name. Runs in the loader.
- `core/syntax.py` -- syntax colour (1.1): the language from the file's
  name, Pygments' lexers plus our own for L5K and Structured Text, and per
  line `(start, stop, category)` spans in display columns. `theme/syntax.py`
  holds the colours, fixed per theme like the diff colours.
- `core/siblings.py` -- which pairs Redline PDF and DWG Viewer compare better,
  and where those install; `io/launch.py` starts them.
- `core/session.py` -- one open comparison: its sides, its deadlines, its
  result, its edits and saves.
- `core/folders.py` -- folder compare's merged tree and its verdicts, masks
  and show filters. Pure, like the engine.
- `core/folderdiff.py` -- one folder comparison: two walks with a stall
  deadline, the tree built off the UI thread, a content compare, and (1.0)
  the sync handed to File Manager and the wait for its result.
- `core/syncplan.py` -- update, mirror and picked-row plans from the tree,
  and the request File Manager's `core/handoff.py` reads. Pure.
- `core/document.py` -- one side's text while it is edited: lines, their
  endings, and undo/redo as splices. Pure; the tests prove it alone.
- `core/loader.py` -- runs work off the UI thread and hands the answer back
  on it, always as a queued event (see "Things that will bite you").
- `core/instance.py` -- the single-instance socket.
- `core/appearance.py` -- ours or File Manager's theme, accent and density.

**`app/io/`** -- every real filesystem call, off the UI thread.

- `io/load.py` -- read a file, detect encoding, BOM and line endings, return
  the decoded lines, the endings, a hash of the bytes and what was detected;
  or read it as a named encoding (the side's "Read as").
- `io/detect.py` -- which code page a file that is not UTF-8 is in (1.2):
  the non-ASCII lines only, each candidate judged by whether its words are
  words in one script, Windows-1252 kept unless it reads badly. Pure.
- `io/kind.py` -- file, folder or missing, for a path from the command line.
- `io/longpath.py` -- the `\\?\` rule, ported from File Manager's `paths.py`.
- `io/save.py` -- encode with the side's encoding, mark and per-line
  endings, write beside, check the file did not move, rename.
- `io/walk.py` -- a tree by `os.scandir`, junctions listed and not
  followed, cancellable; and "are these two files the same bytes".
- `io/handoff.py` -- write a sync request, start `FileManager.exe --queue`,
  read the result File Manager writes beside it.
- `io/read.py` -- opening a side (what the path is, its text), here so a
  worker process can run it without importing Qt.
- `io/pool.py` / `io/volume.py` -- worker processes per network volume, and
  which volume a path is on (1.4).
- `io/shellicons.py` -- Windows' icon for a kind of file, by extension and
  never by path, through ctypes (1.12). Touches no file; None off Windows.

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

### Threads for work, processes for shares (1.4)

Each side loads independently, off the UI thread, under a deadline
(`load.timeout`). A side that misses it shows "not answering" with a Retry,
the other side stays usable, and the late answer is dropped by request id.

Computation -- diffs, colour, tables, hex, images -- runs on the loader's
small thread pool (`Loader.submit`). **Reads** go through
`Loader.submit_io(path, fn, ...)`: on a local disk, the same threads; on a
network volume (`io/volume.py`: a UNC server, or a letter `GetDriveType`
calls remote), a worker process for that server (`io/pool.py`). A deadline
missed calls `Loader.abandon(request)`, which kills the worker holding it --
answering everything it held with "stopped answering" -- and the next read
of that share starts a fresh one. That is what keeps stuck reads, and above
all the every-three-seconds change checks of every open tab, from piling up
on threads the rest of the window needs. Saves stay on threads: a save is
asked for once, and a write is not something to kill half way.

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
- Moved-block detection (1.5): a run removed in one place and added unchanged
  in another is one move with two ends, drawn in the move colour, counted as
  moved rather than as lines only on each side, and Ctrl+M goes from one end
  to the other. The rows keep their DELETED and INSERTED kinds; a block's
  `move` and `Comparison.moves` carry the pairing. A move needs at least
  `MOVE_MIN_CHARS` of text, so one L5X rung counts and a lone `end;` does not.
- Manual alignment (1.6): Ctrl+L on a line, Tab, Ctrl+L on a line of the other
  side pins them onto one row; the diff runs separately between pins
  (`align.compare(..., pins)`), so nothing matches across one. Pins live on
  the session, newest first, in the numbering of the lines shown; edits,
  undo and swap carry them (`shift_pins`), a structure toggle drops them, and
  a pin that crosses a newer one gives way (`valid_pins`).
- Syntax colour (1.1) by the file's name, about six hundred languages
  through Pygments and L5K and Structured Text through our own lexers; a
  language menu in the toolbar picks another or none.

Copying across is by rows, not blocks: `Session.copy_rows(start, end,
to_side)` replaces the target's lines in those rows with the source's, using
`align.side_range` on each side, so part of a block, or a run across several
blocks, copies exactly what was selected and one undo step takes it back
(1.13). `copy_block` is `copy_rows` over the block. A single selected row is
the cursor, not a selection, and copies its whole block -- one stray click
must not shrink what Alt+Right copies.

**Folder** -- recursive, both trees side by side.
- Laid out as two mirrored halves (1.12): name, size, modified on the left;
  a verdict column drawn like the text gutter; name, size, modified on the
  right. Still one `QTreeView` and one model, so the halves cannot drift;
  `RightNames` in `ui/folderview.py` draws the right name's indent, chevron
  and icon from the same depth. A file on one side only leaves the other half
  blank and unwashed. Sizes and times are fixed widths from the font, the
  names share what is left, so the halves are always equal and the tab puts
  each side's header over its own half (`FolderView.split`).
- Row icons are Windows' own, by kind (`io/shellicons.py`, ctypes, the
  SHGFI_USEFILEATTRIBUTES rule from File Manager's CLAUDE.md), fetched on one
  icon thread and cached per kind (`ui/fileicons.py`). Drawn glyphs stand in
  until they land and stay off Windows. Never ask for an icon by path.
- The tree is in the interface font, like File Manager's listing. Once the
  sheet styles `::item`, Qt stops drawing BackgroundRole, so the wash is
  painted by the delegates (`_wash_cell`).
- Compare by size and time (instant), then by content (queued, cancellable,
  per file). Size-and-time uses File Manager's two-second tolerance and
  case-insensitive names for the same reasons stated in its `core/compare.py`.
- Two clock switches (1.8), in the Compare contents menu and kept in the
  settings: **ignore a one-hour shift** (`folders.ignore_hour`, on) makes a
  same-size pair exactly an hour apart `HOUR_APART` -- shown grey, not
  counted, never synced, still read by a content compare. This is the one
  place the verdicts knowingly differ from File Manager's pane compare.
  **Always compare contents** (`folders.by_content`, off) reads every
  same-size pair after each walk.
- Zip contents (1.9, `folders.archives`, on): `io/archive.py` reads each
  .zip's central directory during the walk and lists its members as entries
  with `archive` (the zip's rel) and `crc` set. A member pair is judged by
  size and CRC (`verdict`), never read, counted (`counts`, `Node.files`),
  content-compared or synced (`syncplan` skips it as INSIDE_ZIP; the zip is
  one file). Enter on one extracts the pair to `%TEMP%\FileCompare\zip`
  off the UI thread and opens it read-only. Only `.zip`: .docx, .xlsx and
  the other zip-shaped formats are documents.
- Filters: name masks, show only differences, only one side, hide equal
  folders. Since 1.15 the show buttons carry their counts
  (`folders.show_counts`) and the pick is kept (`folders.show`, default
  Differences).
- Opens collapsed (1.15). A folder row's Size column is its rollup
  (`_rollup`): "N differ", or a one-sided folder's file count. Expand opens
  every folder holding a difference; `folders.open_expanded` brings back the
  old opening (differing folders to depth 3). **Every model reset closes
  every folder**, so `FolderView._rebuild` keeps the open folders by rel
  (`_opened`) and puts them back -- after a content compare, a filter, a
  walk again or a side moved. `forget_open` is for both sides moving at once.
- Each side's header is its path box (1.15, `SideHead.set_folder_mode`):
  Enter, Up, the parent/recent menu, browse, or a drop calls
  `CompareTab.set_folder`, which runs `FolderSession.set_path` -- that side
  walked again, the other side's entries kept -- and updates the
  `core.Session` side's path so the title, Ctrl+Alt+S and swap agree. Paths
  are handled as strings (`folders.tidy`, `ancestors`, `same_path`); whether
  one is a folder is the walk's to say, and it says so on that side's
  header. A row's menu re-roots one side or both (`FolderView.rebase`).
  Ctrl+R on a folder tab walks again and never reloads `core.Session`,
  which could turn the tab into a message if a side is no longer a folder.
- Enter on a pair opens it in a new tab in the right mode.
- Sync (1.0): update, mirror and picked rows, previewed in
  `ui/syncdialog.py` and run by File Manager's queue. See "Working with File
  Manager".

**Hex / binary** -- side by side, aligned by offset, differing bytes marked.
The fallback for anything that will not decode, and the right answer for
firmware images and binary exports.

**Image** -- side by side, overlay, swipe slider, blink, and a difference
mask with a tolerance. Same modes and same chip control as Redline PDF's
compare panel, so the two read as the same tool.

**Three-way merge** -- mine, base, theirs, with the output pane under them.
Conflicts are their own kind with their own navigation. This is also what
makes the app usable as git's `mergetool`.

**Table** -- CSV and (1.3) Excel `.xlsx`/`.xlsm`: rows matched on a key
column rather than by position, so an inserted row is one difference and not
every row after it. A workbook pair compares one sheet at a time, chosen by
name from a list that says which differ; cells are the values Excel saved,
or the formulas. The old binary `.xls` is compared as bytes and says why.

**Format-aware** (normalise, then text compare):
- **L5X (Logix exports)** -- ignore `ExportDate` and other attributes that
  change on every export, compare rung by rung within a routine, and name
  differences by program, routine, rung and tag rather than by line number.
  File Manager's `app/io/logix.py` already reads these; its lessons apply.
- **L5K (1.7)** -- the text form of the same export, read into its blocks and
  `;` statements by `core/formats/l5k.py` and written out in the same shape
  as the L5X comparer's: one line per attribute, sorted collections, rung
  numbers in the crumb, module data as a hash, the header comment ignored.
  The reader is forgiving -- an unknown block is kept if the file closes it,
  a statement missing its `;` ends at its block's END_ line -- and a file
  with no CONTROLLER block is refused and compared as text.
- **Rung view (1.16)** -- View: Rungs on an L5X/L5K pair shown by its
  structure. `core/ladder.py` (pure) parses each rung's neutral text into
  series and branches, lays it out on a cell grid (top level wraps,
  branches never split), matches the two rungs instruction by instruction
  (`mark`), and picks the rung pairs out of the comparison's own rows
  (`pairs`) -- nothing is compared again, and a removed-then-added rung in
  one place is one pair. `ui/rungview.py` paints only the pairs on screen.
  The parser keeps anything it does not understand as a box of its own
  text; a rung is never dropped.
- **XML** -- attribute order and insignificant whitespace ignored.
- **JSON / INI** -- key order ignored.

**Saved sessions (1.10)** -- Ctrl+Alt+S writes the tab's setup (paths,
titles, read-only sides, view, rules without the markers, intraline,
structure, pins, and for folders the mask, show filter and clock and zip
switches) as indented JSON, `.fcsession` (`core/savedsession.py`; never any
content). Opening one -- on the command line, by double-click (the
installer associates the extension per user), dropped on the window, or the
start page's Open session -- is read by `io/sessionfile.py` in the loader,
and its settings go over the application's own through
`MainWindow._compare_page(saved=)`. `loads` refuses a newer version and
ignores keys it does not know.

**Command-line report (1.11)** -- `--report PATH` runs `app/batch.py`
before Qt is created and exits: no window, no hand-over to a running one.
Two files give the text report (HTML, or a unified patch for .patch/.diff)
through the format comparer when it is on by default; two folders give a
folder report of every differing row, with the size-and-time-undecided
pairs always read; one `.fcsession` supplies paths and rules. Exit 0 same,
1 different, 2 failed -- and a failure still writes a page saying why.
Reads directly, not through the loader: nothing to keep responsive, and a
test proves the path never imports PySide6. `rules.from_config` is shared
with the window so a report says what the window would.

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
- **A code page is detected, never assumed past Windows-1252** (1.2). A file
  that is not UTF-8 is Windows-1252 unless `io/detect.py` finds that 1252
  reads its words as nonsense and another page reads them cleanly; the
  header says "(detected)", and the side's **Read as** menu reads it as any
  other page ("(chosen)"). A multi-byte page is only accepted, detected or
  chosen, when it encodes back to the same bytes; otherwise the side is
  lossy and read-only.
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
Ctrl+M                 the other end of a moved block (1.5)
Ctrl+L, Ctrl+L         pin this line opposite one on the other side (1.6)
Ctrl+Shift+L           remove the pin here, or all pins
Ctrl+Alt+S             save this comparison's setup as a session (1.10)
Alt+Right / Alt+Left   copy to the right, to the left: the selected rows when
                       two or more are selected and one differs (1.13), else
                       the current block. The gutter draws the selection's
                       own arrows, in the accent, at its first row.
Shift+Enter            insert an empty line below the cursor (handled 1.13)
Ctrl+Alt+Right / Left  copy all differences across
Home / End             first, last difference (from the overview map)
Tab                    the other side                    (File Manager's Tab)
Ctrl+U                 swap sides                        (File Manager's swap panes)
Ctrl+R                 compare again from disk           (File Manager's refresh)
F5                     copy the selected rows from the side last clicked (or
                       Tabbed to) to the other, folder mode  (File Manager's
                       copy; built 1.14). Alt+Right / Alt+Left copy them one
                       way whatever the side. All go through the sync preview.
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
  with five tabs. **Except `--wait` and `--merge`**: git waits for the
  program it started and deletes its temporary files when it exits, so those
  run in a window of their own that takes no hand-overs, and exit when it
  closes.
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
- **Folder sync runs in File Manager's queue** (1.0, File Manager 0.46). This
  application never copies or removes a file: `core/syncplan.py` plans,
  `ui/syncdialog.py` shows every action with a box, and `io/handoff.py`
  writes the ticked ones as `{"version": 1, "jobs": [...]}` -- at most one
  copy job (`sources`, `destination`, `into`, `conflict`) and one recycle
  job -- under `%LOCALAPPDATA%\FileCompare\handoff`, then starts
  `FileManager.exe --queue <file>`. File Manager refuses the whole request
  unless every part is a copy or a recycle of full paths landing under the
  destination, so **the request format is a contract with that repo**:
  change it there and here in the same sitting, and bump `version`. Since
  1.4.1 / File Manager 0.46.1 it carries `source_root` and `target_root`,
  and File Manager refuses any path outside them and any request file not
  in the handoff folder. File Manager answers every request beside it
  (`.taken.json`, then `.result.json`), and `FolderSession` gives up after
  `TAKE_SECONDS` without a "taken". When the
  jobs end File Manager writes `<name>.result.json` beside the request;
  `FolderSession` polls for it every two seconds, then walks again. File
  Manager shows no second dialog, which is why nothing is sent here that the
  preview did not show ticked.

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

- **A stylesheet font beats `setFont`.** The sheet sets the UI family on every
  `QWidget`, so `widget.setFont(mono_font(...))` is silently undone and
  `self.font()` is Segoe UI. The painted panes keep their own `self.mono` and
  paint with that; a Qt widget that wants mono gets it from a `{mono}` rule in
  `theme/sheet.py`. And Qt's stylesheet keeps only the *first* family of a
  list, so `{mono}` means Cascadia Mono alone unless the substitution
  `sheet.apply` installs is there. Until 1.11.1 every syntax colour and
  character mark was drawn beside its text; `tests/test_fonts.py` is the
  guard. Always look at a preview of text before calling it right.

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
- **A binary file of NULs every other byte reads as UTF-16.** That is the
  sniffer doing its job (some PLC tools write exactly that), and it means a
  test "binary" file must not be `b"\x00\x01" * n`.
- **Folder compare's deadline is a stall, not a total.** A walk that is still
  finding files is a slow share, not a dead one; `FolderSession._tick` marks
  a side not answering only when its count has not moved for the timeout.
- **A tree view's `::item` rule in QSS switches off the model's background
  role.** The folder tree's row washes vanished the moment the sheet styled
  `::item`; the verdict colours are carried by the text colour instead. A
  delegate is the way back to washes if they are wanted.
- **Syntax colour is lexed over the whole file, and only drawn for the
  lines it was lexed from.** A comment or string spans lines, so lexing a
  line at a time colours half a file as a string. The spans are held with
  the very list they came from (`ViewState.syntax`), and the view draws
  them only while that list is still the one on screen: after an edit the
  rows move on first, and old colours on new lines would land on the wrong
  words. Small files are lexed on the spot (`SYNC_LIMIT`), large ones in the
  loader, and past `LIMIT` not at all. Pygments must be given
  `stripnl=False` -- its default strips leading blank lines and every span
  after them lands one row high. A side shown by its structure is not
  coloured: those are lines this application wrote.
- **Detection is tuned against the cases that matter, and the tests hold
  it there.** `test_encodings.py` runs every page dense, sparse (one line
  of it in a page of ASCII) and as a single line, plus ordinary Western
  text that must stay 1252. A change to `detect.judge` that fixes one page
  by breaking 1252 shows up there first. Two rules that were learned: a
  page other than 1252 needs `EVIDENCE` clean characters before it is
  chosen (one stray `0x81` is not a DOS file), and UTF-16 without a mark
  must have spaces or line breaks in it and be mostly letters (a repeating
  binary pattern decodes as UTF-16 too).
- **A workbook is binary to the reader and a table to the tab.** `io/load`
  keeps its bytes (up to `KEEP_BYTES`), the session calls it BINARY, and the
  tab's table view reads those bytes through `core/workbook.py` in the
  loader -- never `side.lines`, which a binary side does not have. A
  workbook's cells are the values Excel calculated *when it last saved*: a
  file written by a script and never opened in Excel has none, which is
  what "Formulas" is for. `workbook.read` is cached on the bytes, so
  changing the key or a toggle does not parse the file again.
- **A sync never takes a folder whole that holds anything it did not see.**
  `syncplan._whole_refusal`: nothing unreadable, no link or junction, and
  nothing the name mask left out (`Node.masked`, set by `folders.build` for
  every folder above an excluded entry). Each was a way for mirror or a
  picked removal to delete files nobody was shown; the tests in
  `test_sync.py` under "what the review found" hold them.
- **A job for `submit_io` lives in `app/io/` and takes `progress=` by
  name.** A worker process imports the job's module to run it, and a module
  under `app/core/` or `app/ui/` brings Qt -- fifty megabytes and a fifth of
  a second -- into every worker. The function goes by reference, so it must
  be module-level; its arguments and its answer cross by pickle, so plain
  data only. Progress comes back as messages a few times a second and is
  copied into the caller's `Progress`; a cancel set on that object is
  carried to the worker by the loader's watch timer. A test that wants a
  process off a network sets `volume.FORCE_REMOTE`.
- **A file can change under an open tab.** Poll the two files on an interval
  (not a watcher; SMB change notification is unreliable) and offer a reload
  when one changes. Never reload over unsaved edits without asking.

## Build order

0. Done so far: steps 1 to 9, less Excel tables, and from step 10 the HTML
   report and unified patch, recent pairs and the Explorer verbs
   (0.4.0: folder compare; 0.5.0: format-aware compare and the sibling
   handoff; 0.6.0: hex and image, with no new dependency -- Pillow was not
   needed; 0.7.0: CSV tables; 0.8.0: three-way merge and `--wait`) (0.2.0 added editing, saving and find; 0.3.0
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
10. Later: saved sessions, archive compare, folder sync actions (see Open
    decisions), Excel tables (needs `openpyxl`), the one-column inline view
    (Ctrl+Shift+I is reserved for it), moved-block detection, syntax colour
    (needs `Pygments`). Moved blocks shipped in 1.5.

## Open decisions

- **Folder sync actions** -- decided (1.0): handed to File Manager's queue.
- **Dependencies** -- approved 2026-09-30: `Pygments` (syntax colour, 1.1),
  `charset-normalizer` (encodings beyond BOM and UTF-8), `openpyxl` (Excel
  tables). `Pillow` was never needed. `charset-normalizer` was tried for 1.2
  and **not used**: on mostly-ASCII files with a few accented words it read
  ordinary Windows-1252 as Baltic or Central European, so `io/detect.py`
  does the job instead (see its docstring). Anything past these is asked
  again.

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
