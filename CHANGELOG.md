# Changelog

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
