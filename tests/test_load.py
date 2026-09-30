"""The reader: encodings, marks, line endings, binary -- and saying so."""

import codecs

from app.io import load as io_load
from app.io import longpath
from app.io.load import Loaded, decode_into, split


def decode(data: bytes) -> Loaded:
    out = Loaded(path="x")
    decode_into(out, data)
    return out


def test_plain_ascii():
    out = decode(b"one\r\ntwo\r\n")
    assert out.encoding == "ascii" and not out.bom
    assert out.lines == ["one", "two"] and out.eol == "CRLF"


def test_utf8_without_a_mark():
    out = decode("Température\n".encode("utf-8"))
    assert out.encoding == "utf-8" and out.lines == ["Température"]


def test_every_byte_order_mark():
    for mark, name in ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
                       (codecs.BOM_UTF16_BE, "utf-16-be"), (codecs.BOM_UTF32_LE, "utf-32-le")):
        codec = name if name != "utf-8" else "utf-8"
        out = decode(mark + "a\nb".encode(codec))
        assert out.encoding == name and out.bom, name
        assert out.lines == ["a", "b"], name


def test_utf16_without_a_mark():
    out = decode("Rung 0\r\nXIC(Start)\r\n".encode("utf-16-le"))
    assert out.encoding == "utf-16-le" and not out.bom and not out.binary
    assert out.lines == ["Rung 0", "XIC(Start)"]


def test_windows_1252():
    out = decode("caf\xe9 \u2013 50\u00b0".encode("cp1252"))
    assert out.encoding == "cp1252" and out.lines == ["caf\xe9 \u2013 50\u00b0"]
    assert not out.guessed


def test_undefined_windows_1252_bytes_fall_to_latin1_and_say_so():
    out = decode(b"abc\x81def")
    assert out.encoding == "latin-1" and out.guessed


def test_binary_is_not_decoded():
    out = decode(b"\x00\x01\x02\xff" * 100)
    assert out.binary and out.lines == []
    assert out.facts.startswith("binary")


def test_line_endings():
    assert decode(b"a\nb\n").eol == "LF"
    assert decode(b"a\rb\r").eol == "CR"
    assert decode(b"a\r\nb\n").eol == "mixed"
    assert decode(b"one line").eol == ""


def test_split_keeps_endings_exactly():
    lines, endings = split("a\r\nb\nc\rd")
    assert lines == ["a", "b", "c", "d"]
    assert endings == ["\r\n", "\n", "\r", ""]
    assert "".join(l + e for l, e in zip(lines, endings)) == "a\r\nb\nc\rd"


def test_form_feed_is_not_a_line_break():
    """`str.splitlines` would split here, and a save would add a line."""
    lines, _ = split("page one\x0cpage two\n")
    assert lines == ["page one\x0cpage two"]


def test_a_final_line_without_an_ending_is_kept():
    lines, endings = split("a\nb")
    assert lines == ["a", "b"] and endings == ["\n", ""]


def test_lossy_utf16_is_marked():
    out = decode(codecs.BOM_UTF16_LE + b"a\x00\x00\xd8")   # a lone surrogate
    assert out.lossy


def test_load_reports_missing_and_folders(tmp_path):
    assert io_load.load(str(tmp_path / "nope.txt")).error == "Not found"
    assert io_load.load(str(tmp_path)).error == "This is a folder"


def test_load_refuses_a_file_over_the_limit(tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 2000)
    out = io_load.load(str(big), max_bytes=1000)
    assert not out.ok and "Too large" in out.error


def test_digest_is_of_the_bytes(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"same\r\n")
    b.write_bytes(b"same\n")
    la, lb = io_load.load(str(a)), io_load.load(str(b))
    assert la.lines == lb.lines and la.digest != lb.digest


def test_long_path_prefix(monkeypatch):
    assert longpath.extended("\\\\server\\share\\x") == "\\\\?\\UNC\\server\\share\\x"
    assert longpath.extended("\\\\?\\C:\\x") == "\\\\?\\C:\\x"
    assert longpath.display("\\\\?\\UNC\\server\\share\\x") == "\\\\server\\share\\x"
    assert longpath.display("\\\\?\\C:\\x") == "C:\\x"
