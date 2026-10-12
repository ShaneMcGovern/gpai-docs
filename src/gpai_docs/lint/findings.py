"""One lint finding and its cited rendering.

A block may not read as a compliance verdict: it names its subject, carries
the kind's message and its citations, and this module owns both the message
words and the render so the two cannot drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import UnionType
from typing import TYPE_CHECKING, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from gpai_docs.models import (
    DateValue,
    ModelDocument,
    NumberValue,
    TextListValue,
    TextValue,
    UrlValue,
)
from gpai_docs.models.leaves import BooleanValue

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from gpai_docs.registry import Registry
    from gpai_docs.registry.models import Field

__all__ = [
    "FOOTER",
    "Finding",
    "FindingKind",
    "error_location",
    "error_path",
    "malformed_message",
    "render_finding",
    "unknown_message",
]

# The shared closing line: no output may
# read as a compliance verdict.
FOOTER = "engineering evidence, not a compliance verdict"

FindingKind = Literal["missing", "unknown", "malformed", "inconsistent"]

# The recipient display names the demo uses, spelling the
# registry's ai_office / nca / downstream vocabulary for a reader; the Form's
# audience flags stay in the registry's own vocabulary, not reworded.
_RECIPIENT_NAMES = {
    "ai_office": "AI Office",
    "nca": "NCAs",
    "downstream": "downstream providers",
}

_TAG_SHAPES = {
    "type:text": "text",
    "type:text-list": "a list of text",
    "type:number": "a number",
    "type:date": "a date",
    "type:url": "an http or https URL",
    "type:compute": "a compute mapping",
    "type:energy": "an energy mapping",
}

# The shape words the model leaves name, for slots below an element: a
# structured subfield or a record-entry field has no registry tag of its own.
# ``bool`` covers the document root's systemic-risk marker, whose bare
# annotation pydantic keeps outside any ``Annotated`` alias.
_LEAF_SHAPES = (
    (TextValue, "text"),
    (TextListValue, "a list of text"),
    (NumberValue, "a number"),
    (DateValue, "a date"),
    (UrlValue, "an http or https URL"),
    (BooleanValue, "a boolean"),
    (bool, "a boolean"),
)

# Pydantic reports both arms of ``NumberValue``'s int | float union as two
# errors, each with the failing arm on its path; the value is one defect.
_NUMBER_BRANCHES = ("int", "float")
_NUMBER_ERRORS = ("int_type", "float_type")

# The exact unknown-key wordings: a key no registry entry names at
# the document's or a section's level, or a field the element's model does not
# declare below one (a structured subfield, a record-entry field).
_NO_ENTRY = "no registry entry for this key"
_NO_FIELD = "no such field"
_SECTION_DEPTH = 2

# The reader constructs numbers only from unquoted YAML 1.2 core literals
# and the hint names unquoting as the one mechanical
# remedy; matching that same shape keeps free text and the 1.1 oddities
# (`12:30`, `1_000`) from earning it.
_NUMERIC_TEXT = re.compile(
    r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+"
    r"|[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?)$"
)
_QUOTED_NUMBER_HINT = "(it reads as text when quoted; write it unquoted)"


@dataclass
class Finding:
    """One lint finding: its kind, the key path it concerns, its field if any.

    ``message`` carries the typed pass's or a rule's wording, and ``label``
    the rule-authored headline of a field-less finding.
    """

    kind: FindingKind
    location: str
    field_id: str | None = None
    message: str | None = None
    citations: list[str] = field(default_factory=list)
    basis_forms: list[tuple[str, str]] = field(default_factory=list)
    label: str | None = None


def error_path(error: ErrorDetails) -> tuple[int | str, ...]:
    """The location an error names, minus the number union's branch tag.

    Pydantic appends the failing arm of ``int | float`` to the path
    (``..., 'int'``); dropping it lets the field's own path be reported and
    the arms' duplicate errors collapse to one finding.
    """
    path = error["loc"]
    if error["type"] in _NUMBER_ERRORS and path and path[-1] in _NUMBER_BRANCHES:
        return path[:-1]
    return path


def error_location(path: tuple[int | str, ...]) -> str:
    """``annex_xi.energy_consumption`` / ``notifications[0].notified_at``."""
    head, *rest = path
    return str(head) + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in rest
    )


def unknown_message(path: tuple[int | str, ...]) -> str:
    """The exact unknown-key wording for an ``extra_forbidden`` path."""
    if len(path) > _SECTION_DEPTH:
        return _NO_FIELD
    return _NO_ENTRY


def malformed_message(
    error: ErrorDetails, registry: Registry, *, root: type[BaseModel] = ModelDocument
) -> str:
    """``expected <what>: <value> is not <what>`` for one malformed error.

    ``<what>`` is the registry ``type:`` tag at an element's own path and the
    model annotation below one; the refused value is shown as Python writes
    it. ``root`` is the model the path is read against (a test may pass a
    smaller model than the document root).
    """
    path = error_path(error)
    what = _expected_shape(path, registry, root)
    return f"expected {what}: {error['input']!r} is not {what}{_hint(error, what)}"


def _hint(error: ErrorDetails, what: str) -> str:
    """A drafting hint for a refusal the document author can fix.

    Only a quoted numeric string earns it: the same digits unquoted are a
    number under the YAML 1.2 core forms.
    """
    value = error["input"]
    if what == "a number" and isinstance(value, str) and _NUMERIC_TEXT.fullmatch(value):
        return f" {_QUOTED_NUMBER_HINT}"
    return ""


def _expected_shape(
    path: tuple[int | str, ...], registry: Registry, root: type[BaseModel]
) -> str:
    """The shape word for the slot a path names, by tag or annotation."""
    tag = _element_tag(path, registry)
    if tag is not None:
        return _TAG_SHAPES[tag]
    word = _shape_word(_annotation_at(root, path))
    if word is None:
        return "a valid value"
    return word


def _element_tag(path: tuple[int | str, ...], registry: Registry) -> str | None:
    """The ``type:`` tag of the registry field the path is an element's own."""
    if len(path) != 2:
        return None
    first, second = path
    if not isinstance(first, str) or not isinstance(second, str):
        return None
    dotted = f"{first}.{second}"
    for entry in registry.fields:
        if entry.model_field == dotted:
            return _tag_of(entry)
    return None


def _tag_of(field: Field) -> str | None:
    """The field's first ``type:`` rule, when it carries one.

    ``completeness`` alone is legal in the data grammar, so a tagless field
    falls back to its model annotation rather than failing the run.
    """
    return next((rule for rule in field.rules if rule in _TAG_SHAPES), None)


def _shape_word(annotation: object) -> str | None:
    """The shape word the model annotation declares, when it names one."""
    optional = _unwrap_optional(annotation)
    for alias, word in _LEAF_SHAPES:
        if optional == alias:
            return word
    if isinstance(optional, type) and issubclass(optional, BaseModel):
        return "a mapping"
    if get_origin(optional) is list:
        item = get_args(optional)[0]
        if isinstance(item, type) and issubclass(item, BaseModel):
            return "a list of records"
        return "a list"
    return None


def _annotation_at(container: object, path: tuple[int | str, ...]) -> object:
    """Walk the model tree ``container`` along ``path`` to the annotation there.

    ``None`` when the path does not resolve (an unknown key's path, or one
    below a leaf), so the caller falls back to a generic shape word.
    """
    if not path:
        return container
    inner = _unwrap_optional(container)
    head, rest = path[0], path[1:]
    if get_origin(inner) is list:
        if not isinstance(head, int):
            return None
        return _annotation_at(get_args(inner)[0], rest)
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        if not isinstance(head, str):
            return None
        field = inner.model_fields.get(head)
        if field is None:
            return None
        return _annotation_at(field.annotation, rest)
    return None


def _unwrap_optional(annotation: object) -> object:
    """``X | None`` becomes ``X``; a real union (int | float) is left whole."""
    inner = [part for part in get_args(annotation) if part is not type(None)]
    if get_origin(annotation) in (Union, UnionType) and len(inner) == 1:
        return inner[0]
    return annotation


def render_finding(finding: Finding, registry: Registry) -> str:
    """Render one finding as a citation block.

    The message renders only for a malformed or inconsistent finding, and the
    run's closing line - count plus :data:`FOOTER` - is the caller's to print.
    """
    field = None if finding.field_id is None else registry.by_id.get(finding.field_id)
    lines = [_headline(finding, field)]
    if finding.kind in ("malformed", "inconsistent") and finding.message is not None:
        lines.append(f"  Reason: {finding.message}")
    if field is not None:
        lines.append(f"  Key: {finding.location}")
        lines.append(f"  {_annex_point(field)} - owed to: {_owed_to(field)}")
        if field.form.rows:
            lines.append(f"  Form rows: {', '.join(field.form.rows)}")
            lines.append(
                f"  Form audience flags: {', '.join(field.form.audience_flags)}"
            )
        else:
            # A row-less Form mapping records why in its note (the model
            # requires one), so the finding states it in the rows' place.
            lines.append(f"  Form: {field.form.note}")
        lines.append(f'  "{registry.sources[field.source].text}"')
        if field.guidance is not None:
            lines.append(f"  Guidance: {field.guidance}")
    lines.extend(_basis_lines(finding, registry))
    return "\n".join(lines)


def _basis_lines(finding: Finding, registry: Registry) -> list[str]:
    """A finding's own bases: cited sources first, then Form rows.

    The ``Basis:`` header shows whenever the finding carries any basis, each
    citation as the source's location and verbatim text; an id the registry
    does not carry raises, since a data defect is never something to skip.
    """
    lines: list[str] = []
    if finding.citations or finding.basis_forms:
        lines.append("  Basis:")
    for source_id in finding.citations:
        source = registry.sources.get(source_id)
        if source is None:
            raise KeyError(
                f"unknown source id {source_id!r} cited by the {finding.kind} "
                f"finding at {finding.location!r}"
            )
        lines.append(f"  {source.location}")
        lines.append(f'  "{source.text}"')
    for row, label in finding.basis_forms:
        lines.append(f"  Form: {row} - {label}")
    return lines


def _headline(finding: Finding, field: Field | None) -> str:
    """The ``[KIND] id - label`` line, or the field-less forms.

    A field-less finding headlines with its rule-authored ``label`` (a
    consistency rule's record finding), else with the typed pass's unknown-key
    message; a field-bearing finding always uses the registry's own label.
    """
    if field is None:
        if finding.label is not None:
            return f"[{finding.kind.upper()}] {finding.location} - {finding.label}"
        if finding.kind == "unknown" and finding.message is not None:
            return f"[{finding.kind.upper()}] {finding.location} - {finding.message}"
        return f"[{finding.kind.upper()}] {finding.location}"
    return f"[{finding.kind.upper()}] {field.id} - {field.label}"


def _annex_point(field: Field) -> str:
    """``Annex XI, Section 1, point 2(e)`` / ``Annex XII, point 1(a)``."""
    section = f", Section {field.section}" if field.section is not None else ""
    return f"Annex {field.annex}{section}, point {field.point}"


def _owed_to(field: Field) -> str:
    """The Act's recipients for the element, in the demo's wording."""
    return ", ".join(_RECIPIENT_NAMES[recipient] for recipient in field.recipients)
