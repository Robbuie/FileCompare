"""Table compare: rows matched on a key, cells compared by column name."""

from app.core import tables as T


def test_rows_match_on_the_key_wherever_they_are():
    left = T.parse("Tag,Address,Desc\nMotor1,N7:0,Spindle\nMotor2,N7:1,Feed\nValve,N7:2,Air\n")
    right = T.parse("Tag,Desc,Address\nValve,Air,N7:2\nNew,Coolant,N7:9\nMotor1,Spindle,N7:5\n")
    result = T.compare(left, right)
    assert result.columns[result.key].name == "Tag"
    by_tag = {}
    for row in result.rows:
        name = result.cell(row, 0, 0) or result.cell(row, 0, 1)
        by_tag[name] = row
    assert by_tag["Motor1"].status == T.CHANGED
    assert by_tag["Motor1"].cells == frozenset({1})          # Address, by name
    assert by_tag["Motor2"].status == T.ONLY_LEFT
    assert by_tag["Valve"].status == T.SAME                   # column order ignored
    assert by_tag["New"].status == T.ONLY_RIGHT
    assert result.counts == {T.SAME: 1, T.CHANGED: 1, T.ONLY_LEFT: 1, T.ONLY_RIGHT: 1}


def test_no_unique_column_matches_by_position():
    left = T.parse("a,b\n1,x\n1,x\n")
    right = T.parse("a,b\n1,x\n1,z\n")
    result = T.compare(left, right)
    assert result.key == T.POSITION
    assert [r.status for r in result.rows] == [T.SAME, T.CHANGED]


def test_delimiters_quotes_and_numbers():
    left = T.parse('id;name;qty\n1;"a;b";1.50\n')
    right = T.parse('id;name;qty\n1;"a;b";1.5\n')
    assert left.delimiter == ";" and left.rows[0][1] == "a;b"
    assert T.compare(left, right).rows[0].status == T.SAME
    strict = T.compare(left, right, T.Options(numeric=False))
    assert strict.rows[0].status == T.CHANGED


def test_an_inserted_right_row_sits_where_it_was_inserted():
    left = T.parse("k\na\nb\nc\n")
    right = T.parse("k\na\nx\nb\nc\n")
    result = T.compare(left, right)
    order = [result.cell(r, 0, 0) or result.cell(r, 0, 1) for r in result.rows]
    assert order == ["a", "x", "b", "c"]


def test_a_csv_pair_opens_as_a_table(qt_app, tmp_path):
    import time

    from PySide6.QtCore import QCoreApplication

    from app import cli
    from app.core.config import Config
    from app.ui.window import MainWindow

    (tmp_path / "a.csv").write_text("Tag,Value\nA,1\nB,2\n")
    (tmp_path / "b.csv").write_text("Tag,Value\nB,3\nA,1\nC,4\n")
    window = MainWindow(Config(path=str(tmp_path / "c.json")), look={}, look_source="own",
                        custom_frame=False)
    window.open_request(cli.parse([str(tmp_path / "a.csv"), str(tmp_path / "b.csv")]))
    tab = window.pages.currentWidget()
    end = time.monotonic() + 10
    while tab.table.model.result is None and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert tab.stack.currentWidget() is tab.table
    result = tab.table.model.result
    assert result.counts[T.CHANGED] == 1 and result.counts[T.ONLY_RIGHT] == 1
    assert "2 records differ" in tab.count.text()
    tab.set_mode("text")
    assert tab.stack.currentWidget() is tab.view
    window._may_close = lambda pages: True
    window.close()
