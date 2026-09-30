"""Walking a folder tree, and reading two files to see whether they match.

Both run off the UI thread, in the loader, and both are written to be stopped:
a walk of a share with fifty thousand files can take a minute when the share
is slow, and a tab closed in the middle of it should stop it rather than leave
a thread listing folders for nobody.

**`os.scandir`, never a `stat` per file.** On Windows the directory listing
already carries size and modification time, and on SMB a `stat` per file is a
round trip per file. File Manager learned this in its listing code and this is
the same rule.

**Junctions and symbolic links are listed, not followed.** A junction that
points at its own parent is a walk that never ends; one that points at another
share is a walk of somewhere nobody asked for.

Progress is reported through a small shared object the UI polls on a timer,
rather than a signal per folder: fifty thousand signals queued onto the UI
thread would be slower than the walk.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from app.core.folders import Entry
from app.io import longpath

#: Bytes read at a time when comparing contents.
CHUNK = 1 << 20


@dataclass
class Progress:
    """Written by the walk, read by the UI. A few ints; no lock needed for a
    number that is only ever shown."""

    folders: int = 0
    files: int = 0
    current: str = ""
    done: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()


class Cancelled(Exception):
    pass


def walk(root: str, progress: Progress | None = None) -> list[Entry]:
    """Every folder and file under `root`, with paths relative to it."""
    progress = progress or Progress()
    out: list[Entry] = []
    top = longpath.api(root)
    if not os.path.isdir(top):
        raise FileNotFoundError(f"Not a folder: {root}")
    stack = [("", top)]
    while stack:
        if progress.cancelled:
            raise Cancelled()
        rel, path = stack.pop()
        progress.current = rel
        try:
            with os.scandir(path) as listing:
                items = list(listing)
        except OSError as exc:
            if rel:
                out.append(Entry(rel=rel, is_dir=True, error=_reason(exc)))
                continue
            raise
        progress.folders += 1
        for item in items:
            child = f"{rel}\\{item.name}" if rel else item.name
            try:
                is_dir = item.is_dir(follow_symlinks=False)
                link = item.is_symlink() or _is_junction(item)
                if is_dir:
                    out.append(Entry(rel=child, is_dir=True, is_link=link))
                    if not link:
                        stack.append((child, item.path))
                    continue
                info = item.stat(follow_symlinks=False)
            except OSError as exc:
                out.append(Entry(rel=child, is_dir=False, error=_reason(exc)))
                continue
            out.append(Entry(rel=child, is_dir=False, size=info.st_size, mtime=info.st_mtime,
                             is_link=link))
            progress.files += 1
    progress.done = True
    return out


def same_bytes(left: str, right: str, cancel: threading.Event | None = None) -> bool:
    """Whether two files hold the same bytes. Stops at the first difference,
    so two large files that differ early cost almost nothing."""
    with open(longpath.api(left), "rb") as a, open(longpath.api(right), "rb") as b:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            x = a.read(CHUNK)
            y = b.read(CHUNK)
            if x != y:
                return False
            if not x:
                return True


def compare_contents(pairs: list[tuple[int, str, str]], progress: Progress) -> list[tuple[int, bool | None, str]]:
    """`(key, left, right)` for each pair; `(key, same, error)` back.

    One job for the whole batch rather than one per pair: a thousand queued
    jobs would each wait behind the other tabs' reads, and one job reports
    progress through the same object as the walk.
    """
    out = []
    for key, left, right in pairs:
        if progress.cancelled:
            break
        progress.current = left
        try:
            out.append((key, same_bytes(left, right, progress.cancel), ""))
        except Cancelled:
            break
        except OSError as exc:
            out.append((key, None, _reason(exc)))
        progress.files += 1
    progress.done = True
    return out


def _is_junction(item: os.DirEntry) -> bool:
    try:
        return bool(getattr(item, "is_junction", lambda: False)())
    except OSError:
        return False


def _reason(exc: OSError) -> str:
    text = exc.strerror or str(exc)
    return text[0].upper() + text[1:] if text else "Could not be read"
