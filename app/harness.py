"""The engine without a window, for checking what it does to a real pair.

    python -m app.harness diff left.txt right.txt
    python -m app.harness diff a.log b.log --time
    python -m app.harness diff a.txt b.txt --whitespace all --case --blank
    python -m app.harness load file.txt

`diff` prints each difference with its row numbers and a few lines of context,
side by side, and the counts. `load` prints what the reader decided about a
file -- encoding, mark, line endings -- which is the first thing to check when
a save or a compare looks wrong. Both use the application's own code paths;
nothing here is a second implementation.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.core.diff import align
from app.core.rules import WHITESPACE, Rules
from app.io.load import load

MARKS = {align.EQUAL: " ", align.CHANGED: "~", align.DELETED: "<",
         align.INSERTED: ">", align.IGNORED: "."}


def _diff(args: argparse.Namespace) -> int:
    began = time.perf_counter()
    left = load(args.left)
    right = load(args.right)
    read = time.perf_counter() - began
    for side in (left, right):
        if not side.ok:
            print(f"{side.path}: {side.error}")
            return 2
        if side.binary:
            print(f"{side.path}: binary")
            return 2
    rules = Rules(whitespace=args.whitespace, case=args.case, blank_lines=args.blank,
                  patterns=tuple(args.pattern or ()))
    result = align.compare(left.lines, right.lines, rules)
    width = args.width

    def cell(lines, index):
        text = "" if index == align.NONE else lines[index].expandtabs(4)
        return (text[:width - 1] + ">") if len(text) > width else text.ljust(width)

    if not args.time:
        for number, block in enumerate(result.blocks, start=1):
            if not block.significant and not args.ignored:
                continue
            first = max(0, block.start - args.context)
            last = min(len(result.rows), block.end + args.context)
            label = "ignored" if not block.significant else align.KIND_NAMES[block.kind]
            print(f"--- {number}: rows {block.start + 1}-{block.end} ({label})")
            for row in range(first, last):
                i, j, kind = result.rows[row]
                ln = f"{i + 1:>6}" if i != align.NONE else "      "
                rn = f"{j + 1:>6}" if j != align.NONE else "      "
                print(f"{ln} {cell(left.lines, i)} {MARKS[kind]} {rn} {cell(right.lines, j)}")
    counts = result.counts()
    print(f"{len(result.differences)} differences; lines: "
          + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    print(f"left {left.facts}")
    print(f"right {right.facts}")
    print(f"read {read * 1000:.0f} ms, compared {result.elapsed * 1000:.0f} ms "
          f"({len(result.rows):,} rows)")
    return 0 if result.identical else 1


def _load(args: argparse.Namespace) -> int:
    loaded = load(args.path)
    if not loaded.ok:
        print(loaded.error)
        return 2
    print(loaded.facts)
    print(f"size {loaded.size:,} bytes, digest {loaded.digest}")
    if loaded.lossy:
        print("some bytes did not decode and were replaced; not editable as text")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.harness")
    sub = parser.add_subparsers(dest="command", required=True)
    diff = sub.add_parser("diff", help="compare two files and print the differences")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.add_argument("--whitespace", choices=WHITESPACE, default="none")
    diff.add_argument("--case", action="store_true", help="ignore case")
    diff.add_argument("--blank", action="store_true", help="ignore blank lines")
    diff.add_argument("--pattern", action="append", help="regex for unimportant text")
    diff.add_argument("--context", type=int, default=2)
    diff.add_argument("--width", type=int, default=50)
    diff.add_argument("--ignored", action="store_true", help="show ignored blocks too")
    diff.add_argument("--time", action="store_true", help="counts and timing only")
    diff.set_defaults(run=_diff)
    one = sub.add_parser("load", help="what the reader decides about one file")
    one.add_argument("path")
    one.set_defaults(run=_load)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
