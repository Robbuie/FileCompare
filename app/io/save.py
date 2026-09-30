"""Writing one side back to disk: the only place this application changes a file.

The rules, from CLAUDE.md's "Text, bytes and saving", and each one is here
because a compare tool somewhere has broken it:

  * **The same encoding, mark and endings it was read with**, unless somebody
    changed one on purpose. The endings are per line (`Document.endings`), so
    a mixed file stays exactly as mixed as it was outside the lines edited.
  * **Text that the encoding cannot hold is refused, not replaced.** A
    Windows-1252 file given a character from outside it would otherwise be
    saved with a question mark where the character was. The error names the
    line, and the side's encoding menu is the way out.
  * **Write beside, then rename.** The new bytes go to a temporary file in the
    same folder, are flushed to the disk, and only then take the real name --
    in one `os.replace`, which on the same volume is atomic on Windows and on
    SMB. Nothing half-written ever carries the name.
  * **The file on disk must still be the one that was loaded.** Size and
    modification time are checked immediately before the rename; if either
    moved, nothing is written and the caller is told, so the user can reload,
    overwrite or save elsewhere.
  * **A read-only file is not written.** The attribute is somebody's decision.
  * **A backup is a setting**: `name.ext.orig` beside the file, made once per
    session, off by default.

Runs off the UI thread, like every other filesystem call. Never raises: the
answer is a `Saved` that says what happened.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass

from app.io import longpath

#: How close two modification times of *the same file* must be to count as
#: unchanged. Not File Manager's two seconds: that tolerance is for comparing
#: two different files across filesystems that round differently. The same
#: file asked twice answers the same, and a two-second window would miss a
#: same-size rewrite made just after the read.
MTIME_SLACK = 0.001


@dataclass
class Saved:
    ok: bool
    path: str
    error: str = ""
    #: True when the file changed on disk since it was loaded, and nothing was
    #: written because of it.
    conflict: bool = False
    size: int = 0
    mtime: float = 0.0
    backup: str = ""


def encode(lines: list[str], endings: list[str], encoding: str, bom: bool) -> bytes:
    """The bytes for a document. Raises `UnicodeEncodeError` with the line
    number in its reason when the encoding cannot hold a character."""
    codec = {"ascii": "utf-8"}.get(encoding, encoding) or "utf-8"
    parts: list[bytes] = []
    if bom:
        parts.append(_BOM.get(codec, b""))
    for number, (line, ending) in enumerate(zip(lines, endings), 1):
        try:
            parts.append((line + ending).encode(codec))
        except UnicodeEncodeError as exc:
            bad = line[exc.start] if exc.start < len(line) else "?"
            raise UnicodeEncodeError(
                exc.encoding, exc.object, exc.start, exc.end,
                f"line {number} has {bad!r} (U+{ord(bad):04X}), which "
                f"{_label(codec)} cannot hold") from None
    return b"".join(parts)


_BOM = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
    "utf-32-le": b"\xff\xfe\x00\x00",
    "utf-32-be": b"\x00\x00\xfe\xff",
}


def _label(codec: str) -> str:
    from app.io.load import LABELS

    return LABELS.get(codec, codec)


def save(path: str, data: bytes, *, expect_size: int | None = None,
         expect_mtime: float | None = None, backup: bool = False,
         force: bool = False) -> Saved:
    """Write `data` to `path` safely. `expect_*` are what the file was when it
    was loaded; None for a file that did not exist then (save as)."""
    target = longpath.api(path)
    out = Saved(ok=False, path=path)
    try:
        info = os.stat(target)
    except FileNotFoundError:
        info = None
    except OSError as exc:
        out.error = _reason(exc)
        return out
    if info is not None:
        if not (info.st_mode & stat.S_IWRITE) or _readonly_attr(info):
            out.error = "The file is read-only"
            return out
        if not force and expect_size is not None and _moved(info, expect_size, expect_mtime):
            out.conflict = True
            out.error = "The file changed on disk after it was read"
            return out
    folder = os.path.dirname(target) or "."
    name = os.path.basename(target)
    try:
        handle, temp = tempfile.mkstemp(prefix=f".{name}.", suffix=".fcsave", dir=folder)
    except OSError as exc:
        out.error = f"Could not write in the folder: {_reason(exc)}"
        return out
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if info is not None:
            # Keep the mode bits the file had; mkstemp makes it 0600.
            try:
                os.chmod(temp, stat.S_IMODE(info.st_mode))
            except OSError:
                pass
            # The last look, as late as it can be: a second writer that got in
            # while the bytes were going out is still caught.
            if not force and expect_size is not None:
                try:
                    again = os.stat(target)
                except OSError:
                    again = None
                if again is not None and _moved(again, expect_size, expect_mtime):
                    out.conflict = True
                    out.error = "The file changed on disk while saving"
                    _discard(temp)
                    return out
            if backup:
                copy = target + ".orig"
                if not os.path.exists(copy):
                    shutil.copy2(target, copy)
                    out.backup = path + ".orig"
        os.replace(temp, target)
    except OSError as exc:
        _discard(temp)
        out.error = _reason(exc)
        return out
    try:
        info = os.stat(target)
        out.size, out.mtime = info.st_size, info.st_mtime
    except OSError:
        pass
    out.ok = True
    return out


def probe(path: str) -> tuple[int, float] | None:
    """Size and modification time, or None when it is not there. For the
    poll that notices a file changing under an open tab."""
    try:
        info = os.stat(longpath.api(path))
    except OSError:
        return None
    return info.st_size, info.st_mtime


def changed(now: tuple[int, float] | None, size: int, mtime: float) -> bool:
    if now is None:
        return True
    return now[0] != size or abs(now[1] - mtime) > MTIME_SLACK


def _moved(info: os.stat_result, size: int, mtime: float | None) -> bool:
    if info.st_size != size:
        return True
    return mtime is not None and abs(info.st_mtime - mtime) > MTIME_SLACK


def _readonly_attr(info: os.stat_result) -> bool:
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_READONLY", 1)) if attrs else False


def _discard(temp: str) -> None:
    try:
        os.remove(temp)
    except OSError:
        pass


def _reason(exc: OSError) -> str:
    text = exc.strerror or str(exc)
    return text[0].upper() + text[1:] if text else "Could not be written"
