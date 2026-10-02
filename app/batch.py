"""The report without the window (1.11): `FileCompare.exe A B --report out.html`.

For checks nobody sits and watches -- a scheduled task that compares the
plant's backup folder with the office copy every night, or the running
program against the last good export -- the comparison is run, a report is
written, and the exit code says what was found:

    0   the same (differences the rules look past do not count)
    1   different
    2   could not compare: a side missing, unreadable, or a bad command line

Two files make a text report: HTML by default, a unified patch when the
report's name ends in .patch or .diff. Two folders make a folder report: every
pair that differs, with sizes and times. A session file (1.10) in place of
the two paths uses that session's paths and rules; otherwise the rules are
the ones last set in Options, so a report says what the window would.

No Qt. This runs before the application is created and exits without
creating it, and it never hands over to a running window: a scheduled task
must get its own answer, not open a tab somewhere. Reading is direct rather
than through the loader, because nothing here has a window to keep
responsive -- and a dead share makes a report late, which a scheduled task
can live with, rather than a window frozen, which nobody can.
"""

from __future__ import annotations

import datetime as _dt
import html
import ntpath
import os
import posixpath
from dataclasses import replace

from app.core import folders, formats, savedsession
from app.core import report as text_report
from app.core.diff import align
from app.core.rules import Rules, comment_markers
from app.core.rules import from_config as rules_from_config

SAME, DIFFERENT, FAILED = 0, 1, 2


class Failed(Exception):
    pass


def run(request, config) -> int:
    """`request` from `cli.parse`, with `report` set. Returns the exit code.
    A failure still writes a report when it can, saying what went wrong, so
    the file a scheduled task leaves behind explains its own exit code."""
    target = request.report
    try:
        if request.error:
            raise Failed(request.error)
        left, right, rules, structure, folder = _setup(request, config)
        kind_left, kind_right = _kind(left), _kind(right)
        if kind_left == "folder" and kind_right == "folder":
            text, same = _folders(left, right, config, folder)
        elif kind_left == "file" and kind_right == "file":
            text, same = _files(left, right, rules, structure, target)
        else:
            missing = [p for p, k in ((left, kind_left), (right, kind_right)) if k == "missing"]
            if missing:
                raise Failed(f"Not found: {missing[0]}")
            raise Failed("One side is a folder and the other a file")
    except (Failed, OSError) as exc:
        reason = str(exc) if isinstance(exc, Failed) else (exc.strerror or str(exc))
        try:
            _write(target, _failure_page(reason))
        except OSError:
            pass
        return FAILED
    try:
        _write(target, text)
    except OSError:
        return FAILED
    return SAME if same else DIFFERENT


def _setup(request, config):
    paths = list(request.paths)
    rules = rules_from_config(config)
    structure = True
    folder: dict = {}
    if len(paths) == 1 and savedsession.is_session(paths[0]):
        from app.io import sessionfile

        try:
            saved = sessionfile.read(paths[0])
        except ValueError as exc:
            raise Failed(f"{_base(paths[0])}: {exc}") from None
        paths = [saved.left, saved.right]
        rules = saved.rules
        structure = saved.structure
        folder = {"mask": saved.folder_mask, "hour": saved.folder_hour,
                  "contents": saved.folder_by_content, "archives": saved.folder_archives}
    if len(paths) != 2 or not all(paths):
        raise Failed("A report needs two paths, or one session file")
    markers = comment_markers(paths[0]) or comment_markers(paths[1])
    return paths[0], paths[1], replace(rules, markers=markers), structure, folder


def _kind(path: str) -> str:
    from app.io import longpath

    real = longpath.api(path)
    if os.path.isdir(real):
        return "folder"
    if os.path.isfile(real):
        return "file"
    return "missing"


def _files(left: str, right: str, rules: Rules, structure: bool, target: str):
    from app.io.load import load

    sides = [load(left), load(right)]
    for side in sides:
        if not side.ok:
            raise Failed(f"{side.path}: {side.error}")
    names = (_base(left), _base(right))
    if any(side.binary for side in sides):
        same = sides[0].digest == sides[1].digest
        return _binary_page(names, sides, same), same
    lines = (sides[0].lines, sides[1].lines)
    note = ""
    kind = formats.detect(left, right)
    if structure and kind in formats.DEFAULT_ON:
        a, b = formats.normalise(kind, lines[0]), formats.normalise(kind, lines[1])
        if not (a.problem or b.problem):
            lines = (a.lines, b.lines)
            note = f"{formats.names()[kind]}: ignoring {a.ignored}"
    result = align.compare(lines[0], lines[1], rules)
    if target.lower().endswith((".patch", ".diff")):
        text = text_report.unified(result, lines[0], lines[1], names)
    else:
        text = text_report.html_report(result, lines[0], lines[1], names=names,
                                       rules=rules.describe(), note=note)
    return text, result.identical


def _folders(left: str, right: str, config, folder: dict):
    from app.io import walk

    def setting(key: str, name: str):
        value = folder.get(key)
        return config.get(name) if value is None else value

    mask_text = str(setting("mask", "folders.mask") or "")
    mask = folders.Mask.parse(mask_text)
    archives = bool(setting("archives", "folders.archives"))
    hour = bool(setting("hour", "folders.ignore_hour"))
    by_content = bool(setting("contents", "folders.by_content"))
    tree = folders.build(walk.walk(left, archives=archives), walk.walk(right, archives=archives),
                         mask=mask, hour=hour)
    # A report is read later by somebody who cannot ask, so the pairs size
    # and time cannot settle are always read; with "always compare
    # contents", every same-size pair is.
    nodes = [n for n in tree.walk() if n.pair and not n.member
             and n.left.size == n.right.size
             and (by_content or n.status in (folders.NEWER_LEFT, folders.NEWER_RIGHT,
                                             folders.HOUR_APART))]
    joined = [(i, _join(left, n.rel), _join(right, n.rel)) for i, n in enumerate(nodes)]
    for key, same, error in walk.compare_contents(joined):
        folders.settle(nodes[key], same, error)
    differing = [n for n in tree.walk() if n.differs and not n.is_dir
                 or n.is_dir and n.status in (folders.ONLY_LEFT, folders.ONLY_RIGHT,
                                              folders.CLASH, folders.ERROR)]
    page = _folder_page((left, right), tree, differing, mask_text, hour)
    return page, not any(n.differs for n in tree.walk() if not n.member)


# ------------------------------------------------------------------- pages

#: The folder report's own table: a list of paths with a few short columns,
#: where the text report's is two halves of a file side by side. The page
#: around it is the text report's, so both read as one tool's output.
STYLE = text_report.STYLE + """
table.f { table-layout: auto; }
table.f td { font: 12px/1.5 "Segoe UI", system-ui, sans-serif; white-space: nowrap;
             word-break: normal; padding: 3px 10px; border-left: none;
             border-bottom: 1px solid #eceef2; }
table.f td.p { font-family: Consolas, "Cascadia Mono", monospace; white-space: pre-wrap;
               word-break: break-all; }
table.f th { padding: 6px 10px; }
table.f tr.chg td.w { color: #9a6a00; } table.f tr.del td.w { color: #b3261e; }
table.f tr.ins td.w { color: #1e7a4c; } table.f tr.fail td { color: #b3261e; }
table.f span.inside { color: #7b838f; }
"""


def _when(mtime: float) -> str:
    if not mtime:
        return ""
    try:
        return _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _folder_page(roots: tuple[str, str], tree, rows, mask: str, hour: bool) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    esc = html.escape
    notes = [f"names: {mask}" if mask else "all names",
             "an hour apart counts as the same" if hour else "an hour apart counts as newer"]
    out = [
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        f"<title>{esc(_base(roots[0]))} vs {esc(_base(roots[1]))}</title>",
        f"<style>{STYLE}</style></head><body>",
        f"<h1>{esc(roots[0])} &nbsp;vs&nbsp; {esc(roots[1])}</h1>",
        f"<div class=\"meta\">{esc(folders.summary(tree))}<br>{esc('; '.join(notes))}"
        f"<br>File Compare, {now}</div>",
        "<table class=\"f\"><tr><th>Path</th><th>What</th><th>Left size</th><th>Left time</th>"
        "<th>Right size</th><th>Right time</th></tr>",
    ]
    for node in rows:
        klass = {folders.ONLY_LEFT: "del", folders.ONLY_RIGHT: "ins",
                 folders.ERROR: "fail"}.get(node.status, "chg")
        cells = []
        for entry in (node.left, node.right):
            if entry is None:
                cells.append("<td class=\"fill\"></td><td class=\"fill\"></td>")
            elif entry.is_dir:
                cells.append("<td>folder</td><td></td>")
            else:
                cells.append(f"<td>{entry.size:,} B</td><td>{_when(entry.mtime)}</td>")
        label = folders.LABELS.get(node.status, node.status)
        error = (node.left and node.left.error) or (node.right and node.right.error) or ""
        if error:
            label += f": {error}"
        where = " <span class=\"inside\">(inside the zip)</span>" if node.member else ""
        out.append(f"<tr class=\"{klass}\"><td class=\"p\">{esc(node.rel)}</td>"
                   f"<td class=\"w\">{esc(label)}{where}</td>{''.join(cells)}</tr>")
    if not rows:
        out.append("<tr><td colspan=\"6\">No differences.</td></tr>")
    out.append("</table></body></html>")
    return "\n".join(out)


def _binary_page(names, sides, same: bool) -> str:
    esc = html.escape
    verdict = "Identical, byte for byte" if same else "The files differ"
    return "\n".join([
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        f"<title>{esc(names[0])} vs {esc(names[1])}</title>",
        f"<style>{STYLE}</style></head><body>",
        f"<h1>{esc(names[0])} &nbsp;vs&nbsp; {esc(names[1])}</h1>",
        f"<div class=\"meta\">{verdict}. Binary files: compared as bytes.<br>"
        f"{sides[0].size:,} and {sides[1].size:,} bytes</div>",
        "</body></html>"])


def _failure_page(reason: str) -> str:
    esc = html.escape
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return "\n".join([
        "<!doctype html><html><head><meta charset=\"utf-8\">",
        "<title>Comparison failed</title>",
        f"<style>{STYLE}</style></head><body>",
        "<h1>Could not compare</h1>",
        f"<div class=\"meta\">{esc(reason)}<br>File Compare, {now}</div>",
        "</body></html>"])


def _write(target: str, text: str) -> None:
    from app.io import save as io_save

    result = io_save.save(target, text.encode("utf-8"))
    if not result.ok:
        raise OSError(result.error)


def _base(path: str) -> str:
    path = path.rstrip("\\/")
    return (ntpath.basename(path) if "\\" in path else posixpath.basename(path)) or path


def _join(root: str, rel: str) -> str:
    if "\\" not in root and root.startswith("/"):
        return posixpath.join(root, rel.replace("\\", "/"))
    if len(root) == 2 and root[1] == ":":
        root += "\\"            # `D:` alone is drive-relative
    return ntpath.join(root, rel)
