"""Logix exports (.L5X) by structure, named by program, routine and rung.

A line diff of two exports of the same project is mostly noise. Logix writes
the export date on the root, stamps edit dates on routines and AOIs, may list
tags in a different order, and puts every rung inside several layers of XML.
A real change -- one contact on rung 12 of MainRoutine -- is somewhere in
that, and a line number tells nobody where.

So the export is rewritten as one line per thing a controls engineer would
name, in an order that does not depend on how Logix felt like listing it:

    Controller Line4  1756-L83E v33.11
    DataType UDT_Motor
      Member Run : BOOL
    Tag Speed : REAL = 1.5
    Program MainProgram  main MainRoutine
      Tag Local : DINT = 0
      Routine MainRoutine (RLL)
        Rung: XIC(Start)OTE(Motor);
          // Starts the motor
    Task MainTask  CONTINUOUS

Collections whose order means nothing -- data types, tags, programs,
routines, modules, AOIs, tasks -- are sorted by name. Order that means
something is kept: rungs, structured text lines, UDT members, AOI parameters.

**Rung numbers are in the crumb, not the line.** Inserting one rung near the
top renumbers every rung after it; with the number in the text, every one of
those rungs would be a difference. Without it, the diff shows the one inserted
rung, and the crumb beside the difference still says "Rung 13".

**Module configuration data** is a hex blob per module. It is shown as a short
hash, so a changed configuration is a one-line difference that says which
module, rather than forty lines of hex that say nothing.

Ignored, and said so: the export date and options, and the created/edited
dates and users that Logix stamps on routines, AOIs and the controller.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ElementTree

from app.core.formats import Formatted
from app.core.formats.xmlfmt import label, local, parse, render, text_lines

#: Attributes that change on every export or edit without the logic changing.
NOISE = frozenset({
    "ExportDate", "ExportOptions", "LastModifiedDate", "LastModifiedBy",
    "EditedDate", "EditedBy", "CreatedDate", "CreatedBy", "ProjectCreationDate",
    "LastModified", "SignatureTimestamp",
})

IGNORED = ("export date and options, created and edited dates and users; "
           "tags, programs, routines, modules and types sorted by name")

#: Containers whose children are sorted by name.
SORTED = frozenset({"DataTypes", "Modules", "AddOnInstructionDefinitions", "Tags",
                    "Programs", "Routines", "Tasks", "LocalTags"})


def normalise(text: str) -> Formatted:
    root = parse(text)
    if local(root.tag) != "RSLogix5000Content":
        raise ValueError("not a Logix export (no RSLogix5000Content)")
    out = Formatted(ignored=IGNORED)
    a = root.attrib
    head = f"Export {a.get('TargetType', '')} {a.get('TargetName', '')}".rstrip()
    if a.get("SoftwareRevision"):
        head += f"  software {a['SoftwareRevision']}"
    _line(out, 0, head, "Export")
    for child in root:
        if local(child.tag) == "Controller":
            _controller(child, out)
        else:
            render(child, out, depth=1, crumb="Export", ignore=NOISE, order=_order)
    return out


def _line(out: Formatted, depth: int, text: str, crumb: str) -> None:
    out.lines.append("  " * depth + text)
    out.crumbs.append(crumb)


def _order(parent: ElementTree.Element, children: list) -> list:
    if local(parent.tag) in SORTED:
        return sorted(children, key=lambda e: (e.attrib.get("Name") or "").lower())
    return children


def _described(element: ElementTree.Element, out: Formatted, depth: int, crumb: str) -> None:
    for child in element:
        if local(child.tag) == "Description":
            lines = text_lines(child.text) or [""]
            _line(out, depth, "Description: " + " / ".join(l.strip() for l in lines), crumb)


def _named(element: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return sorted(element.findall(tag), key=lambda e: (e.attrib.get("Name") or "").lower())


def _controller(controller: ElementTree.Element, out: Formatted) -> None:
    a = controller.attrib
    rev = a.get("MajorRev", "")
    if a.get("MinorRev"):
        rev += "." + a["MinorRev"]
    crumb = f"Controller {a.get('Name', '')}".rstrip()
    _line(out, 0, f"{crumb}  {a.get('ProcessorType', '')}{' v' + rev if rev else ''}".rstrip(),
          crumb)
    rest = {k: v for k, v in a.items() if k not in NOISE and k not in
            ("Name", "ProcessorType", "MajorRev", "MinorRev", "Use")}
    for key in sorted(rest):
        _line(out, 1, f"{key} = {rest[key]}", crumb)
    _described(controller, out, 1, crumb)
    handled = {"Description", "DataTypes", "Modules", "AddOnInstructionDefinitions",
               "Tags", "Programs", "Tasks"}
    for box in controller:
        tag = local(box.tag)
        if tag == "DataTypes":
            for item in _named(box, "DataType"):
                _datatype(item, out)
        elif tag == "Modules":
            for item in _named(box, "Module"):
                _module(item, out)
        elif tag == "AddOnInstructionDefinitions":
            for item in _named(box, "AddOnInstructionDefinition"):
                _aoi(item, out)
        elif tag == "Tags":
            for item in _named(box, "Tag"):
                _tag(item, out, 0, "Controller tags")
        elif tag == "Programs":
            for item in _named(box, "Program"):
                _program(item, out)
        elif tag == "Tasks":
            for item in _named(box, "Task"):
                _task(item, out)
        elif tag not in handled:
            render(box, out, depth=0, crumb=crumb, ignore=NOISE, order=_order)


def _datatype(element: ElementTree.Element, out: Formatted) -> None:
    a = element.attrib
    crumb = f"DataType {a.get('Name', '')}"
    extra = " ".join(v for v in (a.get("Family", ""), a.get("Class", "")) if v and v != "NoFamily")
    _line(out, 0, f"{crumb}{'  ' + extra if extra else ''}", crumb)
    _described(element, out, 1, crumb)
    for member in element.iter("Member"):
        m = member.attrib
        if m.get("Hidden") == "true":
            continue
        dims = f"[{m['Dimension']}]" if m.get("Dimension") not in (None, "", "0") else ""
        bits = f" bit {m['BitNumber']} of {m.get('Target', '')}" if m.get("BitNumber") else ""
        line = f"Member {m.get('Name', '')} : {m.get('DataType', '')}{dims}{bits}"
        if m.get("Radix") and m.get("Radix") != "NullType":
            line += f"  {m['Radix']}"
        if m.get("ExternalAccess"):
            line += f"  {m['ExternalAccess']}"
        _line(out, 1, line, f"{crumb} / {m.get('Name', '')}")
        _described(member, out, 2, f"{crumb} / {m.get('Name', '')}")


def _digest(text: str) -> str:
    return hashlib.sha1("".join(text.split()).encode("utf-8")).hexdigest()[:12]


def _module(element: ElementTree.Element, out: Formatted) -> None:
    a = element.attrib
    crumb = f"Module {a.get('Name', '')}"
    rev = a.get("Major", "")
    if a.get("Minor"):
        rev += "." + a["Minor"]
    line = f"{crumb} : {a.get('CatalogNumber', '')}"
    if rev:
        line += f" rev {rev}"
    if a.get("ParentModule") and a.get("ParentModule") != a.get("Name"):
        line += f"  in {a['ParentModule']} port {a.get('ParentModPortId', '')}"
    if a.get("Inhibited") == "true":
        line += "  inhibited"
    _line(out, 0, line, crumb)
    _described(element, out, 1, crumb)
    for port in element.iter("Port"):
        p = port.attrib
        if p.get("Address"):
            _line(out, 1, f"Port {p.get('Id', '')} {p.get('Type', '')} address {p['Address']}",
                  crumb)
    for key in element.iter("EKey"):
        _line(out, 1, f"Keying {key.attrib.get('State', '')}", crumb)
    for connection in element.iter("Connection"):
        c = connection.attrib
        if c.get("RPI"):
            _line(out, 1, f"Connection {c.get('Name', '')} RPI {int(c['RPI']) / 1000:g} ms "
                          f"{c.get('Type', '')}".rstrip(), crumb)
    blobs = [d for d in element.iter() if local(d.tag) in ("ConfigData", "ConfigScript", "Data")
             and (d.text or "").strip()]
    if blobs:
        joined = "".join((d.text or "") for d in blobs)
        _line(out, 1, f"Configuration data {_digest(joined)}", crumb)


def _tag(element: ElementTree.Element, out: Formatted, depth: int, crumb: str) -> None:
    a = element.attrib
    name = a.get("Name", "")
    here = f"{crumb} / {name}" if crumb else name
    if a.get("TagType") == "Alias":
        _line(out, depth, f"Tag {name} -> {a.get('AliasFor', '')}", here)
    else:
        dims = f"[{a['Dimensions']}]" if a.get("Dimensions") else ""
        line = f"Tag {name} : {a.get('DataType', '')}{dims}"
        if a.get("Usage"):
            line += f"  {a['Usage']}"
        if a.get("Constant") == "true":
            line += "  constant"
        if a.get("ExternalAccess") and a.get("ExternalAccess") != "Read/Write":
            line += f"  {a['ExternalAccess']}"
        value = _value(element)
        if value is not None:
            if len(value) <= 120:
                line += f" = {value}"
                _line(out, depth, line, here)
            else:
                _line(out, depth, line, here)
                for start in range(0, len(value), 100):
                    _line(out, depth + 2, value[start:start + 100], here)
        else:
            _line(out, depth, line, here)
    _described(element, out, depth + 1, here)
    for comment in element.iter("Comment"):
        operand = comment.attrib.get("Operand", "")
        lines = text_lines(comment.text) or [""]
        _line(out, depth + 1, f"Comment {operand}: " + " / ".join(l.strip() for l in lines), here)


def _value(tag: ElementTree.Element) -> str | None:
    """The tag's value in its compact L5K form, when the export carries one."""
    for data in tag.findall("Data"):
        if data.attrib.get("Format") == "L5K" and (data.text or "").strip():
            return " ".join((data.text or "").split())
    for data in tag.findall("Data"):
        if data.attrib.get("Format") == "Decorated":
            values = [v.attrib.get("Value", "") for v in data.iter() if "Value" in v.attrib]
            if values:
                return ", ".join(values)
    return None


def _aoi(element: ElementTree.Element, out: Formatted) -> None:
    a = element.attrib
    crumb = f"AOI {a.get('Name', '')}"
    line = crumb
    if a.get("Revision"):
        line += f" rev {a['Revision']}"
    _line(out, 0, line, crumb)
    _described(element, out, 1, crumb)
    for parameter in element.iter("Parameter"):
        p = parameter.attrib
        text = f"Parameter {p.get('Name', '')} : {p.get('DataType', '')}  {p.get('Usage', '')}"
        if p.get("Required") == "true":
            text += "  required"
        if p.get("Visible") == "true":
            text += "  visible"
        _line(out, 1, text.rstrip(), f"{crumb} / {p.get('Name', '')}")
        _described(parameter, out, 2, f"{crumb} / {p.get('Name', '')}")
    for box in element.findall("LocalTags"):
        for tag in _named(box, "LocalTag"):
            _tag(tag, out, 1, f"{crumb} / local")
    for box in element.findall("Routines"):
        for routine in _named(box, "Routine"):
            _routine(routine, out, 1, crumb)


def _program(element: ElementTree.Element, out: Formatted) -> None:
    a = element.attrib
    crumb = f"Program {a.get('Name', '')}"
    line = crumb
    if a.get("MainRoutineName"):
        line += f"  main {a['MainRoutineName']}"
    if a.get("FaultRoutineName"):
        line += f"  fault {a['FaultRoutineName']}"
    if a.get("Disabled") == "true":
        line += "  disabled"
    if a.get("Class") and a.get("Class") != "Standard":
        line += f"  {a['Class']}"
    _line(out, 0, line, crumb)
    _described(element, out, 1, crumb)
    for box in element.findall("Tags"):
        for tag in _named(box, "Tag"):
            _tag(tag, out, 1, crumb)
    for box in element.findall("Routines"):
        for routine in _named(box, "Routine"):
            _routine(routine, out, 1, crumb)


def _routine(element: ElementTree.Element, out: Formatted, depth: int, parent: str) -> None:
    a = element.attrib
    crumb = f"{parent} / {a.get('Name', '')}"
    _line(out, depth, f"Routine {a.get('Name', '')} ({a.get('Type', '')})", crumb)
    _described(element, out, depth + 1, crumb)
    for content in element:
        tag = local(content.tag)
        if tag == "RLLContent":
            for rung in content.findall("Rung"):
                number = rung.attrib.get("Number", "")
                here = f"{crumb} / Rung {number}"
                text = " ".join(" ".join(text_lines(t.text)) for t in rung.findall("Text"))
                kind = rung.attrib.get("Type", "N")
                prefix = "Rung" if kind == "N" else f"Rung ({kind})"
                _line(out, depth + 1, f"{prefix}: {text}", here)
                for comment in rung.findall("Comment"):
                    for line in text_lines(comment.text):
                        _line(out, depth + 2, f"// {line.strip()}", here)
        elif tag == "STContent":
            for number, line in enumerate(content.findall("Line")):
                here = f"{crumb} / Line {line.attrib.get('Number', number)}"
                body = " ".join(text_lines(line.text))
                _line(out, depth + 1, body, here)
        elif tag != "Description":
            render(content, out, depth=depth + 1, crumb=crumb, ignore=NOISE | {"X", "Y"},
                   order=_order)


def _task(element: ElementTree.Element, out: Formatted) -> None:
    a = element.attrib
    crumb = f"Task {a.get('Name', '')}"
    line = f"{crumb}  {a.get('Type', '')}"
    if a.get("Rate"):
        line += f" every {a['Rate']} ms"
    if a.get("Priority"):
        line += f"  priority {a['Priority']}"
    if a.get("Watchdog"):
        line += f"  watchdog {a['Watchdog']} ms"
    if a.get("InhibitTask") == "true":
        line += "  inhibited"
    _line(out, 0, line, crumb)
    _described(element, out, 1, crumb)
    for scheduled in element.iter("ScheduledProgram"):
        _line(out, 1, f"Runs {scheduled.attrib.get('Name', '')}", crumb)


__all__ = ["normalise", "label"]
