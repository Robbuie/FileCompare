"""Excel workbooks in table compare (1.3)."""

from __future__ import annotations

import datetime as dt
import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.core import tables, workbook  # noqa: E402


def book_bytes(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_cells_read_as_a_person_reads_them():
    assert workbook.text(12.0) == "12"
    assert workbook.text(12.5) == "12.5"
    assert workbook.text(True) == "TRUE"
    assert workbook.text(None) == ""
    assert workbook.text(dt.datetime(2026, 9, 30)) == "2026-09-30"
    assert workbook.text(dt.datetime(2026, 9, 30, 6, 5)) == "2026-09-30 06:05:00"


def test_a_sheet_reads_from_its_first_row_with_anything_in_it():
    data = book_bytes({"Tags": [[], [], ["Tag", "Address", "Desc"],
                                ["Motor1", "N7:0", "Run"], ["Motor2", 12, None]]})
    book = workbook.read(data)
    table = book.sheets["Tags"]
    assert table.header == ["Tag", "Address", "Desc"]
    assert table.rows == [["Motor1", "N7:0", "Run"], ["Motor2", "12", ""]]


def test_sheets_are_matched_by_name_and_say_which_differ():
    left = workbook.read(book_bytes({"A": [["k", "v"], ["1", "x"]], "B": [["k"], ["1"]],
                                     "Old": [["k"]]}))
    right = workbook.read(book_bytes({"B": [["k"], ["1"]], "A": [["k", "v"], ["1", "y"]],
                                      "New": [["k"]]}))
    states = {s.name: s for s in workbook.sheet_states(left, right)}
    assert states["A"].same is False and states["B"].same is True
    assert states["Old"].right is False and states["New"].left is False
    assert workbook.first_different(workbook.sheet_states(left, right)) == "A"


def test_formulas_or_the_values_they_gave():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append(["k", "total"])
    ws.append(["a", "=1+1"])
    out = io.BytesIO()
    wb.save(out)
    book = workbook.read(out.getvalue(), formulas=True)
    assert book.sheets["S"].rows == [["a", "=1+1"]]
    # Saved by openpyxl, never opened in Excel: no calculated value is stored.
    assert workbook.read(out.getvalue()).sheets["S"].rows == [["a", ""]]


def test_without_names_the_first_row_is_data():
    book = workbook.read(book_bytes({"S": [["a", "b"], ["c", "d"]]}))
    table = workbook.table(book, "S", header=False)
    assert table.header == ["Column 1", "Column 2"]
    assert table.rows == [["a", "b"], ["c", "d"]]
    assert workbook.table(book, "Missing").rows == []


def test_not_a_workbook_says_so():
    with pytest.raises(ValueError, match="Not a workbook"):
        workbook.read(b"PK\x03\x04 not really")


def test_the_job_keys_records_and_picks_the_sheet_that_differs():
    from app.ui.comparetab import _workbook_job

    left = book_bytes({"Same": [["k"], ["1"]],
                       "Tags": [["Tag", "Addr"], ["M1", "N7:0"], ["M2", "N7:1"]]})
    right = book_bytes({"Same": [["k"], ["1"]],
                        "Tags": [["Tag", "Addr"], ["M3", "N7:2"], ["M1", "N7:9"]]})
    result, states, sheet, note = _workbook_job(left, right, tables.Options())
    assert sheet == "Tags" and note == ""
    assert result.counts == {tables.SAME: 0, tables.CHANGED: 1, tables.ONLY_LEFT: 1,
                             tables.ONLY_RIGHT: 1}
    assert result.columns[result.key].name == "Tag"
    again, _s, chosen, _n = _workbook_job(left, right, tables.Options(sheet="Same"))
    assert chosen == "Same" and not again.differences


def test_a_workbook_on_one_side_only_is_all_one_side():
    from app.ui.comparetab import _workbook_job

    right = book_bytes({"S": [["k"], ["1"], ["2"]]})
    result, _states, sheet, _n = _workbook_job(b"", right, tables.Options())
    assert sheet == "S" and result.counts[tables.ONLY_RIGHT] == 2


def test_names_say_which_files_are_workbooks():
    assert workbook.is_workbook("C:\\x\\Schedule.XLSX")
    assert workbook.is_workbook("a.xlsm")
    assert not workbook.is_workbook("a.xls") and workbook.is_old_workbook("a.xls")


def test_a_sheet_that_understates_its_size_is_read_whole():
    import re
    import zipfile

    data = book_bytes({"S": [["k", "v"]] + [[f"r{i}", i] for i in range(40)]})
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            body = source.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                body = re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1:B2"/>', body)
            target.writestr(item, body)
    assert len(workbook.read(out.getvalue()).sheets["S"].rows) == 40
