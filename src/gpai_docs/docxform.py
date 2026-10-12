"""The Form's WordprocessingML reader, mapping and writer.

`docs/form-docx-structure.md` is the structure note this reader follows: the
content controls, the split row, the checkbox states, the debris rules, and
the mapping and writing rules.
"""

from __future__ import annotations

import copy
import itertools
import math
import re
import struct
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast
from xml.etree import ElementTree as ET

from gpai_docs.registry import load

if TYPE_CHECKING:
    from gpai_docs.documents import Document
    from gpai_docs.registry import Registry
    from gpai_docs.registry.models import Field as FieldSpec
    from gpai_docs.registry.models import FormRow as FormRowSpec

__all__ = [
    "CellAnswer",
    "DocxError",
    "FormRow",
    "MappedSummary",
    "build_document",
    "count_duplicate_rows",
    "document_values_for_rows",
    "form_rows_for",
    "locate_rows",
    "read_rows",
    "summarise",
    "write_form",
]

_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
}
_W = _NAMESPACES["w"]
_W14 = _NAMESPACES["w14"]

_DOCUMENT_PART = "word/document.xml"

# The fixed member timestamp the write normalises to, so the same
# template bytes and values write byte-identical packages.
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_DECLARATION = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

# The characters an XML 1.0 part may carry; anything else (control characters,
# lone surrogates) would make the written part unparsable, so a value holding
# one is refused.
_UNWRITABLE_CHARS = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")

# The template's own root declarations; ElementTree renames unregistered
# prefixes, and the part's ``mc:Ignorable`` tokens name them, so the writer
# registers them before serialising (only root start tags are scanned).
_NAMESPACE_DECLARATION = re.compile(rb'xmlns:([A-Za-z_][\w.-]*)=["\']([^"\']+)["\']')

# The flag bits the writer's own layout decides, not the template's: the
# encryption and data-descriptor bits (members are written in the clear) and
# the UTF-8 filename bit (``zipfile`` sets it when the name needs it). Every
# other bit is the template's to keep.
_FLAG_WRITER_OWNS = 0x0001 | 0x0008 | 0x0800

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_TBL = f"{{{_W}}}tbl"
_TR = f"{{{_W}}}tr"
_TC = f"{{{_W}}}tc"
_TC_PR = f"{{{_W}}}tcPr"
_P_PR = f"{{{_W}}}pPr"
_GRID_SPAN = f"{{{_W}}}gridSpan"
_P = f"{{{_W}}}p"
_R = f"{{{_W}}}r"
_R_PR = f"{{{_W}}}rPr"
_R_STYLE = f"{{{_W}}}rStyle"
_COLOR = f"{{{_W}}}color"
_T = f"{{{_W}}}t"
_BR = f"{{{_W}}}br"
_CR = f"{{{_W}}}cr"
_SDT = f"{{{_W}}}sdt"
_SDT_PR = f"{{{_W}}}sdtPr"
_SDT_CONTENT = f"{{{_W}}}sdtContent"
_SHOWING_PLC_HDR = f"{{{_W}}}showingPlcHdr"
_ALIAS = f"{{{_W}}}alias"
_TAG = f"{{{_W}}}tag"
_VAL = f"{{{_W}}}val"
_W14_CHECKBOX = f"{{{_W14}}}checkbox"
_W14_CHECKED = f"{{{_W14}}}checked"
_W14_CHECKED_VAL = f"{{{_W14}}}val"

# The form's audience columns, in its own order; a key appears only where the
# row carries the control.
_AUDIENCE_KEYS = ("ai_office", "nca", "downstream")

# The two content-control roles the walk reads: a response control carries an
# alias or a tag; a tick control's state is its ``w14:checked``, not a glyph.
_TICK = "tick"
_RESPONSE = "response"

# The styles and colours the pinned Form renders its guidance in (structure
# note).
_GUIDANCE_STYLES = frozenset({"PlaceholderText", "Style2"})
_GUIDANCE_COLORS = frozenset({"808080", "7F7F7F", "939598", "0F4761"})

# The eight section headings the pinned Form prints, mapped to the section
# part of the registry's row ids (form.yaml): four ids are not derivable from
# their heading, so the map is explicit and keyed by the heading text.
_SECTION_BY_HEADING = {
    "General information": "general-information",
    "Model properties": "model-properties",
    "Methods of distribution and licenses": "distribution-and-licenses",
    "Use": "use",
    "Training process": "training-process",
    "Information on the data used for training, testing, and validation": (
        "data-used-for-training-testing-and-validation"
    ),
    "Computational resources (during training)": "computational-resources",
    "Energy consumption (during training and inference)": "energy-consumption",
}

# The running instruction the form appends to two labels; form.yaml's labels
# are the published text with it (and the trailing colon and stop) trimmed.
_LABEL_INSTRUCTION = re.compile(r"\s*Select all that apply\.?$")

# The rows whose answers are the two structured elements' leaves, keyed by the
# registry's row ids (a row no field draws on is absent). The
# ``type:compute`` and ``type:energy`` rule tags mark an element structured;
# this table is the row-level half.
_ROW_LEAVES = {
    "computational-resources/training-time": "training_time",
    "computational-resources/training-time-wall-clock-and-hardware-days": (
        "training_time"
    ),
    "computational-resources/amount-of-computation-used-for-training": (
        "training_flop"
    ),
    (
        "computational-resources/"
        "amount-of-computation-used-for-training-two-significant-figures"
    ): "training_flop",
    "computational-resources/measurement-methodology": "estimation_method",
    "energy-consumption/amount-of-energy-used-for-training": "training.amount",
    "energy-consumption/measurement-methodology-energy": "training.method",
    "energy-consumption/benchmarked-amount-of-computation-used-for-inference": (
        "inference.amount"
    ),
    "energy-consumption/measurement-methodology-inference": "inference.method",
}

# The leaves read as numbers when their text is exactly a numeric literal;
# every other leaf is text, verbatim.
_NUMERIC_LEAVES = frozenset({"training_flop", "training.amount", "inference.amount"})
_STRUCTURED_RULES = frozenset({"type:compute", "type:energy"})

# The YAML 1.2 core number spellings, exactly the registry reader's own
# (registry/__init__.py), so a value read here is one read back there.
_YAML12_INT = re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$")
_YAML12_FLOAT = re.compile(
    r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?)$"
)


class DocxError(Exception):
    """A Form package is unreadable or does not hold the document part."""


class CellAnswer(NamedTuple):
    """One response-area cell's answer text (the mapping layer's input).

    Exactly one half is non-empty: the split DOCX row's per-modality cells
    answer ``inner``, its last cell ``outer``.
    """

    outer: str
    inner: str


@dataclass
class FormRow:
    """One faithful structural row of the Form.

    ``label`` carries forward from the last row that had one; ``crosses``
    holds only the keys the row carries, and ``answers``/``cross_pairs`` are
    what the mapping layer reads instead (the first pair is ``crosses``).
    """

    section: str
    label: str
    response: str
    description: str
    crosses: dict[str, bool] = field(default_factory=dict)
    answers: tuple[CellAnswer, ...] = ()
    cross_pairs: tuple[dict[str, bool], ...] = ()


@dataclass(frozen=True)
class MappedSummary:
    """The import's counts for the stderr line.

    ``rows_skipped`` counts located rows no field draws on, and the counts
    are distinct rows, not row-field pairs; unmatched rows and debris are
    silent.
    """

    rows_mapped: int
    fields_written: int
    rows_skipped: int
    duplicate_rows: int = 0


class _Cell(NamedTuple):
    """One ``w:tc`` and the content control that wrapped it, if any."""

    element: ET.Element
    kind: str | None
    control: ET.Element | None


class _WalkedRow(NamedTuple):
    """One walked data row with the response-area cells it was read from.

    The writer targets a row's response field through the cells the reader
    read it from, so no second traversal can drift from the first.
    """

    row: FormRow
    area: tuple[_Cell, ...]


def read_rows(package_path: Path) -> list[FormRow]:
    """Read every data row of the Form package at ``package_path``.

    Headings and debris drop out; the rest is reported as it sits, in
    document order (a nested table's rows included).
    """
    return [walked.row for walked in _walk_rows(_document_tree(package_path))]


def _walk_rows(root: ET.Element) -> Iterator[_WalkedRow]:
    """Walk the parsed part's data rows: the reader's and the writer's one walk.

    The row geometry is the structure note's; every heading,
    carry-forward and debris rule lives here, beside the cells the writer
    needs.
    """
    section = ""
    label = ""
    for table in root.iter(_TBL):
        for row in _child_rows(table):
            cells = list(_child_cells(row))
            if not cells:
                continue
            if _is_heading(cells):
                section = _cell_texts(cells[0])[0]
                continue
            head, _ = _cell_texts(cells[0])
            area = cells[1:-3] if len(cells) > 3 else cells[1:]
            audience = cells[-3:] if len(cells) > 3 else []
            texts = [_cell_texts(cell) for cell in area]
            description = [static for static, _ in texts if static]
            response = [text for _, text in texts if text]
            cross_pairs = _cross_pairs(audience)
            if not head and not description and not response:
                continue
            if not head:
                head = label
            else:
                label = head
            yield _WalkedRow(
                row=FormRow(
                    section=section,
                    label=head,
                    response=" ".join(response),
                    description=" ".join(description),
                    crosses=cross_pairs[0] if cross_pairs else {},
                    answers=tuple(_cell_answers(cell) for cell in area),
                    cross_pairs=cross_pairs,
                ),
                area=tuple(area),
            )


def form_rows_for(label: str, registry: Registry) -> list[FormRowSpec]:
    """Every ``form.yaml`` row published under ``label``, in published order.

    Exact label equality; a repeated label returns every candidate, which the
    matcher disambiguates by section and crosses.
    """
    return [row for row in registry.form.rows if row.label == label]


class _Located(NamedTuple):
    """A located published row: the walked row's position and answer halves.

    ``outer`` takes the answers of the cell the row's own response control
    wraps, ``inner`` those inside its plain cells; the split row's halves
    differ, every other row takes both.
    """

    position: int
    outer: bool
    inner: bool


def locate_rows(walked: list[FormRow], registry: Registry) -> dict[str, str]:
    """Pair walked rows with the ``form.yaml`` inventory.

    Each published row, in published order, takes the next unconsumed walked
    row that matches it on section, label and crosses; the output-modalities
    row covers two published rows and is split by shape. A walked row that
    matches nothing is silent; every located row maps to its answer text,
    empty when the form carries none.
    """
    located, _ = _locate(walked, registry)
    return {
        row_id: _answer_text(
            walked[target.position], outer=target.outer, inner=target.inner
        )
        for row_id, target in located.items()
    }


def _locate(
    walked: list[FormRow], registry: Registry
) -> tuple[dict[str, _Located], set[int]]:
    """Locate the inventory, remembering which walked rows it consumed."""
    located: dict[str, _Located] = {}
    consumed: set[int] = set()
    for spec in registry.form.rows:
        if spec.row in located:
            continue
        for index, row in enumerate(walked):
            if index in consumed or not _same_section(row, spec):
                continue
            pair = _split_specs(row, registry)
            if pair is not None and spec.row in (pair[0].row, pair[1].row):
                first, second = pair
                located[first.row] = _Located(index, True, False)
                located[second.row] = _Located(index, False, True)
                consumed.add(index)
                break
            if _matches(row, spec):
                located[spec.row] = _Located(index, True, True)
                consumed.add(index)
                break
    return located, consumed


def count_duplicate_rows(walked: list[FormRow], registry: Registry) -> int:
    """How many walked rows repeat a shape an earlier row already answered.

    The predicate is :func:`_same_shape`, so a row matching nothing is no
    duplicate; the twins the inventory pairs in document order are consumed
    by their own published rows and are no duplicates either.
    """
    located, consumed = _locate(walked, registry)
    matched = [spec for spec in registry.form.rows if spec.row in located]
    duplicates = 0
    for index, row in enumerate(walked):
        if index in consumed:
            continue
        if any(_same_shape(row, spec) for spec in matched):
            duplicates += 1
            continue
        pair = _split_specs(row, registry)
        if pair is not None and pair[0].row in located:
            duplicates += 1
    return duplicates


def build_document(rows: Mapping[str, str], registry: Registry) -> dict[str, object]:
    """Build the native document from located answers.

    Every registry field, in registry order, takes the answers of its rows in
    the field's own row order, joined by a blank line and trimmed; empty
    fields and all-empty sections are absent. The two structured elements
    read numeric-literal amounts as numbers and everything else verbatim.
    """
    sections: dict[str, dict[str, object]] = {}
    for spec, value in _field_values(rows, registry):
        section, _, key = spec.model_field.partition(".")
        sections.setdefault(section, {})[key] = value
    return {"schema": 1, **sections}


def summarise(
    rows: Mapping[str, str], registry: Registry, *, duplicate_rows: int = 0
) -> MappedSummary:
    """The import's stderr counts.

    ``duplicate_rows`` is the caller's count, not measured here.
    """
    field_rows = {row_id for spec in registry.fields for row_id in spec.form.rows}
    mapped = [
        row_id for row_id, text in rows.items() if text.strip() and row_id in field_rows
    ]
    skipped = [row_id for row_id in rows if row_id not in field_rows]
    return MappedSummary(
        rows_mapped=len(mapped),
        fields_written=sum(1 for _ in _field_values(rows, registry)),
        rows_skipped=len(skipped),
        duplicate_rows=duplicate_rows,
    )


def document_values_for_rows(document: Document, registry: Registry) -> dict[str, str]:
    """Render a document into the Form rows it fills.

    Every present registry field, in registry order, contributes its row
    texts; an absent field contributes no row, so its placeholder stays. A
    row two fields share is written by its owner alone (the first claimant
    that carries a value): the import files a written row's text back to
    every claimant, so a second claimant writing beside the owner would be
    re-absorbed into the owner's field and grow it on every cycle. An
    unreadable value is a :class:`DocxError`.
    """
    carried: list[tuple[FieldSpec, list[tuple[str, str]]]] = []
    for spec in registry.fields:
        value = _document_value(document.values, spec)
        if value is None:
            continue
        rows = list(_row_texts(spec, value))
        if rows:
            carried.append((spec, rows))
    owners: dict[str, FieldSpec] = {}
    for spec, _ in carried:
        for row_id in spec.form.rows:
            owners.setdefault(row_id, spec)
    values: dict[str, str] = {}
    for spec, rows in carried:
        for row_id, text in rows:
            if owners[row_id] is not spec:
                continue
            values.setdefault(row_id, text)
    return values


def write_form(
    template_path: Path,
    values_by_row: Mapping[str, str],
    out_path: Path,
    *,
    registry: Registry | None = None,
) -> None:
    """Write ``values_by_row`` into a filled copy of a Form-shaped template.

    Every member is copied through unchanged except ``word/document.xml``,
    where each value goes into its located row's response field (the write
    shapes are :func:`_write_lines`); a value with no row there is written
    nowhere. The template file itself is never modified: writing over it is
    refused.

    ``registry`` defaults to the packaged pack, against which the template is
    checked; a package with no known Form row and values the document part
    cannot carry are refusals, raised before anything is written.
    """
    if registry is None:
        registry = load()
    _check_values(values_by_row)
    members = _read_members(template_path)
    document_xml = _part_bytes(template_path, members)
    root = _parsed_part(template_path, document_xml)
    walked = list(_walk_rows(root))
    rows = [walked_row.row for walked_row in walked]
    _check_template(template_path, rows, registry)
    located, _ = _locate(rows, registry)
    for row_id, text in values_by_row.items():
        target = located.get(row_id)
        if target is None:
            continue
        field = _response_field(
            walked[target.position], outer=target.outer, inner=target.inner
        )
        if field is None:
            continue
        _write_lines(field, text)
    if out_path.exists() and out_path.samefile(template_path):
        raise DocxError(f"refusing to overwrite the template {template_path}")
    _write_package(members, _serialise(root, document_xml), out_path)


def _field_values(
    rows: Mapping[str, str], registry: Registry
) -> Iterator[tuple[FieldSpec, object]]:
    """Every field's non-empty value, in registry order (the one assembly)."""
    for spec in registry.fields:
        answers = [rows.get(row_id, "").strip() for row_id in spec.form.rows]
        answers = [answer for answer in answers if answer]
        if not answers:
            continue
        if _STRUCTURED_RULES & set(spec.rules):
            yield spec, _structured_value(spec, rows)
            continue
        yield spec, "\n\n".join(answers)


def _structured_value(spec: FieldSpec, rows: Mapping[str, str]) -> dict[str, object]:
    """A structured element's value: its rows' answers on their leaves."""
    leaves: dict[str, list[str]] = {}
    for row_id in spec.form.rows:
        leaf = _ROW_LEAVES.get(row_id)
        answer = rows.get(row_id, "").strip()
        if leaf is not None and answer:
            leaves.setdefault(leaf, []).append(answer)
    value: dict[str, object] = {}
    for leaf, parts in leaves.items():
        text = "\n\n".join(parts)
        number = _number_literal(text) if leaf in _NUMERIC_LEAVES else None
        _assign_leaf(value, leaf, number if number is not None else text)
    return value


def _assign_leaf(value: dict[str, object], leaf: str, answer: object) -> None:
    """Place a leaf's value, nesting a dotted leaf path ("training.amount")."""
    *parents, key = leaf.split(".")
    mapping: dict[str, object] = value
    for parent in parents:
        mapping = cast(dict[str, object], mapping.setdefault(parent, {}))
    mapping[key] = answer


def _document_value(values: Mapping[str, object], spec: FieldSpec) -> object:
    """The document's raw value for a registry field, None when absent."""
    section, _, key = spec.model_field.partition(".")
    annex = values.get(section)
    if annex is None:
        return None
    if not isinstance(annex, Mapping):
        raise DocxError(f"the document's {section} section is not a mapping")
    return annex.get(key)


def _row_texts(spec: FieldSpec, value: object) -> Iterator[tuple[str, str]]:
    """A field's (row id, text) pairs, in the field's own row order."""
    if _STRUCTURED_RULES & set(spec.rules):
        yield from _structured_row_texts(spec, value)
        return
    text = _scalar_text(spec.model_field, value)
    if text.strip():
        yield spec.form.rows[0], text


def _structured_row_texts(spec: FieldSpec, value: object) -> Iterator[tuple[str, str]]:
    """A structured element's leaves, on the rows that carry them.

    Each leaf is written once, on the first row of the field's mapping that
    routes to it, so the twin rows stay empty; rows and leaves the value does
    not carry contribute nothing.
    """
    if not isinstance(value, Mapping):
        raise DocxError(f"the document's {spec.model_field} is not a mapping")
    written: set[str] = set()
    for row_id in spec.form.rows:
        leaf = _ROW_LEAVES.get(row_id)
        if leaf is None or leaf in written:
            continue
        raw = _leaf_value(value, leaf, spec.model_field)
        if raw is None:
            continue
        written.add(leaf)
        text = _structured_text(spec.model_field, leaf, raw, value)
        if text.strip():
            yield row_id, text


def _leaf_value(value: Mapping[str, object], leaf: str, field: str) -> object:
    """A leaf's raw value, walking a dotted leaf path; None when absent."""
    current: object = value
    for part in leaf.split("."):
        if not isinstance(current, Mapping):
            raise DocxError(f"the document's {field} is not a mapping")
        current = current.get(part)
        if current is None:
            return None
    return current


def _structured_text(
    field: str, leaf: str, raw: object, value: Mapping[str, object]
) -> str:
    """One structured leaf's spelled-out text.

    A number takes the element's own units (``<amount> FLOP`` with its
    estimation method after it, ``<amount> <unit>`` for energy). A leaf the
    document carries as text is returned verbatim, because it is already the
    text a former export wrote.
    """
    display = f"{field}.{leaf}"
    if leaf not in _NUMERIC_LEAVES or not _is_number(raw):
        return _scalar_text(display, raw)
    amount = _scalar_text(display, raw)
    if leaf == "training_flop":
        text = f"{amount} FLOP"
        method = _leaf_value(value, "estimation_method", field)
        if method is not None:
            estimated = _scalar_text(f"{field}.estimation_method", method)
            if estimated:
                text += f" (estimated: {estimated})"
        return text
    arm = leaf.partition(".")[0]
    unit = _leaf_value(value, f"{arm}.unit", field)
    if unit is None:
        return amount
    rendered = _scalar_text(f"{field}.{arm}.unit", unit)
    return f"{amount} {rendered}" if rendered else amount


def _is_number(value: object) -> bool:
    """Whether a leaf value is a number the format writes with its units.

    ``True`` is an ``int`` in Python and no amount in the document, so bools
    take the verbatim text path.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar_text(field: str, value: object) -> str:
    """A raw value's text, verbatim; a shape text cannot take refuses.

    Bools and numbers take the spelling the document reader parses back (a
    float is its repr, so ``2.3e+25`` keeps its digits). A non-finite float,
    and a sequence or mapping where a value belongs, are refusals.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DocxError(f"the document's {field} is not a finite number")
        return repr(value)
    raise DocxError(f"the document's {field} is not a value the Form can carry")


def _check_values(values: object) -> None:
    """Refuse a values mapping that is not row id to writable text."""
    if not isinstance(values, Mapping):
        raise DocxError("values_by_row must be a mapping of row id to text")
    for row_id, text in values.items():
        if not isinstance(row_id, str):
            raise DocxError(f"values_by_row: the row id {row_id!r} is not a string")
        if not isinstance(text, str):
            raise DocxError(
                f"values_by_row[{row_id!r}]: the value {text!r} is not a string"
            )
        if _UNWRITABLE_CHARS.search(text):
            raise DocxError(
                f"values_by_row[{row_id!r}]: the value holds a character "
                f"{_DOCUMENT_PART} cannot carry"
            )


def _check_template(
    template_path: Path, walked: list[FormRow], registry: Registry
) -> None:
    """Refuse a package that does not look like the Form.

    At least one walked row must carry a label the published inventory knows
    (:func:`_matches`' normalisation), or be the split row two published
    labels share.
    """
    known = {_normalise_label(spec.label) for spec in registry.form.rows}
    for row in walked:
        if _normalise_label(row.label) in known:
            return
        if _split_specs(row, registry) is not None:
            return
    raise DocxError(f"{template_path}: no known Model Documentation Form row")


def _read_members(
    template_path: Path,
) -> list[tuple[zipfile.ZipInfo, bytes]]:
    """Read every member of the template package, in member order.

    Every unreadable input reads as the one-line :class:`DocxError` the
    command's exit-2 contract promises; the closed list is what the write
    copies through.
    """
    try:
        with zipfile.ZipFile(template_path) as package:
            return [(info, package.read(info)) for info in package.infolist()]
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise DocxError(f"cannot read {template_path}: {error}") from error


def _part_bytes(
    template_path: Path, members: list[tuple[zipfile.ZipInfo, bytes]]
) -> bytes:
    """The package's ``word/document.xml``, or the reader's own refusal."""
    for info, data in members:
        if info.filename == _DOCUMENT_PART:
            return data
    raise DocxError(f"{template_path}: the package has no {_DOCUMENT_PART}")


class _Field(NamedTuple):
    """A located row's response field and where its text lives.

    ``element`` is the cell a cell-wrapping control holds, or the control
    itself when the field sits inside a plain cell; ``control`` is the
    response control either way, the element whose placeholder state a
    written value clears.
    """

    element: ET.Element
    control: ET.Element
    cell: _Cell


def _response_field(walked: _WalkedRow, *, outer: bool, inner: bool) -> _Field | None:
    """Locate a row's response field.

    ``outer`` takes the cell the row's own response control wraps, ``inner``
    the first response control inside a plain cell, the split row's halves
    apart. A row carrying neither has nowhere to write.
    """
    if outer:
        for cell in walked.area:
            control = cell.control
            if cell.kind == _RESPONSE and control is not None:
                return _Field(cell.element, control, cell)
    if inner:
        for cell in walked.area:
            for control in _elements(cell.element):
                if control.tag == _SDT and _control_kind(control) == _RESPONSE:
                    return _Field(control, control, cell)
    return None


def _elements(element: ET.Element) -> Iterator[ET.Element]:
    """Every element beneath one, a nested table contributing none.

    The reader's own scope: :func:`_collect_text` never descends a ``w:tbl``,
    so an answer control inside a nested table belongs to the nested rows,
    and this row must not write where the walk would never read it back.
    """
    for child in element:
        if child.tag == _TBL:
            continue
        yield child
        yield from _elements(child)


def _write_lines(field: _Field, text: str) -> None:
    """Write ``text``'s lines into one response field.

    A control holding paragraphs takes the first line in its first
    paragraph's runs and the further lines as further paragraphs carrying its
    properties; a run-level control takes EVERY line inside its own content,
    ``w:br``-separated (the reader's soft break), so no line lands beside the
    control as the row's description; a control holding runs with no
    paragraph takes them as its own paragraphs. Writing clears the control's
    ``w:showingPlcHdr`` flag (the structure note, on the Form's five
    run-level rows).
    """
    lines = text.splitlines()
    if not lines:
        return
    paragraphs = list(_paragraphs(field.element))
    if paragraphs:
        _clear_placeholder(field.control)
        source = paragraphs[0]
        _replace_runs(source, _text_run(lines[0]))
        container = _parent_of(field.cell.element, source)
        previous = source
        for line in lines[1:]:
            following = _line_paragraph(source, line)
            container.insert(_index_of(container, previous) + 1, following)
            previous = following
        return
    content = field.element.find(_SDT_CONTENT)
    if content is None:
        return
    _clear_placeholder(field.control)
    if _enclosing_paragraph(field.cell.element, field.element) is not None:
        # A run-level control: the whole value stays inside it, so the walk
        # reads every line back as its answer.
        _clear_runs(content)
        content.append(_soft_break_run(lines))
        return
    # The control holds its runs without a paragraph around them: the lines
    # become the content's own paragraphs, where the walk joins them as a
    # block field's answer.
    _clear_runs(content)
    for line in lines:
        content.append(_line_paragraph(None, line))


def _clear_placeholder(control: ET.Element) -> None:
    """Clear a response control's showing-placeholder state, as Word does."""
    for props in control.iterfind(_SDT_PR):
        for flag in list(props.iterfind(_SHOWING_PLC_HDR)):
            props.remove(flag)


def _clear_runs(holder: ET.Element) -> None:
    """Drop an element's own runs, the text a value replaces."""
    for existing in list(holder):
        if existing.tag == _R:
            holder.remove(existing)


def _paragraphs(element: ET.Element) -> Iterator[ET.Element]:
    """The paragraphs beneath an element; a nested table contributes none."""
    for child in element:
        if child.tag == _TBL:
            continue
        if child.tag == _P:
            yield child
        else:
            yield from _paragraphs(child)


def _enclosing_paragraph(cell: ET.Element, field: ET.Element) -> ET.Element | None:
    """The cell's paragraph holding a run-level field element, if any."""
    for paragraph in _paragraphs(cell):
        if any(child is field for child in paragraph.iter(_SDT)):
            return paragraph
    return None


def _parent_of(cell: ET.Element, element: ET.Element) -> ET.Element:
    """The cell's element whose own children include ``element``.

    ``element`` always came from walking the cell, so this never runs out.
    """
    return next(
        parent for parent in cell.iter() if any(child is element for child in parent)
    )


def _index_of(container: ET.Element, child: ET.Element) -> int:
    """Where a container's own children hold ``child``."""
    return next(index for index, node in enumerate(container) if node is child)


def _replace_runs(holder: ET.Element, run: ET.Element) -> None:
    """Replace an element's own runs with the one run that answers it."""
    _clear_runs(holder)
    holder.append(run)


def _line_paragraph(source: ET.Element | None, line: str) -> ET.Element:
    """A paragraph for a further value line, carrying ``source``'s props.

    A field with no response paragraph at all (a control holding its own
    runs) has no properties to carry, so the further lines take none.
    """
    paragraph = ET.Element(_P)
    if source is not None:
        props = source.find(_P_PR)
        if props is not None:
            paragraph.append(copy.deepcopy(props))
    paragraph.append(_text_run(line))
    return paragraph


def _text_run(text: str) -> ET.Element:
    """The run a written line takes: an answer, not the form's guidance.

    A response control may state a guidance colour of its own, so a written
    run states an explicit automatic colour: the walk reads it as the answer
    wherever the placeholder's formatting sat.
    """
    run = _answer_run()
    _append_run_text(run, text)
    return run


def _soft_break_run(lines: Sequence[str]) -> ET.Element:
    """The run a run-level control's lines take: ``w:br``-separated text.

    The whole value stays inside the control, the first line in the run and
    each further line after a ``w:br`` (the soft break the reader maps back
    to ``"\n"``), so no line lands beside the control as the row's
    description. A blank line stays the documented normalisation: the reader
    drops it, so the value settles to a single newline.
    """
    run = _answer_run()
    for index, line in enumerate(lines):
        if index:
            ET.SubElement(run, _BR)
        _append_run_text(run, line)
    return run


def _answer_run() -> ET.Element:
    """A written run, unformatted, so the walk reads an answer, not guidance."""
    run = ET.Element(_R)
    props = ET.SubElement(run, _R_PR)
    ET.SubElement(props, _COLOR, {_VAL: "auto"})
    return run


def _append_run_text(run: ET.Element, text: str) -> None:
    """Append one ``w:t`` to a run, preserving its surrounding whitespace."""
    element = ET.SubElement(run, _T)
    element.text = text
    if text != text.strip():
        element.set(_XML_SPACE, "preserve")


def _serialise(root: ET.Element, template_xml: bytes) -> bytes:
    """Serialise the written part, keeping the template's own declarations.

    ElementTree declares only the namespaces the rewritten tree uses, while
    the Form's part declares the whole Office prefix set its ``mc:Ignorable``
    tokens name; the template's declarations are registered first and the
    dropped ones carried back over.
    """
    _register_prefixes(template_xml)
    payload: bytes = ET.tostring(root, encoding="utf-8")
    return _DECLARATION + _restore_declarations(payload, template_xml)


def _restore_declarations(payload: bytes, template_xml: bytes) -> bytes:
    """Add the namespace declarations the payload does not carry.

    Both scans read root start tags alone (the payload's first tag is its
    root), so a declaration-shaped string in either part's text is no
    declaration.
    """
    root = _root_tag(payload)
    declared = {prefix for prefix, _ in _NAMESPACE_DECLARATION.findall(root)}
    additions = b"".join(
        b' xmlns:%s="%s"' % (prefix, uri)
        for prefix, uri in _NAMESPACE_DECLARATION.findall(_root_tag(template_xml))
        if prefix not in declared
    )
    # root[:-1] drops the closing ">", so the additions land inside the tag.
    return root[:-1] + additions + root[-1:] + payload[len(root) :]


def _register_prefixes(template_xml: bytes) -> None:
    """Register the namespace prefixes the template's part declares.

    ElementTree serialises unknown namespaces as ``ns0``/``ns1``, and the
    Form's root names its prefixes in its ``mc:Ignorable`` tokens, so
    renaming them would leave those tokens unbound. The registration is
    global to ElementTree (there is no per-call prefix map).
    """
    for prefix, uri in _NAMESPACE_DECLARATION.findall(_root_tag(template_xml)):
        ET.register_namespace(prefix.decode("ascii"), uri.decode("utf-8"))


def _root_tag(xml_bytes: bytes) -> bytes:
    """A part's root start tag, the one tag declarations belong in.

    A byte order mark and an XML declaration are skipped, so a
    declaration-shaped string later in the part (a written answer, say) is
    never read as a declaration of the part.
    """
    start = xml_bytes.find(b"<")
    if xml_bytes[start : start + 2] == b"<?":
        start = xml_bytes.find(b"<", xml_bytes.index(b"?>", start) + 2)
    return xml_bytes[start : xml_bytes.index(b">", start) + 1]


def _write_package(
    members: list[tuple[zipfile.ZipInfo, bytes]],
    document_xml: bytes,
    out_path: Path,
) -> None:
    """Write the package back: the document part new, every other as it was.

    The members keep their names, order, compression and stored attributes,
    and every timestamp is the fixed 1980-01-01 value, so the write is a pure
    function of the template's bytes and the values (determinism).
    The flag bits need the extra pass below: ``zipfile``'s writer computes
    its own and resets whatever the ``ZipInfo`` carried.
    """
    with zipfile.ZipFile(out_path, "w") as package:
        for info, data in members:
            member = zipfile.ZipInfo(info.filename, date_time=_FIXED_TIMESTAMP)
            member.compress_type = info.compress_type
            member.create_system = info.create_system
            member.internal_attr = info.internal_attr
            member.comment = info.comment
            if info.filename == _DOCUMENT_PART:
                data = document_xml
            package.writestr(member, data)
    _stamp_headers(out_path, members)


def _stamp_headers(
    out_path: Path, members: list[tuple[zipfile.ZipInfo, bytes]]
) -> None:
    """Write the template's stored flag bits and attributes into the headers.

    ``zipfile``'s writer resets whatever flag bits the ``ZipInfo`` carried and
    defaults an empty ``external_attr`` to its own permissions, so the central
    directory is walked in the member order the package was written in and
    each member's stored values are stamped: the flags (the template's, the
    writer's own bits kept) into the entry and its local header, and the
    external attributes into the entry.
    """
    data = bytearray(out_path.read_bytes())
    offset = struct.unpack_from("<I", data, data.rindex(b"PK\x05\x06") + 16)[0]
    for info, _ in members:
        (local,) = struct.unpack_from("<I", data, offset + 42)
        (stored,) = struct.unpack_from("<H", data, offset + 8)
        stamped = (info.flag_bits & ~_FLAG_WRITER_OWNS) | (stored & _FLAG_WRITER_OWNS)
        struct.pack_into("<H", data, offset + 8, stamped)
        struct.pack_into("<H", data, local + 6, stamped)
        struct.pack_into("<I", data, offset + 38, info.external_attr)
        (name_length,) = struct.unpack_from("<H", data, offset + 28)
        (extra_length, comment_length) = struct.unpack_from("<HH", data, offset + 30)
        offset += 46 + name_length + extra_length + comment_length
    out_path.write_bytes(bytes(data))


def _section_of(row: FormRow) -> str | None:
    """The registry section part a walked row's heading maps to, if any."""
    return _SECTION_BY_HEADING.get(row.section)


def _matches(row: FormRow, spec: FormRowSpec) -> bool:
    """Whether a walked row is this inventory row's own (label and crosses)."""
    return _normalise_label(row.label) == _normalise_label(spec.label) and _ticked(
        row.crosses
    ) == set(spec.audience_flags)


def _same_section(row: FormRow, spec: FormRowSpec) -> bool:
    """Whether a walked row sits in the section the published row lives in.

    The section half of the location predicate: a same-label row
    under another heading is never the published row's.
    """
    return _section_of(row) == spec.row.partition("/")[0]


def _same_shape(row: FormRow, spec: FormRowSpec) -> bool:
    """Whether a walked row is the whole shape ``spec`` draws on.

    Section plus label-and-crosses :func:`_matches`: the predicate the
    duplicate counter applies, so a label under another heading is never
    counted as a duplicate (unmatched rows are silent).
    """
    return _same_section(row, spec) and _matches(row, spec)


def _split_specs(
    row: FormRow, registry: Registry
) -> tuple[FormRowSpec, FormRowSpec] | None:
    """The two published rows a split DOCX row covers, or None.

    The label cell concatenates the two labels, and the audience cells carry
    two tick pairs, the second the maximum-size row's (structure note).
    """
    section = _section_of(row)
    if section is None or len(row.cross_pairs) < 2:
        return None
    specs = [
        spec for spec in registry.form.rows if spec.row.partition("/")[0] == section
    ]
    text = _normalise_label(row.label)
    for first, second in itertools.pairwise(specs):
        if text not in (
            f"{first.label}: {second.label}",
            f"{first.label} {second.label}",
        ):
            continue
        if _ticked(row.cross_pairs[0]) != set(first.audience_flags):
            continue
        if _ticked(row.cross_pairs[1]) != set(second.audience_flags):
            continue
        return first, second
    return None


def _ticked(crosses: Mapping[str, bool]) -> set[str]:
    """The keys a row's crosses carries ticked; unticked columns are no flag."""
    return {key for key, state in crosses.items() if state}


def _normalise_label(label: str) -> str:
    """The published label a walked label means (structure note)."""
    text = _LABEL_INSTRUCTION.sub("", " ".join(label.split()))
    return text.rstrip(":. ")


def _answer_text(row: FormRow, *, outer: bool, inner: bool) -> str:
    """A row's answer text, the split row's two halves apart.

    The cells' answers join with a space; the caller joins rows with a blank
    line.
    """
    parts: list[str] = []
    for answer in row.answers:
        if outer and answer.outer:
            parts.append(answer.outer)
        if inner and answer.inner:
            parts.append(answer.inner)
    return " ".join(parts)


def _number_literal(text: str) -> int | float | None:
    """The number an exactly numeric answer denotes, or None.

    The grammar is the YAML 1.2 core set the registry reader constructs, so a
    value read here is a value the document reader reads back. A literal with
    no finite double (``1e400``) stays the text it is.
    """
    if _YAML12_INT.fullmatch(text):
        body = text.lstrip("+-")
        sign = -1 if text.startswith("-") else 1
        if body.startswith("0o"):
            return sign * int(body[2:], 8)
        if body.startswith("0x"):
            return sign * int(body[2:], 16)
        return sign * int(body)
    if _YAML12_FLOAT.fullmatch(text):
        value = float(text)
        return value if math.isfinite(value) else None
    return None


def _document_tree(package_path: Path) -> ET.Element:
    """Parse ``word/document.xml``, refusing unreadable input one line deep.

    A package that is not a zip, a missing file or part, a malformed part, an
    unsupported compression method and an encrypted member all read as the
    one-line :class:`DocxError` the import command's exit-2 contract promises
    (``NotImplementedError`` and ``RuntimeError`` are what ``zipfile`` raises
    for the last two).
    """
    try:
        with zipfile.ZipFile(package_path) as package:
            try:
                xml_bytes = package.read(_DOCUMENT_PART)
            except KeyError as error:
                raise DocxError(
                    f"{package_path}: the package has no {_DOCUMENT_PART}"
                ) from error
            except (NotImplementedError, RuntimeError) as error:
                raise DocxError(f"cannot read {package_path}: {error}") from error
    except (OSError, zipfile.BadZipFile) as error:
        raise DocxError(f"cannot read {package_path}: {error}") from error
    return _parsed_part(package_path, xml_bytes)


def _parsed_part(package_path: Path, xml_bytes: bytes) -> ET.Element:
    """Parse the document part, refusing a malformed one one line deep."""
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise DocxError(f"{package_path}: invalid {_DOCUMENT_PART}: {error}") from error


def _child_rows(table: ET.Element) -> Iterator[ET.Element]:
    """The table's rows, descending through row-wrapping content controls."""
    for child in table:
        if child.tag == _TR:
            yield child
        elif child.tag == _SDT:
            for content in child.iterfind(_SDT_CONTENT):
                yield from _child_rows(content)


def _child_cells(
    row: ET.Element, kind: str | None = None, control: ET.Element | None = None
) -> Iterator[_Cell]:
    """The row's cells, descending through cell-wrapping content controls.

    Each cell keeps the role of the control that last set it, paired with
    that control, so a tick control wrapped in a plain one still reads its
    own ``w14:checked`` state and not the inner control's absence.
    """
    for child in row:
        if child.tag == _TC:
            yield _Cell(child, kind, control)
        elif child.tag == _SDT:
            own = _control_kind(child)
            inner_kind = own if own is not None else kind
            inner_control = child if own is not None else control
            for content in child.iterfind(_SDT_CONTENT):
                yield from _child_cells(content, inner_kind, inner_control)


def _control_kind(control: ET.Element) -> str | None:
    """The role a content control plays, from its own properties."""
    for props in control.iterfind(_SDT_PR):
        if props.find(_W14_CHECKBOX) is not None:
            return _TICK
        if props.find(_ALIAS) is not None or props.find(_TAG) is not None:
            return _RESPONSE
    return None


def _tick_state(control: ET.Element) -> bool:
    """The control's state, from ``w14:checked``: ``1`` ticked, ``0`` not.

    The structured state is the source, never the rendered character; a
    control that spells no state reads unticked.
    """
    values = [
        checked.get(_W14_CHECKED_VAL, "0")
        for props in control.iterfind(_SDT_PR)
        for checkbox in props.iterfind(_W14_CHECKBOX)
        for checked in checkbox.iterfind(_W14_CHECKED)
    ]
    return any(value in ("1", "true") for value in values)


def _tick_states(cell: _Cell) -> list[bool]:
    """The cell's tick controls' states, the wrapping control first."""
    states = (
        [_tick_state(cell.control)]
        if cell.kind == _TICK and cell.control is not None
        else []
    )
    states.extend(
        _tick_state(control)
        for control in cell.element.iter(_SDT)
        if _control_kind(control) == _TICK
    )
    return states


def _cross_pairs(audience: list[_Cell]) -> tuple[dict[str, bool], ...]:
    """Every audience tick pair in reading order (the split row carries two)."""
    columns = [
        (key, _tick_states(cell))
        for key, cell in zip(_AUDIENCE_KEYS, audience, strict=False)
    ]
    depth = max((len(states) for _, states in columns), default=0)
    return tuple(
        {key: states[index] for key, states in columns if index < len(states)}
        for index in range(depth)
    )


def _is_heading(cells: list[_Cell]) -> bool:
    """Whether a row is a section heading (structure note)."""
    spans = [
        int(span.get(_VAL, "1"))
        for cell in cells[:1]
        for props in cell.element.iterfind(_TC_PR)
        for span in props.iterfind(_GRID_SPAN)
    ]
    return len(cells) > 1 and any(span > 1 for span in spans)


def _cell_texts(cell: _Cell) -> tuple[str, str]:
    """A cell's (static, response) text, whitespace-normalised.

    A response-wrapped cell is response text throughout; a tick control's
    content is read as neither, its meaning being its state.
    """
    if cell.kind == _TICK:
        return "", ""
    static: list[str] = []
    response: list[str] = []
    _collect_text(cell.element, cell.kind == _RESPONSE, False, None, static, response)
    return _normalise(static), _normalise(response)


def _cell_answers(cell: _Cell) -> CellAnswer:
    """One response-area cell's answer text (the mapping layer's input).

    A response-wrapped cell answers ``outer``, a plain cell the controls
    inside it as ``inner``; the pinned form's guidance reads absent, so a
    blank import stays the skeleton.
    """
    if cell.kind == _TICK:
        return CellAnswer("", "")
    static: list[str] = []
    response: list[str] = []
    if cell.kind == _RESPONSE and cell.control is not None:
        if _placeholder_control(cell.control):
            return CellAnswer("", "")
        colour = _control_colour(cell.control)
        _collect_text(cell.element, True, True, colour, static, response)
        return CellAnswer(_normalise(response), "")
    _collect_text(cell.element, False, True, None, static, response)
    return CellAnswer("", _normalise(response))


def _placeholder_control(control: ET.Element) -> bool:
    """Whether a control holds guidance, not an answer (structure note)."""
    props = control.find(_SDT_PR)
    if props is None:
        return False
    if props.find(_SHOWING_PLC_HDR) is not None:
        return True
    values = {
        _normalise([attribute.get(_VAL, "")])
        for attribute in (*props.iterfind(_ALIAS), *props.iterfind(_TAG))
    }
    text = _joined_text(control)
    return bool(text) and text in values


def _control_colour(control: ET.Element) -> str | None:
    """The colour a response control's own run properties state, if any."""
    props = control.find(_SDT_PR)
    if props is None:
        return None
    rpr = props.find(_R_PR)
    if rpr is None:
        return None
    colour = rpr.find(_COLOR)
    return None if colour is None else colour.get(_VAL, "")


def _guidance_run(run: ET.Element, colour: str | None) -> bool:
    """Whether a run carries guidance, not an answer (structure note)."""
    props = run.find(_R_PR)
    style: str | None = None
    explicit: str | None = None
    if props is not None:
        style_element = props.find(_R_STYLE)
        style = style_element.get(_VAL) if style_element is not None else None
        colour_element = props.find(_COLOR)
        explicit = colour_element.get(_VAL) if colour_element is not None else None
    if explicit is not None:
        return explicit in _GUIDANCE_COLORS
    if style is not None:
        return style in _GUIDANCE_STYLES
    return colour in _GUIDANCE_COLORS


def _joined_text(element: ET.Element) -> str:
    """All ``w:t`` text beneath an element, whitespace-normalised."""
    return _normalise([text.text or "" for text in element.iter(_T)])


def _collect_text(
    element: ET.Element,
    in_response: bool,
    discriminate: bool,
    colour: str | None,
    static: list[str],
    response: list[str],
) -> None:
    """Gather ``w:t`` text, separating the response fields' text.

    Runs within a paragraph join with nothing; a ``w:br`` or ``w:cr``
    contributes ``"\n"`` and the paragraph boundary a space, so a label split
    across paragraphs (the form's own shape) reads with the space it means. A
    nested table contributes nothing to the containing cell. With
    ``discriminate``, the guidance a response field carries is left out of
    the response text; without it, the walk stays faithful and keeps it.
    """
    for child in element:
        if child.tag == _TBL:
            continue
        if child.tag == _SDT:
            kind = _control_kind(child)
            if kind == _TICK:
                continue
            # The nested control's colour is local to its own recursion: the
            # outer frame keeps its own fallback, or a coloured nested control
            # would shade the siblings that follow it in this frame.
            inner_colour = colour
            if discriminate and (in_response or kind == _RESPONSE):
                if _placeholder_control(child):
                    continue
                own = _control_colour(child)
                if own is not None:
                    inner_colour = own
            for content in child.iterfind(_SDT_CONTENT):
                _collect_text(
                    content,
                    in_response or kind == _RESPONSE,
                    discriminate,
                    inner_colour,
                    static,
                    response,
                )
        elif child.tag == _R:
            if discriminate and in_response and _guidance_run(child, colour):
                continue
            _collect_text(child, in_response, discriminate, colour, static, response)
        elif child.tag == _T:
            (response if in_response else static).append(child.text or "")
        elif child.tag in (_BR, _CR):
            (response if in_response else static).append("\n")
        elif child.tag == _P:
            before = (len(static), len(response))
            _collect_text(child, in_response, discriminate, colour, static, response)
            if len(static) > before[0]:
                static.append(" ")
            if len(response) > before[1]:
                response.append(" ")
        else:
            _collect_text(child, in_response, discriminate, colour, static, response)


def _normalise(parts: list[str]) -> str:
    """Join text parts, collapse each line's whitespace, drop blank lines.

    Runs of whitespace within a line collapse to one space, and a blank line
    (however much whitespace it holds) collapses to the single newline before
    the next line, the blank-line normalisation the round-trip claim records.
    """
    lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)
