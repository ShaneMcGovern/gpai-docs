"""Version comparison over the registry's vocabulary.

The walk follows the registry, never the raw key set, so a key the format
does not define is no change, and it judges nothing: validity is lint's
story (docs/methodology.md, "Comparing document versions").
"""

from __future__ import annotations

import datetime
import json
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from gpai_docs.documents import RECORDS

# The format's absence reading, single-sourced from the checks'
# completeness pass so diff and lint can never disagree about presence.
from gpai_docs.lint.completeness import _absent

if TYPE_CHECKING:
    from gpai_docs.documents import Document
    from gpai_docs.registry import Registry

__all__ = [
    "FieldChange",
    "changes_json",
    "changes_markdown",
    "diff_documents",
    "render_changes",
    "typed_equal",
]

# A value that is not in the document at all. Never ``None``: null reads as
# an absence like a missing key, and the sentinel keeps the
# renderers able to tell "no value on this side" from a rendered value.
_ABSENT = object()

# The systemic-risk marker's top-level key. It is not a
# registry field - the registry conditions Section 2's fields on it instead -
# so diff reads it as an attribute of its own, beside the registry walk.
_SYSTEMIC_RISK = "systemic_risk"

# What a self-referential value renders as. YAML anchors can make a value
# reference itself, and such a value has no finite canonical form; the
# marker keeps the walk terminating and the rendering JSON-safe.
_RECURSIVE = "<recursive>"


@dataclass
class FieldChange:
    """One difference between two documents.

    ``location`` is a registry ``model_field`` path, ``systemic_risk``, or a
    records location (``notifications[0].date``); ``kind`` is
    ``added``/``removed``/``changed`` (the one kind with both sides set);
    ``before`` and ``after`` hold the raw values, ``_ABSENT`` for a side
    that has none.
    """

    location: str
    kind: Literal["added", "removed", "changed"]
    before: Any = _ABSENT
    after: Any = _ABSENT


def diff_documents(
    old: Document, new: Document, registry: Registry
) -> list[FieldChange]:
    """Compare two loaded documents registry-driven.

    The changes come in registry order, then the systemic-risk marker, then
    the records sections in :data:`gpai_docs.documents.RECORDS` order.
    """
    changes: list[FieldChange] = []
    for field in registry.fields:
        section, _, key = field.model_field.partition(".")
        before = _read(old.values, section, key)
        after = _read(new.values, section, key)
        if before is _ABSENT and after is _ABSENT:
            continue
        if before is _ABSENT:
            changes.append(
                FieldChange(location=field.model_field, kind="added", after=after)
            )
        elif after is _ABSENT:
            changes.append(
                FieldChange(location=field.model_field, kind="removed", before=before)
            )
        elif not typed_equal(before, after):
            changes.append(
                FieldChange(
                    location=field.model_field,
                    kind="changed",
                    before=before,
                    after=after,
                )
            )
    changes.extend(_marker_changes(old, new))
    for section in RECORDS:
        changes.extend(_record_changes(old, new, section))
    return changes


def render_changes(changes: list[FieldChange]) -> str:
    """The human rendering: one line per change.

    Each line opens with the sign (``+`` added, ``-`` removed, ``~``
    changed), then the location and the canonical value(s); nothing to report
    renders the empty string.
    """
    return "\n".join(_change_line(change) for change in changes)


def _change_line(change: FieldChange) -> str:
    if change.kind == "added":
        return f"+ {change.location}: {_side_text(change.after)}"
    if change.kind == "removed":
        return f"- {change.location}: {_side_text(change.before)}"
    return (
        f"~ {change.location}: "
        f"{_side_text(change.before)} -> {_side_text(change.after)}"
    )


def changes_json(changes: list[FieldChange]) -> dict[str, Any]:
    """The stable JSON payload: ``{"changes": [...]}``.

    Each entry carries ``location``, ``kind``, ``from`` and ``to``, in that
    order; both value keys are always present, ``null`` for an absent side.
    """
    entries: list[dict[str, Any]] = [
        {
            "location": change.location,
            "kind": change.kind,
            "from": _payload_value(change.before),
            "to": _payload_value(change.after),
        }
        for change in changes
    ]
    return {"changes": entries}


def _payload_value(value: object) -> object:
    return None if value is _ABSENT else _canonical(value)


def changes_markdown(changes: list[FieldChange]) -> str:
    """The Markdown table: ``| location | change | from | to |``.

    Header and rule are always present, so no changes renders the empty
    table; a side the change does not carry reads ``null``, and a value's
    ``|`` is escaped so a document can never break a row.
    """
    rows = [
        f"| {_cell(change.location)} | {change.kind} "
        f"| {_cell(_side_text(change.before))} "
        f"| {_cell(_side_text(change.after))} |"
        for change in changes
    ]
    return "\n".join(
        ["| location | change | from | to |", "| --- | --- | --- | --- |", *rows]
    )


def _side_text(value: object) -> str:
    """One side's inline text: ``null`` for the absent side, else canonical.

    Both text renderings spell it this way so an absent side can never fall
    through to the sentinel's ``repr`` (an address, and no stable output).
    """
    return "null" if value is _ABSENT else _value_text(value)


def _value_text(value: object) -> str:
    """One present raw value as compact JSON of its canonical form."""
    return json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"))


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _read(values: dict[str, object], section: str, key: str) -> object:
    """The raw value at ``section.key``, or ``_ABSENT`` when it reads absent.

    A section the loader would refuse has no elements; a present value rides
    through raw, nested nulls included, since it is the element that is
    present.
    """
    mapping = values.get(section)
    if not isinstance(mapping, dict):
        return _ABSENT
    value = mapping.get(key, _ABSENT)
    if value is _ABSENT or _absent(value):
        return _ABSENT
    return value


def _marker_changes(old: Document, new: Document) -> list[FieldChange]:
    """The systemic-risk marker's one change, when the documents differ on it.

    The marker is read raw and effective: absent and ``false`` read alike, and
    any other value compares as itself. Absence is the format's default, not a
    missing side, so a difference is always one ``changed`` change.
    """
    before = _effective_marker(old.values)
    after = _effective_marker(new.values)
    if typed_equal(before, after):
        return []
    return [
        FieldChange(location=_SYSTEMIC_RISK, kind="changed", before=before, after=after)
    ]


def _effective_marker(values: dict[str, object]) -> object:
    value = values.get(_SYSTEMIC_RISK, _ABSENT)
    return False if value is _ABSENT or value is False else value


def _record_changes(old: Document, new: Document, section: str) -> list[FieldChange]:
    """One records section's changes.

    Equal-length sections compare index-aligned; a section that meets a pair
    the field-wise reading cannot take falls back whole to remove+add, and a
    length change keeps the v0.1 multiset reading.
    """
    old_entries = _entries(old, section)
    new_entries = _entries(new, section)
    if len(old_entries) != len(new_entries):
        return _multiset_changes(old_entries, new_entries, section)
    aligned = _field_changes(old_entries, new_entries, section)
    if aligned is None:
        return _indexed_remove_add(old_entries, new_entries, section)
    return aligned


def _field_changes(
    old_entries: list[object], new_entries: list[object], section: str
) -> list[FieldChange] | None:
    """The index-aligned field-wise changes, or ``None`` for the fallback.

    A same-key-set mapping pair reports one ``changed`` change per differing
    field, in canonical key order; ``None`` means the caller falls the whole
    section back to remove+add, so one section is never diffed in two
    readings. The location renders the key (:func:`_key_text`), which is not
    injective: two keys that spell alike (``1`` and ``"1"``) share one
    location.
    """
    changes: list[FieldChange] = []
    for index, (before, after) in enumerate(zip(old_entries, new_entries, strict=True)):
        if _identity_key(before) == _identity_key(after):
            continue
        if not (
            isinstance(before, dict)
            and isinstance(after, dict)
            and set(before) == set(after)
        ):
            return None
        for key in sorted(before, key=_key_text):
            old_value = before[key]
            new_value = after[key]
            if _identity_key(old_value) == _identity_key(new_value):
                continue
            changes.append(
                FieldChange(
                    location=f"{section}[{index}].{_key_text(key)}",
                    kind="changed",
                    before=old_value,
                    after=new_value,
                )
            )
    return changes


def _indexed_remove_add(
    old_entries: list[object], new_entries: list[object], section: str
) -> list[FieldChange]:
    """A fallback section's changes: remove+add at every unequal index.

    Removals come first, in old order, then additions, in new order - the
    v0.1 shape, so a reorder of equal entries is now a change (accepted cost).
    """
    unequal = [
        index
        for index, (before, after) in enumerate(
            zip(old_entries, new_entries, strict=True)
        )
        if _identity_key(before) != _identity_key(after)
    ]
    removals = [
        FieldChange(
            location=f"{section}[{index}]", kind="removed", before=old_entries[index]
        )
        for index in unequal
    ]
    additions = [
        FieldChange(
            location=f"{section}[{index}]", kind="added", after=new_entries[index]
        )
        for index in unequal
    ]
    return removals + additions


def _multiset_changes(
    old_entries: list[object], new_entries: list[object], section: str
) -> list[FieldChange]:
    """The v0.1 reading for a length change: entries pair by canonical key.

    Each side's excess occurrences, oldest first, are a removal at their old
    index or an addition at their new one.
    """
    old_keys = [_identity_key(entry) for entry in old_entries]
    new_keys = [_identity_key(entry) for entry in new_entries]
    matched = _matched_counts(old_keys, new_keys)
    changes = [
        FieldChange(
            location=f"{section}[{index}]", kind="removed", before=old_entries[index]
        )
        for index in _excess_indices(old_keys, matched)
    ]
    changes.extend(
        FieldChange(
            location=f"{section}[{index}]", kind="added", after=new_entries[index]
        )
        for index in _excess_indices(new_keys, matched)
    )
    return changes


def _entries(document: Document, section: str) -> list[object]:
    """The section's raw entries; a section the loader would refuse has none."""
    entries = document.records.get(section)
    return entries if isinstance(entries, list) else []


def _identity_key(value: object) -> str:
    """One value's canonical identity: sorted-key JSON of its canonical form
    with every number read as the double it denotes.

    The element and key readings agree except at three corners: signed zero
    keys as a change although the numbers compare equal, NaN keys alike as
    the numbers do, and a number in mapping-key position reads by its text
    (:func:`_key_text`), so ``{1: ...}`` against ``{1.0: ...}`` is a change.
    """
    identity = _canonical_value(value, frozenset(), _double_number)
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _matched_counts(old_keys: list[str], new_keys: list[str]) -> Counter[str]:
    old_counts = Counter(old_keys)
    new_counts = Counter(new_keys)
    return Counter(
        {
            key: min(old_counts[key], new_counts[key])
            for key in old_counts.keys() | new_counts.keys()
        }
    )


def _excess_indices(keys: list[str], matched: Counter[str]) -> list[int]:
    excess: list[int] = []
    seen: Counter[str] = Counter()
    for index, key in enumerate(keys):
        seen[key] += 1
        if seen[key] > matched[key]:
            excess.append(index)
    return excess


def typed_equal(a: object, b: object) -> bool:
    """Whether two raw values read as the same value.

    Numbers compare numerically (two NaNs read as the same value), dates by
    value, strings exactly, lists element-wise in order, mappings by canonical
    deep equality; anything else by canonical form, and only within its kind.
    """
    return _equal(a, b, frozenset())


def _equal(a: object, b: object, seen: frozenset[tuple[int, int]]) -> bool:
    """The typed-equality walk; ``seen`` holds the pairs on the current path.

    Re-meeting a pair means both sides reach themselves through it, so they
    are assumed equal while their rest compares - what makes a cycle
    terminate rather than trace back.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _numbers_equal(a, b)
    if isinstance(a, list) and isinstance(b, list):
        pair = (id(a), id(b))
        if pair in seen:
            return True
        return len(a) == len(b) and all(
            _equal(x, y, seen | {pair}) for x, y in zip(a, b, strict=True)
        )
    if isinstance(a, dict) and isinstance(b, dict):
        pair = (id(a), id(b))
        if pair in seen:
            return True
        if set(a) != set(b):
            return False
        return all(_equal(a[key], b[key], seen | {pair}) for key in a)
    if isinstance(a, datetime.date) or isinstance(b, datetime.date):
        return _canonical(a) == _canonical(b)
    return type(a) is type(b) and _canonical(a) == _canonical(b)


def _numbers_equal(a: int | float, b: int | float) -> bool:
    """Two ints exactly; with a float on either side, both as doubles.

    An int with no double at all falls back to the exact comparison, where it
    can never equal a finite float; two NaNs read as one value.
    """
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    try:
        first, second = float(a), float(b)
    except OverflowError:
        return a == b
    if math.isnan(first) and math.isnan(second):
        return True
    return first == second


def _canonical(value: object) -> object:
    """One raw value's canonical form.

    Ints stay ints, a float is its ``repr`` (one spelling per double, so two
    spellings render identically), a date its ISO string, and mappings recurse
    with keys sorted so rendering never depends on the file's order. Two
    non-string keys of one ``repr`` collapse (:func:`_key_text`), and anything
    else renders by its ``repr``, judged by nobody; the form is JSON-safe.
    """
    return _canonical_value(value, frozenset(), _source_number)


def _canonical_value(
    value: object,
    visiting: frozenset[int],
    number: Callable[[int | float], object],
) -> object:
    """The canonical walk; ``visiting`` holds the containers on this path.

    ``number`` is the spelling the walk reads every int and float with: the
    source form for the rendered values, the double it denotes for an
    identity.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return number(value)
    if isinstance(value, str):
        return value
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical_value(item, visiting, number) for item in value), key=repr
        )
    if isinstance(value, (dict, list)):
        if id(value) in visiting:
            return _RECURSIVE
        nested = visiting | {id(value)}
        if isinstance(value, dict):
            keys = sorted(value, key=_key_text)
            return {
                _key_text(key): _canonical_value(value[key], nested, number)
                for key in keys
            }
        return [_canonical_value(item, nested, number) for item in value]
    return repr(value)


def _source_number(value: int | float) -> object:
    return repr(value) if isinstance(value, float) else value


def _double_number(value: int | float) -> object:
    """The entry-identity spelling: every number as the double it denotes.

    ``json.dumps`` writes a float through ``float.__repr__``, so the key
    carries one spelling for every way of writing a magnitude (signed zero
    and NaN excepted); an int with no double keeps its own digits.
    """
    try:
        return float(value)
    except OverflowError:
        return value


def _key_text(key: object) -> str:
    """A mapping key's canonical text: strings as themselves, rest by ``repr``.

    The text is not injective: ``1`` collapses onto ``"1"``, so two such keys
    in one mapping read as one. Only a malformed mapping reaches it; every
    key the format names is a string.
    """
    return key if isinstance(key, str) else repr(key)
