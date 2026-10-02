"""L5K exports by structure (1.7): the same treatment as L5X, read from the
text form."""

import os
import time


from app.core import formats
from app.core.diff import align
from app.core.formats import l5k

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "l5k")


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as handle:
        return handle.read()


def differences(a, b):
    result = align.compare(a.lines, b.lines)
    out = []
    for block in result.differences:
        crumbs = [b.crumbs[j] if j != align.NONE else a.crumbs[i]
                  for i, j, _k in result.rows[block.start:block.end]]
        out.append(crumbs[0])
    return out


def test_detected_and_on_by_default():
    assert formats.detect("a.L5K", "b.l5k") == "l5k"
    assert "l5k" in formats.DEFAULT_ON


def test_only_the_real_changes_are_left():
    a, b = l5k.normalise(read("left.L5K")), l5k.normalise(read("right.L5K"))
    found = differences(a, b)
    # The export date, LastModifiedDate, a reordered routine and a reordered
    # controller tag are all gone; what is left names itself.
    assert found == [
        "Module IO_Rack1",                          # Minor 1 -> 3
        "Module IO_Rack1",                          # configuration data
        "Program MainProgram / Run_Timer",          # preset 5000 -> 8000
        "Program MainProgram / MainRoutine / Rung 0",   # a rung inserted
        "Program MainProgram / Speeds / Line 1",    # ST: 1.5 -> 1.8
        "Task MainTask",                            # watchdog
    ]


def test_an_inserted_rung_does_not_renumber_the_rest():
    a, b = l5k.normalise(read("left.L5K")), l5k.normalise(read("right.L5K"))
    rungs_a = [l for l in a.lines if l.strip().startswith("Rung:")]
    rungs_b = [l for l in b.lines if l.strip().startswith("Rung:")]
    assert rungs_a[-1] == rungs_b[-1]


def test_rung_comments_and_attributes():
    out = l5k.normalise(read("left.L5K"))
    text = "\n".join(out.lines)
    assert "// Start the conveyor" in text and "// Stop wins over start" in text
    assert "  Watchdog = 500" in text
    assert "LastModifiedDate" not in text and "Exported" not in text
    assert "Runs MainProgram" in text
    assert len(out.lines) == len(out.crumbs)


def test_statements_spread_over_lines_are_joined():
    text = ("CONTROLLER C (ProcessorType := \"x\")\n PROGRAM P (MAIN := \"R\")\n"
            "  ROUTINE R\n   N: XIC(a)\n      OTE(b);\n   RC: \"long $\n comment\";\n"
            "   N: NOP();\n  END_ROUTINE\n END_PROGRAM\nEND_CONTROLLER\n")
    out = l5k.normalise(text)
    assert "    Rung: XIC(a) OTE(b);" in out.lines
    assert any("long" in line and line.strip().startswith("//") for line in out.lines)


def test_a_missing_semicolon_stops_at_the_end_of_its_block():
    text = ("CONTROLLER C\n TAG\n  A : DINT\n END_TAG\n TAG\n  B : DINT;\n END_TAG\n"
            "END_CONTROLLER\n")
    out = l5k.normalise(text)
    assert "Tag A : DINT" in out.lines and "Tag B : DINT" in out.lines


def test_long_values_are_wrapped_and_module_data_digested():
    values = ",".join(str(n) for n in range(200))
    text = (f"CONTROLLER C\n MODULE M (Major := 1)\n  ConfigData := [{values}];\n"
            f" END_MODULE\n TAG\n  Big : DINT[200] := [{values}];\n END_TAG\nEND_CONTROLLER\n")
    out = l5k.normalise(text)
    assert any(line.strip().startswith("ConfigData ") and len(line) < 40 for line in out.lines)
    assert "Tag Big : DINT[200] =" in out.lines
    assert max(len(line) for line in out.lines) < 120


def test_not_an_l5k_falls_back_to_text():
    out = formats.normalise("l5k", ["just some text", "nothing here"])
    assert out.problem and out.lines == ["just some text", "nothing here"]


def test_the_session_compares_an_l5k_by_structure(qt_app):
    from PySide6.QtCore import QCoreApplication

    from app.core import session as core
    from app.core.loader import Loader
    from app.core.session import Options, Session

    loader = Loader()
    s = Session(loader, os.path.join(HERE, "left.L5K"), os.path.join(HERE, "right.L5K"),
                options=Options(poll=False))
    s.start()
    end = time.monotonic() + 10
    while s.kind != core.TEXT and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert s.structure and len(s.result.differences) == 6
    s.set_structure(False)
    assert len(s.result.differences) > 6
