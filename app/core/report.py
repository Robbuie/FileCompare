"""A comparison written down: an HTML report, or a unified patch.

The report is for somebody who does not have File Compare open -- attached to
an email, printed for a change review, kept with a job folder. It is one
self-contained HTML file: the two sides in two columns, only the differences
and a few lines around each, the same colours as the view, and a header with
the two paths, the time, and the rules that were in force. Nothing is linked,
nothing is loaded from anywhere.

The patch is `diff -u` format, for tools that read one.

Pure: a comparison in, text out. Writing it is `io/save.py`'s job.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import html

from app.core.diff import align

CONTEXT = 3

#: Fixed colours for the report, not tokens: the report is read in a browser
#: or on paper, away from whichever theme the window happened to be in, and
#: paper wants the light theme's washes.
STYLE = """
body { font: 13px/1.45 "Segoe UI", system-ui, sans-serif; color: #14181f; margin: 24px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.meta { color: #4a525e; margin-bottom: 16px; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
td { font: 12px/1.4 Consolas, "Cascadia Mono", monospace; white-space: pre-wrap;
     word-break: break-all; vertical-align: top; padding: 0 6px; border-left: 1px solid #e3e6eb; }
td.n { width: 44px; text-align: right; color: #7b838f; border-left: none; }
tr.gap td { background: #f1f2f5; color: #7b838f; text-align: center; padding: 2px; }
tr.chg td.t { background: #fdf1dc; } tr.del td.l { background: #fbe4e2; }
tr.ins td.r { background: #e2f6ec; } tr.ign td.t { color: #7b838f; }
td.fill { background: #f4f5f7; }
th { text-align: left; font-weight: 600; padding: 6px; border-bottom: 1px solid #d5d9e0; }
"""


def unified(result: align.Comparison, left: list[str], right: list[str],
            names: tuple[str, str]) -> str:
    return "\n".join(difflib.unified_diff(left, right, names[0], names[1], lineterm="",
                                          n=CONTEXT)) + "\n"


def html_report(result: align.Comparison, left: list[str], right: list[str], *,
                names: tuple[str, str], rules: str = "", note: str = "") -> str:
    counts = result.counts()
    summary = (f"{len(result.differences)} difference{'s' if len(result.differences) != 1 else ''}"
               f" &middot; {counts['changed']} changed &middot; {counts['deleted']} only left"
               f" &middot; {counts['inserted']} only right")
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        f"<title>{html.escape(names[0])} vs {html.escape(names[1])}</title>",
        f"<style>{STYLE}</style></head><body>",
        f"<h1>{html.escape(names[0])} &nbsp;vs&nbsp; {html.escape(names[1])}</h1>",
        f"<div class=\"meta\">{summary}<br>{html.escape(rules)}"
        f"{' &middot; ' + html.escape(note) if note else ''}<br>File Compare, {now}</div>",
        "<table><colgroup><col style=\"width:44px\"><col><col style=\"width:44px\"><col>"
        "</colgroup>",
        f"<tr><th></th><th>{html.escape(names[0])}</th><th></th>"
        f"<th>{html.escape(names[1])}</th></tr>",
    ]
    rows = result.rows
    shown = set()
    for block in result.blocks:
        for r in range(max(0, block.start - CONTEXT), min(len(rows), block.end + CONTEXT)):
            shown.add(r)
    last = -1
    for r in sorted(shown):
        if last >= 0 and r != last + 1:
            out.append("<tr class=\"gap\"><td colspan=\"4\">...</td></tr>")
        elif last < 0 and r > 0:
            out.append("<tr class=\"gap\"><td colspan=\"4\">...</td></tr>")
        last = r
        i, j, kind = rows[r]
        klass = {align.CHANGED: "chg", align.DELETED: "del", align.INSERTED: "ins",
                 align.IGNORED: "ign"}.get(kind, "")
        cells = []
        for index, lines, side in ((i, left, "l"), (j, right, "r")):
            if index == align.NONE:
                cells.append("<td class=\"n\"></td><td class=\"fill\"></td>")
            else:
                cells.append(f"<td class=\"n\">{index + 1}</td><td class=\"t {side}\">"
                             f"{html.escape(lines[index].expandtabs(4)) or '&nbsp;'}</td>")
        out.append(f"<tr class=\"{klass}\">{''.join(cells)}</tr>")
    if not result.blocks:
        out.append("<tr><td colspan=\"4\">No differences.</td></tr>")
    out.append("</table></body></html>")
    return "\n".join(out)
