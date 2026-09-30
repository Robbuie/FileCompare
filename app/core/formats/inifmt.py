"""INI by structure: sections and keys in name order, comments and spacing
ignored.

`configparser` is not used: it lowercases keys, refuses duplicate keys and
sections, and interprets `%` -- all of which change what a Windows INI file
says. This reads it the way Windows' own profile functions do: `[Section]`
lines, `key=value` lines, `;` and `#` comments, anything else kept as it is.

Key names compare without case (Windows' do); values compare exactly. A key
that appears twice in a section keeps both lines, in their order, since which
one wins depends on the program reading it. Lines before the first section
stay first.
"""

from __future__ import annotations

import re

from app.core.formats import Formatted

_SECTION = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_KEY = re.compile(r"^\s*([^=]+?)\s*=\s*(.*?)\s*$")


def normalise(lines: list[str]) -> Formatted:
    sections: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    order: list[str] = []
    current = ""
    sections[""] = ("", [])
    for raw in lines:
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        match = _SECTION.match(line)
        if match:
            name = match.group(1).strip()
            current = name.lower()
            if current not in sections:
                sections[current] = (name, [])
                order.append(current)
            continue
        match = _KEY.match(line)
        if match:
            sections[current][1].append((match.group(1), match.group(2)))
        else:
            sections[current][1].append((line, None))
    out = Formatted(ignored="section and key order, comments, spacing")
    for key in [""] + sorted(order):
        name, entries = sections[key]
        if key:
            out.lines.append(f"[{name}]")
            out.crumbs.append(f"[{name}]")
        entries = sorted(entries, key=lambda kv: kv[0].lower())
        for k, v in entries:
            out.lines.append(f"{k} = {v}" if v is not None else k)
            out.crumbs.append(f"[{name}] {k}" if key else k)
    return out
