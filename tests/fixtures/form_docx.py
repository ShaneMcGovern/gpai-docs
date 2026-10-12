"""Synthetic Form packages for the DOCX I/O tests.

Every call writes a minimal WordprocessingML package (``[Content_Types].xml``,
``_rels/.rels`` and ``word/document.xml``) whose document part mirrors the
published Model Documentation Form; the constructs it builds are the structure
note's (docs/form-docx-structure.md).
The packages are byte-stable (fixed member timestamps, uncompressed members),
built in-test, and never read from a binary.

A row is a label cell, a response area (option checks, static description,
then the response field) and the three audience columns in the form's order;
:class:`Row` documents the knobs.
"""

from __future__ import annotations

import struct
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

__all__ = [
    "AUDIENCE_KEYS",
    "RESPONSE_ALIAS",
    "Row",
    "write_form_docx",
    "write_package",
]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14 = "http://schemas.microsoft.com/office/word/2010/wordml"

# The serialized prefixes are the Form's own, so the built part reads like the
# part the reader meets.
ET.register_namespace("w", _W)
ET.register_namespace("w14", _W14)

_P = f"{{{_W}}}p"
_P_PR = f"{{{_W}}}pPr"
_P_STYLE = f"{{{_W}}}pStyle"
_R = f"{{{_W}}}r"
_R_PR = f"{{{_W}}}rPr"
_R_STYLE = f"{{{_W}}}rStyle"
_COLOR = f"{{{_W}}}color"
_T = f"{{{_W}}}t"
_TC = f"{{{_W}}}tc"
_TR = f"{{{_W}}}tr"
_TR_PR = f"{{{_W}}}trPr"
_TBL = f"{{{_W}}}tbl"
_TBL_PR = f"{{{_W}}}tblPr"
_TBL_GRID = f"{{{_W}}}tblGrid"
_TC_PR = f"{{{_W}}}tcPr"
_GRID_SPAN = f"{{{_W}}}gridSpan"
_SDT = f"{{{_W}}}sdt"
_SDT_PR = f"{{{_W}}}sdtPr"
_SDT_CONTENT = f"{{{_W}}}sdtContent"
_SHOWING_PLC_HDR = f"{{{_W}}}showingPlcHdr"
_ALIAS = f"{{{_W}}}alias"
_TAG = f"{{{_W}}}tag"
_VAL = f"{{{_W}}}val"
_W14_CHECKBOX = f"{{{_W14}}}checkbox"
_W14_CHECKED = f"{{{_W14}}}checked"
_W14_VAL = f"{{{_W14}}}val"

# The form's own audience column order; a row's crosses use these keys.
AUDIENCE_KEYS = ("ai_office", "nca", "downstream")
# The alias the form puts on its response fields (structure note).
RESPONSE_ALIAS = "Replace this with your response..."

_AUDIENCE_HEADERS = ("AIO", "NCAs", "DPs")
_GLYPHS = {True: "☒", False: "☐"}

_DOCUMENT_XML = "word/document.xml"
_CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    "<Types xmlns="
    '"http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType='
    '"application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType='
    '"application/vnd.openxmlformats-officedocument.wordprocessingml.'
    'document.main+xml"/>'
    "</Types>"
)
_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    "<Relationships xmlns="
    '"http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)


@dataclass
class Row:
    """One synthetic form row (see the module docstring for the model).

    ``label`` (or ``label_runs``, one paragraph of runs, or
    ``label_paragraphs``) fills the label cell; ``options`` writes tick
    controls with their printed labels; ``description`` writes static text in
    the response area; ``response`` (or ``response_runs``, or
    ``response_paragraphs``, one paragraph per entry) writes the response
    field. ``crosses`` maps an audience key to its state (``None`` inherits
    :func:`write_form_docx`'s ``crosses``); a key in ``silent`` writes an
    empty tick control, and a key missing from ``crosses`` leaves the column
    out. ``nested`` rows go into a nested table inside the response area's
    cell; a ``heading`` row is a section heading and ignores the other
    fields.

    The guidance-styling fields ``response_style``, ``response_color``,
    ``response_control_color``, ``response_plchdr``,
    ``response_paragraph_style`` and ``response_inline`` mirror the published
    form's shapes (structure note);
    ``label_tick`` adds a glyph-less tick control.

    ``extra_crosses`` writes a second tick control per audience cell (the
    split row's hidden pair) and ``split_responses`` builds the split row:
    one plain cell per entry, each carrying an inner response field, then
    ``response`` as a cell-wrapped field. ``options``/``description``/
    ``nested`` are ignored when ``split_responses`` is set.
    """

    label: str = ""
    label_runs: Sequence[str] | None = None
    label_paragraphs: Sequence[str] | None = None
    options: Sequence[tuple[bool, str]] = ()
    description: str = ""
    response: str = ""
    response_runs: Sequence[str] | None = None
    response_paragraphs: Sequence[str] | None = None
    response_style: str | None = None
    response_color: str | None = None
    response_control_color: str | None = None
    response_plchdr: bool = False
    response_paragraph_style: str | None = None
    response_inline: bool = False
    crosses: Mapping[str, bool] | None = None
    silent: Sequence[str] = ()
    extra_crosses: Mapping[str, bool] | None = None
    label_tick: bool | None = None
    split_responses: Sequence[str] | None = None
    nested: Sequence[Row] = field(default_factory=tuple)
    heading: str | None = None
    wrap_row: bool = False
    wrap_cells: bool = True


def write_form_docx(
    path: Path,
    rows: Sequence[Row],
    *,
    crosses: Mapping[str, bool] | None = None,
    extra: Mapping[str, str | bytes] | None = None,
    flag_bits: int = 0,
    external_attr: int = 0,
) -> Path:
    """Write a one-table synthetic Form package to ``path``.

    ``crosses`` is the audience state rows without their own inherit, so a
    test that cares only about labels can write ``Row(label=...)`` rows and
    pass the state once. ``extra`` lands as further package members, and
    ``flag_bits``/``external_attr`` stamp the members' headers (see
    :func:`write_package`).
    """
    body = ET.Element(f"{{{_W}}}body")
    table = ET.SubElement(body, _TBL)
    ET.SubElement(table, _TBL_PR)
    ET.SubElement(table, _TBL_GRID)
    for row in rows:
        table.append(_row_element(row, crosses if crosses is not None else {}))
    document = ET.Element(f"{{{_W}}}document")
    document.append(body)
    return write_package(
        path,
        _serialize(document),
        extra=extra,
        flag_bits=flag_bits,
        external_attr=external_attr,
    )


def write_package(
    path: Path,
    document_xml: str | bytes,
    *,
    extra: Mapping[str, str | bytes] | None = None,
    flag_bits: int = 0,
    external_attr: int = 0,
) -> Path:
    """Write the minimal package parts around ``document_xml`` to ``path``.

    Identical input yields identical bytes; ``extra`` members are written
    after the standard three, in its own order. ``flag_bits`` and
    ``external_attr`` are stamped on every member's headers after the write
    (structure note), since
    ``zipfile``'s writer computes its own flag bits and defaults the
    attributes.
    """
    members: dict[str, str | bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES_XML,
        "_rels/.rels": _RELS_XML,
        _DOCUMENT_XML: document_xml,
    }
    if extra is not None:
        members.update(extra)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as package:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            package.writestr(info, content)
    _stamp_headers(path, flag_bits=flag_bits, external_attr=external_attr)
    return path


def _stamp_headers(path: Path, *, flag_bits: int, external_attr: int) -> None:
    """Stamp every member's flag bits and external attributes.

    The mechanics are the structure note's to describe.
    """
    data = bytearray(path.read_bytes())
    offset = data.index(b"PK\x01\x02")
    while data[offset : offset + 4] == b"PK\x01\x02":
        (name_length,) = struct.unpack_from("<H", data, offset + 28)
        (extra_length, comment_length) = struct.unpack_from("<HH", data, offset + 30)
        (local,) = struct.unpack_from("<I", data, offset + 42)
        struct.pack_into("<H", data, offset + 8, flag_bits)
        struct.pack_into("<I", data, offset + 38, external_attr)
        struct.pack_into("<H", data, local + 6, flag_bits)
        offset += 46 + name_length + extra_length + comment_length
    path.write_bytes(bytes(data))


def _serialize(element: ET.Element) -> str:
    declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return declaration + ET.tostring(element, encoding="unicode")


def _row_element(row: Row, default_crosses: Mapping[str, bool]) -> ET.Element:
    if row.heading is not None:
        element = _heading_row(row.heading)
    else:
        element = _data_row(row, default_crosses)
    if row.wrap_row:
        return _sdt([element])
    return element


def _heading_row(heading: str) -> ET.Element:
    row = ET.Element(_TR)
    ET.SubElement(row, _TR_PR)
    cell = ET.SubElement(row, _TC)
    props = ET.SubElement(cell, _TC_PR)
    ET.SubElement(props, _GRID_SPAN, {_VAL: "2"})
    cell.append(_paragraph([heading]))
    for header in _AUDIENCE_HEADERS:
        row.append(_cell([_paragraph([header])]))
    return row


def _data_row(row: Row, default_crosses: Mapping[str, bool]) -> ET.Element:
    element = ET.Element(_TR)
    ET.SubElement(element, _TR_PR)
    element.append(_label_cell(row))
    if row.split_responses is not None:
        element.extend(_split_cells(row))
    else:
        element.append(_response_cell(row))
    crosses = row.crosses if row.crosses is not None else default_crosses
    for key in AUDIENCE_KEYS:
        element.append(
            _cross_cell(
                crosses, key, key in row.silent, row.wrap_cells, row.extra_crosses
            )
        )
    return element


def _split_cells(row: Row) -> list[ET.Element]:
    """The split row's response area: inner answer cells, then its own cell."""
    cells = [
        _cell([_sdt([_paragraph([text])], alias=RESPONSE_ALIAS)])
        for text in row.split_responses or ()
    ]
    cells.append(_sdt([_cell([_paragraph([row.response])])], alias=RESPONSE_ALIAS))
    return cells


def _label_cell(row: Row) -> ET.Element:
    paragraphs = _label_paragraphs(row)
    if row.label_tick is not None:
        tick = _sdt([_run([])], ticked=row.label_tick)
        paragraphs = [*paragraphs, _paragraph([], nested=[tick])]
    if row.wrap_cells:
        return _sdt([_cell(paragraphs)])
    return _cell(paragraphs)


def _label_paragraphs(row: Row) -> list[ET.Element]:
    if row.label_runs is not None:
        return [_paragraph(row.label_runs)]
    if row.label_paragraphs is not None:
        return [_paragraph([text]) for text in row.label_paragraphs]
    return [_paragraph([row.label])]


def _response_cell(row: Row) -> ET.Element:
    content = [_option_paragraph(ticked, text) for ticked, text in row.options]
    if row.description:
        content.append(_paragraph([row.description]))
    if row.nested:
        content.append(_nested_table(row.nested))
    control_color, plchdr = row.response_control_color, row.response_plchdr
    if row.response_inline:
        runs = list(row.response_runs or [row.response])
        if "".join(runs):
            control = _sdt(
                [
                    _run(
                        runs,
                        style=row.response_style,
                        color=row.response_color,
                    )
                ],
                alias=RESPONSE_ALIAS,
                control_color=control_color,
                plchdr=plchdr,
            )
            content.append(
                _paragraph(
                    [],
                    nested=[control],
                    paragraph_style=row.response_paragraph_style,
                )
            )
        return _cell(content)
    paragraphs = _response_paragraphs(row)
    if not paragraphs:
        return _cell(content)
    if row.wrap_cells and not content:
        return _sdt(
            [_cell(paragraphs)],
            alias=RESPONSE_ALIAS,
            control_color=control_color,
            plchdr=plchdr,
        )
    content.append(
        _sdt(
            paragraphs,
            alias=RESPONSE_ALIAS,
            control_color=control_color,
            plchdr=plchdr,
        )
    )
    return _cell(content)


def _response_paragraphs(row: Row) -> list[ET.Element]:
    """The response field's paragraphs; empty when the row carries no field."""
    style, color = row.response_style, row.response_color
    paragraph_style = row.response_paragraph_style
    if row.response_paragraphs is not None:
        return [
            _paragraph(
                [text], style=style, color=color, paragraph_style=paragraph_style
            )
            for text in row.response_paragraphs
        ]
    runs = list(row.response_runs) if row.response_runs is not None else [row.response]
    if not "".join(runs):
        return []
    return [_paragraph(runs, style=style, color=color, paragraph_style=paragraph_style)]


def _nested_table(rows: Sequence[Row]) -> ET.Element:
    table = ET.Element(_TBL)
    ET.SubElement(table, _TBL_PR)
    ET.SubElement(table, _TBL_GRID)
    for row in rows:
        table.append(_row_element(row, {}))
    return table


def _cross_cell(
    crosses: Mapping[str, bool],
    key: str,
    silent: bool,
    wrap_cells: bool,
    extra: Mapping[str, bool] | None = None,
) -> ET.Element:
    states = [crosses[key]] if key in crosses else []
    if extra is not None and key in extra:
        states.append(extra[key])
    if not states:
        return ET.Element(_TC)
    if extra is not None:
        # The split row's shape: two tick controls per cell, in reading order.
        controls = [_sdt([_run([_GLYPHS[state]])], ticked=state) for state in states]
        return _cell([_paragraph([], nested=controls)])
    ticked = states[0]
    runs = [] if silent else [_GLYPHS[ticked]]
    if wrap_cells:
        return _sdt([_cell([_paragraph(runs)])], ticked=ticked)
    control = _sdt([_run(runs)] if runs else [], ticked=ticked)
    return _cell([_paragraph([], nested=[control])])


def _option_paragraph(ticked: bool, text: str) -> ET.Element:
    control = _sdt([_run([_GLYPHS[ticked]])], ticked=ticked)
    label = _sdt([_run([text])])
    return _paragraph([], nested=[control, label])


def _cell(children: Sequence[ET.Element]) -> ET.Element:
    cell = ET.Element(_TC)
    cell.extend(children)
    return cell


def _paragraph(
    runs: Sequence[str],
    nested: Sequence[ET.Element] = (),
    style: str | None = None,
    color: str | None = None,
    paragraph_style: str | None = None,
) -> ET.Element:
    paragraph = ET.Element(_P)
    if paragraph_style is not None:
        props = ET.SubElement(paragraph, _P_PR)
        ET.SubElement(props, _P_STYLE, {_VAL: paragraph_style})
    for text in runs:
        paragraph.append(_run([text], style=style, color=color))
    for element in nested:
        paragraph.append(element)
    return paragraph


def _run(
    runs: Sequence[str], style: str | None = None, color: str | None = None
) -> ET.Element:
    run = ET.Element(_R)
    if style is not None or color is not None:
        props = ET.SubElement(run, _R_PR)
        if style is not None:
            ET.SubElement(props, _R_STYLE, {_VAL: style})
        if color is not None:
            ET.SubElement(props, _COLOR, {_VAL: color})
    for text in runs:
        ET.SubElement(run, _T).text = text
    return run


def _sdt(
    children: Sequence[ET.Element],
    alias: str | None = None,
    ticked: bool | None = None,
    control_color: str | None = None,
    plchdr: bool = False,
) -> ET.Element:
    """A content control: its properties carry the alias and/or tick state."""
    control = ET.Element(_SDT)
    props = ET.SubElement(control, _SDT_PR)
    if control_color is not None:
        rpr = ET.SubElement(props, _R_PR)
        ET.SubElement(rpr, _COLOR, {_VAL: control_color})
    if alias is not None:
        ET.SubElement(props, _ALIAS, {_VAL: alias})
        ET.SubElement(props, _TAG, {_VAL: alias})
    if plchdr:
        ET.SubElement(props, _SHOWING_PLC_HDR)
    if ticked is not None:
        checkbox = ET.SubElement(props, _W14_CHECKBOX)
        ET.SubElement(checkbox, _W14_CHECKED, {_W14_VAL: "1" if ticked else "0"})
    content = ET.SubElement(control, _SDT_CONTENT)
    content.extend(children)
    return control
