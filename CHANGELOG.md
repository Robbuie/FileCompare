# Changelog

## 1.16.0 - rungs as ladder

- **View: Rungs** draws a Logix comparison (.L5X or .L5K) as ladder, the
  left file's rungs opposite the right's: power rails, contacts, coils,
  branches, and instruction boxes with their operands. Choose it from the
  View button above the comparison; it is there whenever a Logix pair is
  shown by its structure.
- **The instruction that changed is the one coloured.** An edited contact is
  amber on both sides, one only on the left is red, one only on the right is
  green, and the rest of the rung stays plain. A rung that was added or
  removed is coloured whole, with "not on this side" opposite it.
- Each rung is headed by its program, routine and rung number on each side
  (a renumbered rung shows both numbers), with its comment under it; a
  comment that changed is amber.
- **Differing rungs** lists only the rungs that differ; **All rungs** lists
  the unchanged ones too, greyed. The bar says how many of how many differ.
- Next and previous (the arrows, or Alt+Down and Alt+Up) step from one
  differing rung to the next, and the count line names where you are.
- **Double-click a rung, or press Enter, to see it in the text view**, at
  the same place.
- Long tags are written over two lines above a contact, broken after a `.`
  or `_`, and a rung too wide for its half wraps onto a second line, as
  Logix Designer wraps it. Hover over a rung for its full text.

## 1.15.0 - big folder compares, and changing either side's folder

- **Folder compare opens collapsed and showing only the differences.** On a
  big tree the old view opened with everything listed and the differing
  folders expanded, which was a long scroll to find anything. Now each top
  folder sits on one line, and its Size column says how many files under it
  differ ("12 differ"), or for a folder on one side only, how many files it
  holds.
- **The show buttons carry their counts**: All 4,920, Differences 132, Left
  newer 41, Right newer 7, Same 4,781. They are the summary as well as the
  filter. The one you pick is kept for next time; it starts on Differences.
- **Expand** opens every folder that holds a difference, all the way down.
  Its menu has Expand all, Collapse all, and "Open with differences
  expanded" for anyone who wants the old way back. Collapse is still beside
  it.
- **Folders you open or close stay that way** when the tree is rebuilt: after
  a content compare, a filter change, Ctrl+R, or one side moved to another
  folder. Before, every one of those opened the differing folders again.
- **Each side's header is now its folder's path box**, as in Beyond Compare.
  Type or paste a folder and press Enter, and only that side changes: the
  other keeps its folder and is not read again, which matters when it is a
  slow share. Escape puts the path back.
  - **Up** (the arrow at the left) goes up one folder on that side.
  - **The arrow beside the path** lists every folder above it, so you can go
    straight up several levels, and the folders compared lately.
  - **The folder button** browses for one.
  - **Drop a folder** from File Manager or Explorer on a header to put it on
    that side.
  - A folder that is not there, or a share that stops answering, says so on
    its own side, with Retry.
- **Right-click a folder row** for "Compare these two folders" (both sides
  move down into it, keeping what was open under it), "Use as the left
  folder" and "Use as the right folder" -- the last two line up two trees
  that are not at the same depth.
- Ctrl+R in a folder compare reads both folders again and nothing else.

## 1.14.0 - copy across in folder compare

- **F5 copies the selected files and folders to the other side**, as in
  File Manager. It copies from the side you last clicked in; Tab switches
  sides. That side's header has a blue line under it so you can see which
  one it is.
- **Alt+Right and Alt+Left copy the selection right or left**, whichever
  side you're on, the same keys as in the text view.
- **"Copy to left" and "Copy to right" buttons** sit in the folder bar,
  enabled once something is selected.
- All of these open the same preview as the Sync menu, listing what will
  be copied, before File Manager's queue does the copying. Files that are
  already the same, or aren't on the side being copied from, are left out;
  if that's everything, the preview says there's nothing to copy.
- Fixed: the blue line under the focused side's header never appeared, in
  text compare either. It shows now.

## 1.13.0 - copy just the lines you pick

- **Select lines and copy just those across**, as in Beyond Compare. Drag
  over two or more lines (or Shift with the arrow keys), and arrows appear
  in the middle strip beside the selection, which is outlined in the accent
  colour. Click an arrow, or press Alt+Right or Alt+Left, to copy those
  lines over the other side's.
- It can be part of a difference, such as two lines out of a ten-line
  change, or a run across several differences. Lines that are already the
  same are left alone. One Ctrl+Z puts it all back.
- With one line or nothing selected, the arrows and Alt+Right / Alt+Left
  copy the whole difference, as before.
- **Right-click in the text** for a menu: copy the selection, the
  difference, or just this line to either side; edit, delete or insert
  lines; copy the text; select all; and align a line with the other side.
- **Shift+Enter inserts an empty line** below the cursor. The key had been
  listed since 1.0 but did nothing.

## 1.12.1 - the build, not the app

- No change to File Compare itself. Two of the font checks added in 1.11.1
  passed on a PC and failed on GitHub's build machine, which stopped the
  1.11.1 and 1.12.0 installers from being made. They now check the same
  thing in a way that holds on both. This is the installer to take for
  everything in 1.11.1 and 1.12.0.

## 1.12.0 - folder compare as two panes

- **Folder compare is laid out as two mirrored panes**, like Beyond Compare
  and File Manager: name, size and modified for the left folder, a narrow
  verdict column in the middle, then name, size and modified for the right
  folder. Before, there was one name column, and files that existed only on
  the right were listed on the left.
- **A file on one side only leaves the other half of its row empty**, and
  only the side that has it is coloured. Folders that exist on one side
  only have their arrow on that side only.
- The right side has its own indentation and arrows, and clicking a right
  arrow opens or closes that folder the same as the left one.
- **Rows show Windows' file icons**, the same ones File Manager shows. They
  are looked up by file type, never by opening or touching a file, so a slow
  share is no slower to show. Simple drawn icons stand in until they arrive.
- Each side's folder name and path now sit over that side's own half.
- The middle column looks like the text view's gutter and runs the full
  height of the view.
- The summary line no longer appears twice: it's in the status bar only.
- The name filter has a "Filter" label and no longer stretches across the
  whole bar.
- The tree uses the interface font, like File Manager's listing. Sizes still
  line up because they're right-aligned.

## 1.11.1 - text lines up again

- **The text panes now draw in the monospaced font they measure in.** The
  window's style was quietly replacing it with the interface font. Because
  every colour and character mark is placed by column, syntax colours ran
  into each other ("PROGRAMConveyor"), indentation collapsed, and the boxes
  marking changed characters sat beside the characters instead of on them.
  This affected every text compare since 1.0.
- The line editor (F2 on a selection), the Excel grid and the merge tab's
  "Edit this part" box are monospaced too now.
- On a PC without Cascadia Mono, mono text falls back to Consolas instead
  of a proportional font.

## 1.11.0 - reports from the command line

- **`FileCompare.exe A B --report out.html` compares without opening a
  window**, writes the report and exits. It's meant for scheduled checks,
  such as last night's backup against the office copy, or the running
  program against the last good export.
- **The exit code says what was found:** 0 the same, 1 different, 2 could
  not compare (a side missing or unreadable). When it fails it still writes
  the report, saying why, so the file left behind explains the code.
- Two files give the same HTML report as Ctrl+Shift+H, or a patch when the
  name ends in `.patch` or `.diff`. L5X and L5K pairs are compared by
  structure.
- **Two folders give a folder report**: every file that differs, with sizes
  and times, including files inside zips. Pairs whose size and time can't
  settle it are always read, so the report doesn't list a file whose only
  difference is its timestamp.
- **A session file can stand in for the two paths:**
  `FileCompare.exe weekly.fcsession --report out.html` uses that session's
  paths, rules and folder settings. Otherwise the rules are the ones last
  set in Options.
- From a batch file, use `start /wait "" FileCompare.exe ...` so it waits
  for the exit code. A scheduled task waits on its own.

## 1.10.0 - saved sessions

- **Ctrl+Alt+S saves a comparison's setup as a session file**
  (`.fcsession`): the two paths, their titles, the rules and ignore
  patterns, the view, Structure on or off, and any pinned lines. For a
  folder compare it also keeps the name filter, the show filter, and the
  clock and zip switches.
- **Opening the session sets up the same comparison**, read fresh from
  disk. Double-click the file (the installer associates `.fcsession` with
  File Compare), drop it on the window, or use **Open session** on the
  start page.
- A session file holds settings only, never file contents, and it's plain
  readable text. Saving again from a tab opened from a session offers the
  same file.
- Run the 1.10 installer once so double-clicking a session file works. An
  automatic update installs the association the same way.

## 1.9.0 - inside zip files

- **Folder compare lists the files inside each .zip** under the zip, as
  if it were a folder, and marks which members are the same, which differ
  and which are on one side only. A folder of backup zips now shows what
  changed inside them, not just that the zips differ.
- Nothing is unpacked to do this. Only the zip's directory is read (a few
  KB at the end of the file, however big the zip is), and members are
  compared by the size and checksum stored there.
- **Enter on a file inside a zip opens it** in a new tab, unpacked into a
  temporary folder. It opens read-only, since an edit there could not go
  back into the zip.
- The zip still counts as one file in the folder's totals, and sync copies
  the zip whole. Picking a file inside a zip for a sync leaves it alone and
  says why.
- Turn it off with **Compare contents > Look inside .zip files**. Only .zip
  files are opened this way. Word and Excel files and other formats that
  are zips underneath are compared as documents.

## 1.8.0 - folder compare and the clock

- **Files the same size whose times are exactly an hour apart now count as
  the same.** That shift is what a daylight saving change does to files on a
  FAT drive or on a share that stores local time. Before, every file copied
  before the change showed as newer on one side. These pairs are listed in
  grey, marked "same size, an hour apart", left out of the count and left
  alone by sync. Compare contents still reads them and says whether the
  bytes really agree. Turn it off with **Compare contents > Ignore a
  one-hour shift**.
- **Compare contents > Always compare contents**: after every walk, each
  pair with the same size is read, so a file only counts as different when
  its bytes differ, whatever the timestamps say. Use it on shares where you
  can't trust the timestamps. Pairs of different sizes need no reading.
- Both settings are remembered for the next folder compare.
- File Manager's own pane compare still treats an hour as newer. Its rule
  hasn't changed.

## 1.7.0 - L5K exports by structure

- **L5K files now compare the way L5X files do.** Programs, routines, tags,
  modules, data types and tasks are lined up by name, so a routine or tag
  that moved in the export is not a difference. Each difference is named by
  program, routine and rung ("Program MainProgram / MainRoutine / Rung 0")
  instead of by line number.
- Each block's attributes get a line of their own, so a changed watchdog or
  module revision is one short line that names itself, not a change
  somewhere in a long parenthesised list.
- Inserting a rung doesn't make every rung below it a difference, because
  rung numbers aren't part of the compared text.
- A module's configuration data is shown as a short fingerprint: a change
  shows which module it's in, without forty lines of numbers.
- Ignored, as the status line says: the header comment with the export date,
  and the created and edited dates and users on blocks. **Structure** turns
  it off to see and edit the file as plain text.

## 1.6.0 - align lines by hand

- **When the automatic diff lines up the wrong lines, you can say which go
  together.** Put the cursor on a line and press **Ctrl+L**, press Tab to go
  to the other side, put the cursor on the line that belongs opposite it, and
  press **Ctrl+L** again. The two lines are put on one row, and the files are
  compared separately above and below that row.
- A pinned row is marked by a bar across the gutter. Add as many pins as
  you need. A new pin that contradicts an earlier one (line 10 opposite 50,
  then line 20 opposite 40) replaces it.
- **Ctrl+Shift+L** removes the pin on the cursor's row, or every pin when
  the cursor is not on one, and cancels a pin that is only half made.
- Pins move with their lines when you edit, undo or swap sides. Turning
  Structure on or off removes them, since the lines being shown change.

## 1.5.0 - moved blocks

- **A block that was cut and pasted elsewhere is shown as a move**, not as
  lines removed in one place and unrelated lines added in another. Both ends
  are drawn in the move colour (violet) in the panes, the gutter and the
  overview map, and the status line counts them as moved.
- The difference line says where the other end is ("Moved: 6 lines, now at
  right 18"), and **Ctrl+M** jumps there and back.
- One line can be a move when it is long enough, so a rung that moved in a
  normalised L5X export shows as moved. Short lines such as `END_IF;` or `}`
  are not, since those turning up in two places is usually coincidence.
- The ignore rules apply: with whitespace ignored, a block that moved and was
  reindented is still a move.
- HTML reports colour moved lines and count them.

## 1.4.3 - the installed app starts

- **1.4.2 installed but would not start**: "No module named
  PySide6.QtNetwork". File Compare finds its already-open window through a
  local socket, which is Qt's networking module, and the installer's list of
  Qt parts to leave out -- copied from File Manager, which finds its window
  another way -- removed it. 1.4.2 was the first installer ever built, which
  is why it had not shown before. The module is shipped again, and a test now
  checks every Qt module the application uses against that list, so a build
  that leaves one out fails before it is released.
- A 1.4.2 install cannot update itself, since it cannot start: run the
  1.4.3 setup over it.

## 1.4.2 - the installer builds again

- The release build for 1.4.1 stopped at its own safety check: Qt's PDF
  library, which image compare uses to read PDFs, needs Qt's networking
  library, and the installer was leaving that out. It is kept now (about
  1.7 MB), as File Manager has done since 0.45.1, and two unused pieces of
  Qt's QML runtime that nothing could load are left out. This is 1.4.1 with
  that fix; 1.4.1 never had an installer.

## 1.4.1 - sync and share fixes from a review

- **A folder is only copied or removed whole when everything under it was
  seen.** A folder holding something that could not be read, a link or
  junction, or files the name filter hides is now left alone in the sync
  preview, saying which -- before, mirror with a filter such as `-*.bak`
  would have removed a folder along with the files the filter hid.
- **A picked file whose folder is not on the other side** is left alone
  with "copy the folder" rather than sent and failing in File Manager.
- **Swapping sides or changing the name filter** clears the tree until it
  is built again, so a sync cannot be planned from the old orientation and
  run the opposite way to the one shown.
- **A drive given on its own** (`D:`) means its root, rather than a path
  File Manager refuses.
- **The sync request names its two folders**, which File Manager 0.46.1
  requires, and File Compare stops waiting with a message if File Manager
  has not taken the request within 45 seconds, or as soon as it refuses or
  is told no.
- **Compare contents** on a pair with a local side and a share runs in the
  share's reader, and stops with a message when nothing has been read for
  the timeout.
- **Excel sheets whose files understate their size** -- some exporters
  write a wrong one -- are read in full rather than cut short and called
  the same.
- A share reader that dies at the moment a read is sent to it answers that
  read rather than leaving it waiting.

## 1.4.0 - a dead share can be stopped

- **Reads, folder walks and change checks on a network share run in a
  process of their own**, one per server. When one misses its deadline the
  side says "not answering" as before -- and now the process holding it is
  stopped and a new one starts on the next read, rather than a thread
  staying stuck in Windows' network call until Windows gives up.
- That matters most for a share that goes away while tabs are open: each
  tab checks every few seconds whether its files changed, and those checks
  could take every thread File Compare had, after which comparisons,
  colouring and reads in every tab queued behind them. They no longer can.
- Local disks are unchanged: they stay on threads, with no process to start.
- A folder compare on a share shows its file count as it walks, as before,
  and Stop still stops it.

## 1.3.0 - Excel workbooks

- **Two Excel workbooks open as a table**, like two CSV files: records
  matched on a key column wherever they are, columns matched by their names,
  each changed cell showing `old -> new`. `.xlsx`, `.xlsm`, `.xltx` and
  `.xltm`.
- **One sheet at a time.** The Sheet list names every sheet in either
  workbook and says which are the same, which differ, and which are on one
  side only; the comparison opens on the first that differs.
- Cells are compared as they read: 12 not 12.0, a date as 2026-09-30, TRUE
  and FALSE. A sheet starts at its first row with anything in it, so a
  title row and blank lines above the names do not get in the way.
- **Formulas** compares what was typed in each cell instead of the value
  Excel last calculated, so a formula that changed but gives the same answer
  still shows.
- "First row is names", "Ignore case", "Numbers by value", the key and
  "Differences only" work as they do for CSV.
- Very large sheets are compared up to 200,000 rows and 500 columns, and
  say so. An old `.xls` workbook is compared as bytes, with a line saying
  that saved as `.xlsx` it compares as a table.
- New dependency: openpyxl (MIT licence), in the installer.

## 1.2.0 - code pages, and Read as

- **Files in other code pages are read as what they are.** A file that is
  not UTF-8 used to be read as Windows-1252 whatever it held -- right for
  English, German, French and Spanish, and quietly wrong for a Czech, Polish,
  Russian, Greek, Turkish, Baltic, Japanese, Chinese or Korean file, or a DOS
  tool's report: wrong letters on screen, and a compare marking the wrong
  words. Now the lines with non-ASCII bytes are read under each likely code
  page and the one whose words read as words is used: Windows-1250, 1251,
  1253, 1254, 1257, DOS 437, 850 and 866, Shift JIS, Big5, EUC-KR and
  GB18030. The header says "(detected)".
- **Western files are read exactly as before.** Windows-1252 is kept unless
  it reads the file's words as nonsense, and one stray byte is not enough to
  switch.
- **UTF-16 without a byte order mark** in Chinese, Japanese or Korean opens
  as text rather than as binary.
- **Read as** on each side's menu reads the file again as any of seventeen
  encodings, or back to working it out. The header says "(chosen)". Unsaved
  edits on that side are asked about first.
- A detected or chosen file saves back in the same encoding, byte for byte;
  the encoding it was read in is always on the "Save with encoding" list. A
  multi-byte encoding that would not give the same bytes back makes the side
  read-only rather than risk a save.
- No new dependency: charset-normalizer was tried and read ordinary Western
  files as Baltic, so the detection is our own.

## 1.1.0 - syntax colour

- **Text is coloured by its language**, found from the file's name: about
  six hundred languages through Pygments -- C, C#, C++, VB.NET, VBScript,
  PowerShell, batch, SQL, Python, JavaScript, XML, JSON, YAML, INI, TOML,
  Markdown, G-code and the rest -- and two written here that Pygments does
  not know: **L5K** (Logix's text export, with ladder instructions,
  keywords, tag attributes and rung comments picked out) and **IEC 61131-3
  Structured Text** (`.st`, `.scl`: keywords, types, `T#5s` and `16#FF`,
  both comment styles).
- A `.L5X` compared as plain text (Structure off) colours as XML, and a
  `.nc` as G-code rather than what Pygments guesses.
- The colours are quiet and fixed per theme -- a difference is still the
  loudest thing on a row -- with a set each for the dark themes, the light
  ones, and high contrast.
- **The language button** beside the View switch says what the text is
  coloured as, and picks another from a list of forty, or plain text.
  "Colour code by language" in the menu sets the default for new tabs and
  every open one.
- A file with no extension is coloured when its first line says what it is
  (`#!` or an XML declaration). A side shown by its structure is not
  coloured. Very large files (over eight million characters) are not
  coloured; large ones are coloured in the background.
- New dependency: Pygments (BSD licence), in the installer.

## 1.0.0 - folder sync, run by File Manager

- **Sync** on the folder view's toolbar: update left to right or right to
  left (copy what is only on one side and what is newer there), or mirror
  (the same, and remove what is only on the target). The first press is
  update left to right; the arrow beside it has the other three.
- **Picked rows** from the right-click menu: copy to the right or to the
  left, which replaces what is there whatever its time, or remove from
  either side. A folder picked means the files under it that differ.
- **Everything is previewed first**: every copy and removal with a box
  beside it, ticked, and everything left alone with the reason -- newer on
  the target, the same time with different contents, a folder on one side
  and a file on the other, a link or junction, something that could not be
  read. A folder on one side only is one line, copied or removed whole. The
  direction and the mode switch in the preview without reading anything
  again.
- **File Manager does the copying.** "Send to File Manager" hands the ticked
  actions to its queue (File Manager 0.46 or later), so there is one copy
  engine: pause, cancel, the conflict rule, retry and history are its own.
  An update copies under "newer only", so a file that changed on the target
  after the compare is still not overwritten by an older one. Removals go to
  the Recycle Bin, and the preview says when the target is on a share,
  where Windows removes permanently instead.
- When File Manager's jobs finish, both folders are read again by
  themselves and the status line says how many were copied, skipped or
  failed. "Stop waiting for File Manager" on the Sync menu stops listening
  for that (the jobs carry on there).
- **Mirror needs a complete picture**: if anything could not be read, only
  update is offered, and the preview says why.
- Junctions and symbolic links are marked in the tree's data and are never
  copied, removed or walked through.

## 0.9.0 - reports, recent pairs, comments

- **Reports**: Ctrl+Shift+H saves a text comparison as a self-contained HTML
  report -- both sides in two columns, only the differences and three lines
  around each, the paths, the time and the rules in force -- or as a unified
  patch.
- **Recent pairs** on the start page, newest first; one click compares them
  again.
- **Drop a file on one side** of an open comparison to compare it against
  the other side, in a new tab so the pair it replaced is still there.
- **Ignore comments** in the Rules menu, for the file type's line comments:
  `#` for Python, PowerShell and YAML, `;` for INI, `//` for C-like languages,
  structured text and L5K, `'` for VB, `REM` for batch files, and others. A
  comment-only line is looked past like a blank line; either is shown in grey.

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
