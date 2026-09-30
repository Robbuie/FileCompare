"""JSON by structure: key order ignored, formatting ignored.

Written out one value per line with the keys of every object in sorted order,
so two files that say the same thing in a different order or a different
layout compare equal. Array order is kept -- in JSON it is meaning, not
layout. The crumb is the path to the value, `servers[2].port`.
"""

from __future__ import annotations

import json

from app.core.formats import Formatted


def normalise(text: str) -> Formatted:
    data = json.loads(text.lstrip("﻿"))
    out = Formatted(ignored="key order and layout")
    _emit(data, out, "", 0, "")
    return out


def _scalar(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _emit(value, out: Formatted, prefix: str, depth: int, path: str) -> None:
    pad = "  " * depth
    if isinstance(value, dict):
        if not value:
            out.lines.append(f"{pad}{prefix}{{}}")
            out.crumbs.append(path)
            return
        out.lines.append(f"{pad}{prefix}{{")
        out.crumbs.append(path)
        for key in sorted(value):
            child = f"{path}.{key}" if path else str(key)
            _emit(value[key], out, f"{json.dumps(key, ensure_ascii=False)}: ", depth + 1, child)
        out.lines.append(f"{pad}}}")
        out.crumbs.append(path)
    elif isinstance(value, list):
        if not value:
            out.lines.append(f"{pad}{prefix}[]")
            out.crumbs.append(path)
            return
        out.lines.append(f"{pad}{prefix}[")
        out.crumbs.append(path)
        for index, item in enumerate(value):
            _emit(item, out, "", depth + 1, f"{path}[{index}]")
        out.lines.append(f"{pad}]")
        out.crumbs.append(path)
    else:
        out.lines.append(f"{pad}{prefix}{_scalar(value)}")
        out.crumbs.append(path)
