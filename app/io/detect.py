"""Which legacy code page a file that is not UTF-8 is in (1.2).

The reader (`io/load.py`) settles most files on its own: a byte order mark,
UTF-16 by its NULs, strict UTF-8. What is left is a file written in a
Windows or DOS code page, and there the old answer was always Windows-1252 --
right for an English, German, French or Spanish file, and quietly wrong for a
Czech, Polish, Russian, Greek or Japanese one, or for a DOS tool's report full
of box drawing. Wrong without saying so: every byte still round-trips, so a
save loses nothing, but the text on screen is not the text in the file, and a
compare of two such files marks the wrong words.

**Why not charset-normalizer.** It was the candidate. Measured on the files
this is for -- mostly ASCII, a few accented words -- it read ordinary
Windows-1252 text as Baltic or Central European more often than not, which
would have made the common case worse to fix the rare one. What decides here
is simpler and aimed at that shape of file:

  * Only the lines holding a byte over 127 are looked at. The ASCII around
    them says nothing about the code page and drowns any statistic.
  * Each candidate decodes those lines strictly (a byte it does not define
    rules it out), and every word with a non-ASCII letter in it is judged:
    **one script** is a word; Latin and Cyrillic in one word, a symbol in the
    middle of a word (`by³y` is `były` read as the wrong page), or a Latin
    word of four or more letters with no plain letter in it (`Äâèãàòåëü` is
    Russian read as Western; `été` is French and is left alone) are not.
  * **Windows-1252 wins unless it reads badly.** It is tried first and kept
    whenever its words read as words; the others are asked only when it does
    not. Two pages that both read cleanly -- Windows-1250 and 1252 share most
    of their accented letters -- are left as 1252, and the side's menu reads
    the file as another page when that was wrong.

Pure: bytes in, a codec name out. No Qt, no files.
"""

from __future__ import annotations

import unicodedata

#: In the order they are preferred when more than one reads cleanly.
SINGLE_BYTE = ("cp1252", "cp1251", "cp1250", "cp1253", "cp1254", "cp1257",
               "cp437", "cp850", "cp866")
#: Multi-byte pages, tried when no single-byte page reads cleanly. GB18030
#: decodes almost anything, so it is last.
MULTI_BYTE = ("shift_jis", "big5", "euc_kr", "gb18030")

#: How much of the non-ASCII part of a file is looked at.
SAMPLE = 64 * 1024

def sample(data: bytes, limit: int = SAMPLE) -> bytes:
    """The lines with a byte over 127, up to `limit` bytes of them."""
    kept: list[bytes] = []
    size = 0
    for line in data.split(b"\n"):
        if not line.isascii():
            kept.append(line)
            size += len(line) + 1
            if size >= limit:
                break
    return b"\n".join(kept)


def _script(ch: str) -> str:
    if ch.isascii():
        return "LATIN"
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "UNKNOWN"
    for script in ("LATIN", "CYRILLIC", "GREEK", "HEBREW", "ARABIC", "HANGUL",
                   "HIRAGANA", "KATAKANA", "CJK", "THAI"):
        if name.startswith(script) or f" {script} " in f" {name} ":
            if script in ("HIRAGANA", "KATAKANA", "CJK"):
                return "CJK"      # Japanese mixes all three in one word
            return script
    if "IDEOGRAPH" in name:
        return "CJK"
    return "OTHER"


def judge(text: str) -> tuple[int, int]:
    """(bad, good) for decoded text: how many non-ASCII characters sit where
    they would in a real file, and how many do not."""
    good = bad = 0
    word: list[str] = []

    def close() -> None:
        nonlocal good, bad
        if not word:
            return
        foreign = [c for c in word if not c.isascii()]
        if foreign:
            scripts = {_script(c) for c in word}
            if len(scripts) > 1:
                bad += len(foreign)
            elif scripts == {"LATIN"} and len(foreign) == len(word) and len(word) >= 4:
                # A Latin word with no plain letter in it: Cyrillic or Greek
                # read as Western, or DOS box drawing read as letters.
                bad += len(foreign)
            else:
                good += len(foreign)
        word.clear()

    previous = ""
    for index, ch in enumerate(text):
        if ch.isalpha():
            word.append(ch)
            previous = ch
            continue
        if not ch.isascii():
            category = unicodedata.category(ch)
            following = text[index + 1] if index + 1 < len(text) else ""
            between_letters = (previous.isalpha() and following.isalpha()
                               and _script(previous) != "CJK"
                               and _script(following) != "CJK")
            if category.startswith("C"):
                bad += 3
            elif between_letters and category[0] in "SN" and ch != "·":
                # `by³y`, `£ódŸ`: a symbol or a digit inside a word is a
                # letter from another page. Punctuation is not -- an
                # apostrophe, a hyphen, a full stop in a Japanese sentence.
                bad += 2
            else:
                good += 1
        close()
        previous = ch
    close()
    return bad, good


#: Non-ASCII characters a page has to have read cleanly before it is chosen
#: over Windows-1252. One stray byte is not evidence of anything.
EVIDENCE = 4


def reads_cleanly(bad: int, good: int) -> bool:
    return good > 0 and bad <= good * 0.02


def detect(data: bytes) -> str | None:
    """A code page that reads this file cleanly, or None.

    `data` is the whole file, already known not to be UTF-8. The answer is
    checked against all of it -- decoded strictly, and for the multi-byte
    pages encoded back to the same bytes -- not only against the sample.
    """
    part = sample(data)
    if not part:
        return None
    for group in (SINGLE_BYTE, MULTI_BYTE):
        for codec in group:
            try:
                text = part.decode(codec)
            except UnicodeDecodeError:
                continue
            bad, good = judge(text)
            if not reads_cleanly(bad, good):
                continue
            if codec != "cp1252" and good < EVIDENCE:
                continue
            if _whole(data, codec, multi=group is MULTI_BYTE):
                return codec
    return None


def _whole(data: bytes, codec: str, *, multi: bool) -> bool:
    try:
        text = data.decode(codec)
    except UnicodeDecodeError:
        return False
    if multi:
        # A multi-byte page can decode two byte sequences to one character;
        # a save would then write different bytes. Only a page that gives the
        # same bytes back is one a side may be edited in.
        try:
            return text.encode(codec) == data
        except UnicodeEncodeError:
            return False
    return True


def utf16(data: bytes) -> str | None:
    """UTF-16 without a mark whose text is not mostly Latin -- Chinese or
    Japanese, where the NUL-every-other-byte test in the reader finds too few
    NULs. Decoded strictly both ways, judged like a code page."""
    if len(data) < 4 or len(data) % 2:
        return None
    for codec in ("utf-16-le", "utf-16-be"):
        try:
            text = data[:SAMPLE].decode(codec)
        except UnicodeDecodeError:
            continue
        if any(unicodedata.category(c) == "Cc" and c not in "\t\r\n\x0c" for c in text):
            continue
        # Text has spaces or line breaks in it, and is mostly letters; a
        # repeating binary pattern that happens to decode is neither.
        spaces = sum(1 for c in text if c in " \t\r\n\u3000")
        letters = sum(1 for c in text if c.isalpha())
        if spaces * 200 < len(text) or letters * 10 < len(text) * 3:
            continue
        bad, good = judge(text)
        if reads_cleanly(bad, good) and good >= EVIDENCE:
            try:
                data.decode(codec)
            except UnicodeDecodeError:
                continue
            return codec
    return None
