"""What is inside a .zip, for folder compare (1.9).

A folder of backups is often a folder of zips, and "these two zips differ"
says nothing about which file inside them did. With archives on, a walk lists
each zip's members as if the zip were a folder, and folder compare shows them
under it.

Only the zip's **central directory** is read: a few kilobytes at the end of
the file, however large the zip is. It carries every member's name, size,
time and CRC-32, which is enough to say whether two members hold the same
bytes without decompressing either -- two members with the same size and the
same CRC are taken as the same, as every archive tool takes them. Nothing is
extracted until a pair is opened in a tab, and then only that pair, into a
temporary folder.

Pure reading. Nothing here writes into a zip, and nothing ever will: a
member is shown and compared, never saved back.
"""

from __future__ import annotations

import os
import tempfile
import time
import zipfile

from app.core.folders import Entry
from app.io import longpath

#: Extensions read as archives. Not .docx, .xlsx, .jar and the other formats
#: that happen to be zips: those are documents, compared as documents.
EXTENSIONS = (".zip",)

#: A member larger than this is not extracted to be opened; the reader would
#: refuse it anyway, and a temporary folder is no place for it.
EXTRACT_LIMIT = 512 * 1024 * 1024


def is_archive(name: str) -> bool:
    return name.lower().endswith(EXTENSIONS)


def members(path: str, rel: str) -> list[Entry]:
    """The members of the zip at `path`, as entries under `rel` (the zip's
    own relative path). Folders a member's name implies are listed too, so
    the tree has a node for each. Raises on a file that is not a zip."""
    out: list[Entry] = []
    seen_dirs: set[str] = set()

    def add_dir(inner: str) -> None:
        key = inner.lower()
        if not inner or key in seen_dirs:
            return
        parent = inner.rpartition("\\")[0]
        add_dir(parent)
        seen_dirs.add(key)
        out.append(Entry(rel=f"{rel}\\{inner}", is_dir=True, archive=rel))

    with zipfile.ZipFile(longpath.api(path)) as archive:
        for info in archive.infolist():
            inner = _inner(info.filename)
            if not inner:
                continue
            if info.is_dir():
                add_dir(inner)
                continue
            add_dir(inner.rpartition("\\")[0])
            out.append(Entry(rel=f"{rel}\\{inner}", is_dir=False, size=info.file_size,
                             mtime=_mtime(info.date_time), archive=rel, crc=info.CRC))
    return out


def _inner(name: str) -> str:
    """A member's name as a relative Windows path, or '' for one that would
    climb out of the zip or is absolute -- shown nowhere, opened never."""
    parts = [p for p in name.replace("\\", "/").split("/") if p and p != "."]
    if not parts or ".." in parts or ":" in parts[0]:
        return ""
    return "\\".join(parts)


def _mtime(date_time: tuple) -> float:
    """A zip stores local time to two seconds, with no zone. Read as local
    time, which is what the file's timestamp was when it was zipped."""
    try:
        return time.mktime(tuple(date_time) + (0, 0, -1))
    except (OverflowError, ValueError):
        return 0.0


def extract(zip_path: str, inner: str, dest: str) -> str:
    """One member, written into the folder `dest`; its path back."""
    with zipfile.ZipFile(longpath.api(zip_path)) as archive:
        name = _find(archive, inner)
        info = archive.getinfo(name)
        if info.file_size > EXTRACT_LIMIT:
            raise OSError(f"{inner} is {info.file_size // (1024 * 1024)} MB; "
                          "too large to open from inside a zip")
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, inner.rpartition("\\")[2] or "member")
        with archive.open(name) as source, open(target, "wb") as out:
            while True:
                chunk = source.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    os.utime(target, (_mtime(info.date_time),) * 2)
    return target


def extract_pair(left: tuple[str, str] | None, right: tuple[str, str] | None) -> tuple[str, str]:
    """`(zip path, member)` per side, either None; the two extracted paths,
    '' for a side that had nothing. Each side gets its own folder, so two
    members with the same name do not land on each other."""
    base = os.path.join(tempfile.gettempdir(), "FileCompare", "zip")
    os.makedirs(base, exist_ok=True)
    out = []
    for side, which in ((left, "left"), (right, "right")):
        if side is None:
            out.append("")
            continue
        folder = tempfile.mkdtemp(prefix=f"{which}-", dir=base)
        out.append(extract(side[0], side[1], folder))
    return out[0], out[1]


def _find(archive: zipfile.ZipFile, inner: str) -> str:
    wanted = inner.lower()
    for name in archive.namelist():
        if _inner(name).lower() == wanted:
            return name
    raise FileNotFoundError(f"{inner} is not in the zip")
