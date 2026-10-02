"""The diff engine. Pure: sequences in, data out.

No Qt, no files, no threads. Everything here is covered by `pytest`, and that
is the point of keeping it this way -- it is the part of the application that
can be proved without anybody watching a window.

  lines.py      which lines match (histogram diff)
  align.py      the row model built from those matches
  intraline.py  what differs inside a pair of lines
"""

from app.core.diff.align import (  # noqa: F401
    CHANGED,
    DELETED,
    EQUAL,
    IGNORED,
    INSERTED,
    NONE,
    Block,
    Comparison,
    Move,
    compare,
)
