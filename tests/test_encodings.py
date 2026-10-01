"""Code pages beyond Windows-1252 (1.2): the detector, the reader, Read as,
and that a detected file saves back byte for byte."""

from __future__ import annotations

import pytest

from app.io import detect, load, save

ASCII = ("TAG Motor_Run : BOOL := 0;\nROUTINE Main\n  N: XIC(Start)OTE(Run);\n"
         "END_ROUTINE\n") * 40

TEXTS = {
    "cp1252": "Café résumé naïve — “quoted” motor läuft über die Straße. Größe, été.\n",
    "cp1250": "Příliš žluťoučký kůň úpěl ďábelské ódy. Motor běží na lince tři.\n",
    "cp1251": "Двигатель запущен на линии три, ячейка четыре. Проверьте датчик.\n",
    "cp437": "┌────────────┐\n│ Motor ÄÖÜ äöü ß │\n└────────────┘ Temperatur 20°C\n",
    "shift_jis": "モーターが起動しました。ライン3のセル4です。圧力センサーを確認してください。\n",
    "gb18030": "电机已启动。第三条线第四单元。请检查压力传感器和阀门。\n",
    "big5": "電機已啟動。第三條線第四單元。請檢查壓力感測器和閥門。\n",
}
POLISH = "Łódź: silnik był włączony, sprawdź czujnik ciśnienia. Zażółć gęślą jaźń.\n"


@pytest.mark.parametrize("codec", sorted(TEXTS))
@pytest.mark.parametrize("shape", ["dense", "sparse", "one line"])
def test_each_page_is_found_whether_the_file_is_full_of_it_or_mostly_ascii(codec, shape):
    text = TEXTS[codec]
    body = {"dense": text * 20, "sparse": ASCII + text * 2 + ASCII,
            "one line": ASCII + text}[shape]
    assert detect.detect(body.encode(codec)) == codec


def test_polish_is_central_european_not_western():
    assert detect.detect((ASCII + POLISH).encode("cp1250")) == "cp1250"


@pytest.mark.parametrize("text", [
    "Temperature 20°C ±2, Motor „Läuft“ €5\n",
    "Señal de presión baja — revisar válvula\n",
    "L’état du moteur: arrêté. Vérifiez la sécurité à l’entrée.\n",
    "Temp 20°\n",
])
def test_ordinary_western_text_stays_windows_1252(text):
    assert detect.detect((ASCII + text).encode("cp1252")) == "cp1252"


def test_the_judge_catches_the_three_shapes_of_a_wrong_page():
    assert detect.judge("by³y")[0] > 0                 # a symbol inside a word
    assert detect.judge("Äâèãàòåëü")[0] > 0            # accents and no plain letter
    assert detect.judge("Prиvet")[0] > 0          # Latin and Cyrillic in one word
    assert detect.judge("été Größe l’eau")[0] == 0


def test_the_reader_says_what_it_detected():
    got = load.Loaded(path="x")
    load.decode_into(got, (ASCII + TEXTS["cp1251"]).encode("cp1251"))
    assert got.encoding == "cp1251" and got.detected
    assert "Windows-1251 (detected)" in got.facts
    assert "Двигатель" in got.lines[-1]


def test_western_files_read_exactly_as_before():
    got = load.Loaded(path="x")
    load.decode_into(got, "Größe\n".encode("cp1252"))
    assert got.encoding == "cp1252" and not got.detected and "(detected)" not in got.facts


def test_utf16_without_a_mark_in_another_script_is_text_not_binary():
    got = load.Loaded(path="x")
    load.decode_into(got, ("电机已启动。第三条线\r\n" * 30).encode("utf-16-le"))
    assert not got.binary and got.encoding == "utf-16-le" and got.lines[0] == "电机已启动。第三条线"


def test_real_binary_stays_binary():
    got = load.Loaded(path="x")
    load.decode_into(got, bytes(range(256)) * 8)
    assert got.binary


def test_read_as_uses_the_encoding_given_and_says_so():
    got = load.Loaded(path="x")
    load.decode_into(got, "Größe\n".encode("cp1252"), encoding="cp1251")
    assert got.forced and got.encoding == "cp1251" and "(chosen)" in got.facts
    assert got.lines == ["GrцЯe"]


def test_read_as_utf8_on_bytes_that_are_not_marks_the_side_lossy():
    got = load.Loaded(path="x")
    load.decode_into(got, "Größe\n".encode("cp1252"), encoding="utf-8")
    assert got.lossy


def test_read_as_takes_off_a_mark_that_belongs_to_the_encoding():
    got = load.Loaded(path="x")
    load.decode_into(got, b"\xef\xbb\xbfabc\n", encoding="utf-8")
    assert got.bom and got.lines == ["abc"]


@pytest.mark.parametrize("codec", ["cp1250", "cp1251", "cp437", "shift_jis", "big5"])
def test_a_detected_file_saves_back_byte_for_byte(codec):
    data = (ASCII + TEXTS.get(codec, POLISH) * 3).replace("\n", "\r\n").encode(codec)
    got = load.Loaded(path="x")
    load.decode_into(got, data)
    assert got.encoding == codec and not got.lossy
    assert save.encode(got.lines, got.endings, got.encoding, got.bom) == data


def test_the_session_reads_one_side_again_as_chosen(tmp_path):
    import time

    from PySide6.QtWidgets import QApplication

    from app.core.loader import Loader
    from app.core.session import Session

    left = tmp_path / "a.txt"
    right = tmp_path / "b.txt"
    left.write_bytes("Größe\n".encode("cp1252"))
    right.write_bytes(b"x\n")
    loader = Loader()
    session = Session(loader, str(left), str(right))
    session.start()

    def wait():
        end = time.monotonic() + 5
        while session.result is None and time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.01)

    wait()
    assert session.sides[0].loaded.encoding == "cp1252"
    session.read_as(0, "cp1251")
    wait()
    assert session.sides[0].loaded.encoding == "cp1251"
    assert session.sides[0].lines == ["GrцЯe"]
    assert session.sides[0].encoding == "cp1251"     # what a save would write
    session.stop()
    loader.shutdown()
