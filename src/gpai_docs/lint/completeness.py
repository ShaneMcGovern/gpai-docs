"""The registry-driven checks: typed, completeness, unknown.

Unknown findings are re-sorted by path so report order never depends on
pydantic's error order; the completeness pass walks the registry's fields in
registry order. Consistency and adequacy are not this module's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from gpai_docs.lint.findings import (
    Finding,
    error_location,
    error_path,
    malformed_message,
    unknown_message,
)
from gpai_docs.models import ModelDocument

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from gpai_docs.documents import Document
    from gpai_docs.registry import Registry

__all__ = ["lint"]

# A value that is not in the document at all.
_ABSENT = object()

# The schema marker the loader does not surface, reinserted so a
# whole document validates; the loader owns its enforcement.
_MARKER = {"schema": 1}


def lint(document: Document, registry: Registry) -> list[Finding]:
    """Check ``document``: typed, then completeness, then unknown."""
    errors = _errors(document)
    malformed = _malformed_findings(errors, registry)
    findings = list(malformed)
    findings.extend(_missing_findings(document, registry, malformed))
    findings.extend(_unknown_findings(errors))
    return findings


def _errors(document: Document) -> list[ErrorDetails]:
    payload = {**_MARKER, **document.values, **document.records}
    try:
        ModelDocument.model_validate(payload)
    except ValidationError as error:
        return error.errors(include_url=False)
    return []


def _malformed_findings(
    errors: list[ErrorDetails], registry: Registry
) -> list[Finding]:
    """One malformed finding per non-extra error.

    The number union's two arms report one value twice at one path, so the
    first occurrence wins.
    """
    by_model_field = {field.model_field: field.id for field in registry.fields}
    findings: list[Finding] = []
    seen: set[str] = set()
    for error in errors:
        if error["type"] == "extra_forbidden":
            continue
        location = error_location(error_path(error))
        if location in seen:
            continue
        seen.add(location)
        findings.append(
            Finding(
                kind="malformed",
                location=location,
                field_id=_field_id(error, by_model_field),
                message=malformed_message(error, registry),
            )
        )
    return findings


def _field_id(error: ErrorDetails, by_model_field: dict[str, str]) -> str | None:
    """The registry id the error's first two segments name, or ``None``.

    Records paths (``notifications[0].notified_at``) and top-level keys name
    no element, so they read as field-less findings.
    """
    dotted = ".".join(str(part) for part in error_path(error)[:2])
    return by_model_field.get(dotted)


def _missing_findings(
    document: Document, registry: Registry, malformed: list[Finding]
) -> list[Finding]:
    """One finding per registry field the document does not answer.

    Malformed wins: a path the typed pass already reported is skipped, so a
    wrong value is never also reported missing. A field carrying the
    ``systemic_risk`` condition is checked only when the document's marker
    asserts it.
    """
    decided = {finding.location for finding in malformed}
    systemic_risk = _systemic_risk(document)
    findings: list[Finding] = []
    for field in registry.fields:
        if field.model_field in decided:
            continue
        if field.condition is not None and not systemic_risk:
            continue
        if _absent(_resolve(document, field.model_field)):
            findings.append(
                Finding(kind="missing", location=field.model_field, field_id=field.id)
            )
    return findings


def _systemic_risk(document: Document) -> bool:
    """Whether the document asserts systemic risk.

    The marker resolves from the validated document when the models accept
    the payload, and from the raw top-level value otherwise; only a real
    ``True`` reads as it, so a non-boolean value is the typed pass's finding
    and the conditional fields stay skipped rather than guessed at.
    """
    payload = {**_MARKER, **document.values, **document.records}
    try:
        return ModelDocument.model_validate(payload).systemic_risk
    except ValidationError:
        return document.values.get("systemic_risk") is True


def _absent(value: object) -> bool:
    """Whether the checks read a resolved value as absent.

    ``null``, the empty string and the empty list are absences, and so is a
    mapping with no non-null leaf beneath it: an empty or all-null one
    describes nothing.
    """
    if value is _ABSENT or value is None or value == "":
        return True
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        return not _has_leaf(value)
    return False


def _has_leaf(value: object) -> bool:
    """Whether a non-null leaf sits at or beneath ``value``.

    Iterative and alias-aware: YAML anchors can make a mapping reference
    itself, and the walk must terminate on one rather than crash a run.
    """
    stack = [value]
    seen: set[int] = set()
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if isinstance(item, dict):
            if id(item) in seen:
                continue
            seen.add(id(item))
            stack.extend(item.values())
            continue
        return True
    return False


def _resolve(document: Document, path: str) -> object:
    """The raw value at ``annex_xi.key`` / ``annex_xii.key``, or ``_ABSENT``.

    The loader guarantees the annex sections are mappings; a document that
    carries neither reads every element as absent.
    """
    section, _, key = path.partition(".")
    mapping = cast("dict[str, object] | None", document.values.get(section))
    if mapping is None:
        return _ABSENT
    return mapping.get(key, _ABSENT)


def _unknown_findings(errors: list[ErrorDetails]) -> list[Finding]:
    """The typed pass's extra keys, sorted by path string."""
    findings: list[Finding] = []
    for error in errors:
        if error["type"] != "extra_forbidden":
            continue
        path = error_path(error)
        findings.append(
            Finding(
                kind="unknown",
                location=error_location(path),
                message=unknown_message(path),
            )
        )
    return sorted(findings, key=lambda finding: finding.location)
