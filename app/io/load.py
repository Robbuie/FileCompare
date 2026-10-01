"""Reading a file for comparison, and saying exactly what was found in it.

A compare tool quietly damages files in two places: the read, where bytes are
decoded under a guess, and the save, where they are encoded back under a
different one. This module is the read, and its rule is that nothing it
decides is hidden. The encoding, whether there was a byte order mark, which
line endings the file uses and whether anything failed to decode all travel
with the text, are shown in the side's header, and are what a save will use.

The order of the encoding ladder:

  1. **A byte order mark** settles it: UTF-8, UTF-16 or UTF-32.
  2. **UTF-16 without a mark**, recognised by NULs in every other byte of the
     first few kilobytes. Some PLC and HMI tools write exactly this.
  3. **UTF-8**, strictly. Almost everything is, and a strict decode that
     succeeds on non-ASCII text is very strong evidence.
  4. **Another code page** (1.2), when Windows-1252 would read the file's
     words as nonsense and one of the others reads them cleanly: Central
     European, Cyrillic, Greek, Turkish, Baltic, DOS, Japanese, Chinese,
     Korean. `io/detect.py` decides, and the header says "(detected)".
  5. **Windows-1252**, which is what an old file on a Windows share almost
     always is when it is not UTF-8. Five byte values are undefined in it;
     a file containing one falls to
  6. **Latin-1**, which decodes every byte and is marked as a guess.

A file that is none of these -- NULs outside a UTF-16 pattern, and not
UTF-16 text in another script either -- is binary, and is reported as such
rather than decoded into nonsense.

The side's menu can read a file as a named encoding instead (`encoding=`),
for when the ladder is wrong; that answer is used as given.

Nothing here imports Qt. It runs off the UI thread, and the long-path rule is
applied here at the file call and nowhere else (`longpath.api`).
"""

from __future__ import annotations

import codecs
import hashlib
import os
import re
from dataclasses import dataclass, field

from app.io import detect, longpath

#: How much of the start of a file the sniffing looks at.
SNIFF = 8192

#: Files larger than this are not read as text. A setting; this is its default.
MAX_BYTES = 512 * 1024 * 1024

#: The bytes themselves are kept, for hex and image compare, up to this size.
#: Past it a side is text only: two copies of a 300 MB log in memory to offer
#: a hex view nobody asked for is a poor trade.
KEEP_BYTES = 64 * 1024 * 1024

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),   # before UTF-16 LE, which it starts with
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

#: What the header shows for each encoding name used here.
LABELS = {
    "utf-8": "UTF-8",
    "utf-16-le": "UTF-16 LE",
    "utf-16-be": "UTF-16 BE",
    "utf-32-le": "UTF-32 LE",
    "utf-32-be": "UTF-32 BE",
    "cp1252": "Windows-1252",
    "latin-1": "Latin-1",
    "ascii": "ASCII",
    "cp1250": "Windows-1250",
    "cp1251": "Windows-1251",
    "cp1253": "Windows-1253",
    "cp1254": "Windows-1254",
    "cp1257": "Windows-1257",
    "cp437": "DOS 437",
    "cp850": "DOS 850",
    "cp866": "DOS 866",
    "shift_jis": "Shift JIS",
    "big5": "Big5",
    "euc_kr": "EUC-KR",
    "gb18030": "GB18030",
    "utf-16": "UTF-16",
}

#: What the side's "Read as" menu offers: (label, encoding). Everything the
#: detector can answer, and the Unicode forms.
READ_AS = (
    ("UTF-8", "utf-8"),
    ("Windows-1252 (Western)", "cp1252"),
    ("Windows-1250 (Central European)", "cp1250"),
    ("Windows-1251 (Cyrillic)", "cp1251"),
    ("Windows-1253 (Greek)", "cp1253"),
    ("Windows-1254 (Turkish)", "cp1254"),
    ("Windows-1257 (Baltic)", "cp1257"),
    ("DOS 437 (US)", "cp437"),
    ("DOS 850 (Western)", "cp850"),
    ("DOS 866 (Cyrillic)", "cp866"),
    ("Shift JIS (Japanese)", "shift_jis"),
    ("GB18030 (Chinese, simplified)", "gb18030"),
    ("Big5 (Chinese, traditional)", "big5"),
    ("EUC-KR (Korean)", "euc_kr"),
    ("UTF-16 LE", "utf-16-le"),
    ("UTF-16 BE", "utf-16-be"),
    ("Latin-1 (every byte as itself)", "latin-1"),
)


def label(encoding: str) -> str:
    return LABELS.get(encoding, encoding)


@dataclass
class Loaded:
    """One side, as read. Plain data: it crosses a thread boundary."""

    path: str
    ok: bool = False
    #: Why it could not be read, in words, when `ok` is False.
    error: str = ""
    size: int = 0
    mtime: float = 0.0
    #: A hash of the bytes as read, so "identical" can mean byte for byte and
    #: two binary files can at least be said to match or not.
    digest: str = ""
    binary: bool = False
    encoding: str = ""
    bom: bool = False
    #: True when the encoding came from the last rung of the ladder.
    guessed: bool = False
    #: 1.2: True when `io/detect.py` chose the code page, and when the side's
    #: menu did (`forced`).
    detected: bool = False
    forced: bool = False
    #: True when some bytes did not decode and were replaced. Such a side is
    #: never editable as text: saving it would write the replacements back.
    lossy: bool = False
    #: "CRLF", "LF", "CR", "mixed" or "" for a file with one line and no ending.
    eol: str = ""
    lines: list[str] = field(default_factory=list)
    #: The ending of each line ("\r\n", "\n", "\r" or ""), kept for the save.
    endings: list[str] = field(default_factory=list)
    #: The bytes as read, for hex and image compare; None past `KEEP_BYTES`.
    data: bytes | None = field(default=None, repr=False)

    @property
    def facts(self) -> str:
        """The header's summary: encoding, mark, endings, line count."""
        if not self.ok:
            return ""
        if self.binary:
            return f"binary  ·  {_size(self.size)}"
        name = LABELS.get(self.encoding, self.encoding)
        if self.bom:
            name += " BOM"
        if self.guessed:
            name += " (guess)"
        elif self.forced:
            name += " (chosen)"
        elif self.detected:
            name += " (detected)"
        parts = [name]
        if self.eol:
            parts.append(self.eol)
        parts.append(f"{len(self.lines):,} line{'s' if len(self.lines) != 1 else ''}")
        return "  ·  ".join(parts)


def load(path: str, *, max_bytes: int = MAX_BYTES, encoding: str = "") -> Loaded:
    """Read and decode one file. Never raises: a failure is a `Loaded` that
    says why, which is what the side's header shows. `encoding` reads it as
    that instead of working one out."""
    out = Loaded(path=path)
    target = longpath.api(path)
    try:
        info = os.stat(target)
    except FileNotFoundError:
        out.error = "Not found"
        return out
    except PermissionError:
        out.error = "Access is denied"
        return out
    except OSError as exc:
        out.error = _reason(exc)
        return out
    if os.path.isdir(target):
        out.error = "This is a folder"
        return out
    out.size = info.st_size
    out.mtime = info.st_mtime
    if info.st_size > max_bytes:
        out.error = f"Too large to compare as text ({_size(info.st_size)})"
        return out
    try:
        with open(target, "rb") as handle:
            data = handle.read()
    except PermissionError:
        out.error = "Access is denied"
        return out
    except OSError as exc:
        out.error = _reason(exc)
        return out
    decode_into(out, data, encoding=encoding)
    return out


def decode_into(out: Loaded, data: bytes, *, encoding: str = "") -> None:
    """The ladder, on bytes already read. Separate so the tests can feed it
    bytes without touching a disk."""
    out.size = out.size or len(data)
    out.data = data if len(data) <= KEEP_BYTES else None
    out.digest = hashlib.blake2b(data, digest_size=16).hexdigest()
    if encoding:
        _decode_as(out, data, encoding)
        return
    encoding, bom = _sniff(data)
    if encoding is None:
        wide = detect.utf16(data)
        if wide is None:
            out.ok = True
            out.binary = True
            return
        encoding, bom = wide, b""
        out.detected = True
    body = data[len(bom):] if bom else data
    out.bom = bool(bom)
    text: str
    if encoding == "utf-8" and not bom:
        try:
            text = body.decode("utf-8")
            encoding = "ascii" if body.isascii() else "utf-8"
        except UnicodeDecodeError:
            page = detect.detect(body)
            if page is not None and page != "cp1252":
                text = body.decode(page)
                encoding = page
                out.detected = True
            else:
                try:
                    text = body.decode("cp1252")
                    encoding = "cp1252"
                except UnicodeDecodeError:
                    text = body.decode("latin-1")
                    encoding = "latin-1"
                    out.guessed = True
    else:
        try:
            text = body.decode(encoding)
        except UnicodeDecodeError:
            text = body.decode(encoding, errors="replace")
            out.lossy = True
    out.encoding = encoding
    out.lines, out.endings = split(text)
    out.eol = eol_style(out.endings)
    out.ok = True


def _decode_as(out: Loaded, data: bytes, encoding: str) -> None:
    """Read as the encoding somebody chose. A mark that belongs to it is
    taken off and kept; bytes it cannot decode are replaced and the side is
    marked lossy, so it is never saved back over the file."""
    out.forced = True
    body = data
    for mark, name in _BOMS:
        if data.startswith(mark) and (name == encoding or (
                name.startswith("utf-16") and encoding == "utf-16")):
            body = data[len(mark):]
            out.bom = True
            break
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError:
        text = body.decode(encoding, errors="replace")
        out.lossy = True
    except LookupError:
        out.error = f"Unknown encoding: {encoding}"
        return
    if encoding not in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be",
                        "latin-1") and not out.lossy:
        # A multi-byte page can decode two byte sequences to one character;
        # only one that gives the same bytes back may be edited and saved.
        try:
            if text.encode(encoding) != body:
                out.lossy = True
        except UnicodeEncodeError:
            out.lossy = True
    out.encoding = encoding
    out.lines, out.endings = split(text)
    out.eol = eol_style(out.endings)
    out.ok = True


_BREAK = re.compile(r"\r\n|\r|\n")


def split(text: str) -> tuple[list[str], list[str]]:
    """Lines without endings, and the endings, exactly.

    `str.splitlines` is not used: it also splits on form feed, vertical tab
    and a handful of Unicode separators, and a file with a form feed in it
    would come back with a line that was never there -- and be saved that way.
    Only CR, LF and CRLF end a line here.

    One pass of a compiled pattern. The first version walked the text in
    Python and looked ahead for the next CR with `find`, which in a file with
    no CR at all scans to the end once per line: 2.6 seconds for 60,000.
    """
    lines: list[str] = []
    endings: list[str] = []
    start = 0
    for match in _BREAK.finditer(text):
        lines.append(text[start:match.start()])
        endings.append(match.group())
        start = match.end()
    if start < len(text):
        lines.append(text[start:])
        endings.append("")
    return lines, endings


def eol_style(endings: list[str]) -> str:
    kinds = {e for e in endings if e}
    if not kinds:
        return ""
    if len(kinds) > 1:
        return "mixed"
    return {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[kinds.pop()]


def _sniff(data: bytes) -> tuple[str | None, bytes]:
    for mark, name in _BOMS:
        if data.startswith(mark):
            return name, mark
    head = data[:SNIFF]
    if b"\x00" not in head:
        return "utf-8", b""
    # UTF-16 without a mark: ASCII-range text has a NUL in every other byte.
    even = head[0::2]
    odd = head[1::2]
    if len(head) >= 4:
        if odd.count(0) > 0.7 * len(odd) and even.count(0) < 0.1 * len(even):
            return "utf-16-le", b""
        if even.count(0) > 0.7 * len(even) and odd.count(0) < 0.1 * len(odd):
            return "utf-16-be", b""
    return None, b""


def _reason(exc: OSError) -> str:
    text = exc.strerror or str(exc)
    return text[0].upper() + text[1:] if text else "Could not be read"


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} bytes"
