"""XML by structure: attribute order and insignificant whitespace ignored.

Each element becomes one line, `<Tag a="1" b="2">`, with its attributes in
name order and its text on the same line when the text is a single short
line, or on the lines under it when not. Children follow, indented. There are
no closing tags: the indentation already says where an element ends, and a
column of `</Tag>` lines is a column of lines that match each other and
anchor the diff to nothing.

Element order is kept. In XML it usually means something -- the order of
steps, of rungs, of list items -- and a comparer that sorted it would call two
different files the same. Comments and processing instructions are dropped by
the parser, and the ignored-line says so.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from typing import Callable, Iterable

from app.core.formats import Formatted

#: A text longer than this is put on its own lines under the element.
INLINE = 80

_NS = re.compile(r"^\{[^}]*\}")
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)


def parse(text: str) -> ElementTree.Element:
    # The declaration names an encoding the text has already been decoded
    # from; ElementTree refuses a str that still carries one.
    return ElementTree.fromstring(_DECL.sub("", text, count=1).lstrip("﻿"))


def local(tag: str) -> str:
    return _NS.sub("", tag) if isinstance(tag, str) else str(tag)


def label(element: ElementTree.Element) -> str:
    """How a crumb names an element: its tag, and its name if it has one."""
    name = element.attrib.get("Name") or element.attrib.get("name") or \
        element.attrib.get("id") or element.attrib.get("Id") or ""
    tag = local(element.tag)
    return f"{tag} {name}" if name else tag


def opening(element: ElementTree.Element, ignore: Iterable[str] = ()) -> str:
    skip = set(ignore)
    attrs = sorted((local(k), v) for k, v in element.attrib.items() if local(k) not in skip)
    inner = " ".join(f'{k}="{v}"' for k, v in attrs)
    return f"<{local(element.tag)}{' ' + inner if inner else ''}>"


def text_lines(text: str | None) -> list[str]:
    if not text or not text.strip():
        return []
    lines = [line.rstrip() for line in text.strip("\n").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    # Common indentation removed, so re-indenting a block is not a difference.
    widths = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(widths) if widths else 0
    return [l[cut:] for l in lines]


def render(element: ElementTree.Element, out: Formatted, *, depth: int = 0,
           crumb: str = "", ignore: Iterable[str] = (),
           order: Callable[[ElementTree.Element, list], list] | None = None) -> None:
    """Append `element` and everything under it to `out`."""
    pad = "  " * depth
    here = f"{crumb} / {label(element)}" if crumb else label(element)
    head = opening(element, ignore)
    body = text_lines(element.text)
    children = list(element)
    if order is not None:
        children = order(element, children)
    if len(body) == 1 and len(body[0]) <= INLINE and not children:
        out.lines.append(f"{pad}{head}{body[0]}")
        out.crumbs.append(here)
    else:
        out.lines.append(pad + head)
        out.crumbs.append(here)
        for line in body:
            out.lines.append(f"{pad}  {line}")
            out.crumbs.append(here)
    for child in children:
        render(child, out, depth=depth + 1, crumb=here, ignore=ignore, order=order)
        tail = text_lines(child.tail)
        for line in tail:
            out.lines.append(f"{pad}  {line}")
            out.crumbs.append(here)


def normalise(text: str) -> Formatted:
    out = Formatted(ignored="attribute order, whitespace between elements, comments")
    render(parse(text), out)
    return out
