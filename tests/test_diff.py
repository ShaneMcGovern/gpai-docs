"""The registry-driven diff engine and its renderers.

Pins typed equality across spellings, the index-aligned records reading, the
format's absence reading (null, "", [] and a missing key all read as absent),
registry order, and the engine's no-judgement rule: validity is lint's story.
"""

import copy
import datetime
import sys
from pathlib import Path

import pytest

from gpai_docs import cli
from gpai_docs.diff import (
    _ABSENT,
    FieldChange,
    _canonical,
    changes_json,
    changes_markdown,
    diff_documents,
    render_changes,
    typed_equal,
)
from gpai_docs.documents import Document, load_document
from gpai_docs.registry import Registry, load
from gpai_docs.registry.models import Field

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "model-docs-example.yaml"

# Every element the shipped registry names, so the completeness pin below runs
# one case per field and a forgotten field fails by name.
REGISTRY_FIELD_IDS = [field.id for field in load().fields]

XI_LICENCE = "annex_xi.licence"
XI_TRAINING_DATA = "annex_xi.training_data"
XI_COMPUTE = "annex_xi.computational_resources"
XI_ENERGY = "annex_xi.energy_consumption"
XII_LICENCE = "annex_xii.licence"

# One notification entry, written twice over: an edited copy is a change
# while a respelled one (an int against its double) is not.
NOTIFICATION = {
    "compute_flop": 2.5e25,
    "aware_on": "2026-04-20",
    "notified_on": "2026-04-30",
}

# What a document does not carry at all, told apart from the empty value.
_MISSING = object()


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


def test_identical_documents_carry_no_change(registry: Registry) -> None:
    # Two independent loads of the shipped example read alike in every
    # registry element and in the notification record, so nothing changed.
    assert (
        diff_documents(load_document(EXAMPLE), load_document(EXAMPLE), registry) == []
    )


def test_a_numeric_respelling_is_no_change(registry: Registry) -> None:
    # `1` equals `1.0`: the value is the number, never its spelling.
    changes = diff_documents(
        Document(
            values={"annex_xi": {"computational_resources": {"training_flop": 1}}}
        ),
        Document(
            values={"annex_xi": {"computational_resources": {"training_flop": 1.0}}}
        ),
        registry,
    )

    assert changes == []


def test_a_float_equals_the_double_its_int_spelling_denotes() -> None:
    # The checks' double-precision precedent: `2.3e+25` and its int spelling
    # 23000000000000000000000000 are one magnitude, and so are the exact int
    # 10**25 and the double it converts to: the int reads as that double.
    assert typed_equal(2.3e25, 23000000000000000000000000)
    assert typed_equal(10**25, 1e25)


def test_two_ints_compare_exactly(registry: Registry) -> None:
    # Only a float pulls the comparison to double precision: two ints keep
    # every digit, so 10**25 + 1 is the real difference it is written as.
    changes = diff_documents(
        Document(
            values={"annex_xi": {"computational_resources": {"training_flop": 10**25}}}
        ),
        Document(
            values={
                "annex_xi": {"computational_resources": {"training_flop": 10**25 + 1}}
            }
        ),
        registry,
    )

    assert changes == [
        FieldChange(
            location=XI_COMPUTE,
            kind="changed",
            before={"training_flop": 10**25},
            after={"training_flop": 10**25 + 1},
        )
    ]


def test_two_nans_read_as_one_value() -> None:
    # The writer's value is the writer's value: a NaN-carrying document must
    # not differ from itself, so two NaNs compare equal while a NaN against a
    # number (or another kind) is the difference it is written as.
    nan = float("nan")

    assert typed_equal(nan, float("nan"))
    assert not typed_equal(nan, 1.0)
    assert not typed_equal(1.0, nan)
    assert not typed_equal(nan, "nan")


def test_an_int_with_no_double_still_compares(registry: Registry) -> None:
    # An int beyond the double range (10**400) has no double reading; it
    # still compares, and never equals a finite float.
    changes = diff_documents(
        Document(
            values={"annex_xi": {"computational_resources": {"training_flop": 10**400}}}
        ),
        Document(
            values={"annex_xi": {"computational_resources": {"training_flop": 1e308}}}
        ),
        registry,
    )

    assert [change.kind for change in changes] == ["changed"]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("2.3e+25", 2.3e25),
        ("1", 1),
        (True, 1),
        (False, 0),
        (None, ""),
        (b"x", "b'x'"),
    ],
    ids=["numeric-string", "string", "bool-true", "bool-false", "null", "bytes"],
)
def test_a_value_never_coerces_into_another_kind(a: object, b: object) -> None:
    # diff never judges and never coerces: a value of the wrong kind (a
    # numeric string, a bool in a number slot, bytes) is a value of its own
    # kind, so it differs from the value it might have been read as.
    assert not typed_equal(a, b)
    assert not typed_equal(b, a)


def test_strings_compare_exactly() -> None:
    assert typed_equal("Apache-2.0", "Apache-2.0")
    assert not typed_equal("Apache-2.0", "apache-2.0")
    assert not typed_equal("1.0", "1")


def test_dates_compare_by_value() -> None:
    # Dates are strings in practice and compare as strings, with no
    # re-parsing of a near-date. A library user's real date object denotes the
    # same value as its ISO form.
    assert typed_equal("2026-04-20", "2026-04-20")
    assert typed_equal(datetime.date(2026, 4, 20), "2026-04-20")
    assert not typed_equal("2026-4-20", "2026-04-20")
    assert not typed_equal("2026-04-20", "2026-04-21")


def test_lists_compare_element_wise_in_order() -> None:
    # No registry field is a list in this pack, but diff never judges: a
    # malformed list diffs by its raw reading, order and element kinds
    # included, and nested numbers read under the same typed equality.
    assert typed_equal([1, 2], [1, 2])
    assert typed_equal([1], [1.0])
    assert not typed_equal([1, 2], [2, 1])
    assert not typed_equal([1], [1, 2])
    assert not typed_equal([1], ["1"])


def test_mappings_compare_by_canonical_deep_equality() -> None:
    # Mapping key order is free; the values recurse under the same reading.
    assert typed_equal({"a": 1, "b": 2.0}, {"b": 2, "a": 1.0})
    assert not typed_equal({"a": 1}, {"a": 1, "b": 2})
    assert not typed_equal({"a": 1}, {"a": "1"})
    assert not typed_equal({"a": 1}, {"b": 1})


def test_a_structured_element_change_is_one_change_at_the_element(
    registry: Registry,
) -> None:
    # The element is the unit: a leaf edit inside computational resources is
    # one changed change carrying the whole mapping, old and new.
    old_value = {"training_flop": 2.5e25, "estimation_method": "as published"}
    new_value = {
        "training_flop": 2.5e25,
        "estimation_method": "as measured",
        "training_time": "21 days",
    }

    changes = diff_documents(
        Document(values={"annex_xi": {"computational_resources": dict(old_value)}}),
        Document(values={"annex_xi": {"computational_resources": dict(new_value)}}),
        registry,
    )

    assert changes == [
        FieldChange(
            location=XI_COMPUTE, kind="changed", before=old_value, after=new_value
        )
    ]


def test_a_nested_respelling_inside_an_element_reads_alike(registry: Registry) -> None:
    # Typed equality reaches every leaf of a structured element: the energy
    # arm's `1500` and `1500.0` are one amount, and key order is free.
    changes = diff_documents(
        Document(
            values={
                "annex_xi": {
                    "energy_consumption": {
                        "training": {"amount": 1500, "unit": "MWh"},
                        "inference": {"amount": 8.1e18},
                    }
                }
            }
        ),
        Document(
            values={
                "annex_xi": {
                    "energy_consumption": {
                        "inference": {"amount": 8100000000000000000},
                        "training": {"unit": "MWh", "amount": 1500.0},
                    }
                }
            }
        ),
        registry,
    )

    assert changes == []


def test_a_change_deep_inside_an_element_reports_the_element(
    registry: Registry,
) -> None:
    # The same reach, the other way: an edit two mappings down (the energy
    # element's inference arm) is one change at the element's own path.
    old_value = {"training": {"amount": 1500, "unit": "MWh"}}
    new_value = {"training": {"amount": 1500, "unit": "MWh", "method": "measured"}}

    changes = diff_documents(
        Document(values={"annex_xi": {"energy_consumption": dict(old_value)}}),
        Document(values={"annex_xi": {"energy_consumption": dict(new_value)}}),
        registry,
    )

    assert changes == [
        FieldChange(
            location=XI_ENERGY, kind="changed", before=old_value, after=new_value
        )
    ]


@pytest.mark.parametrize(
    "empty",
    [None, "", [], _MISSING],
    ids=["null", "empty-string", "empty-list", "missing-key"],
)
def test_emptying_a_field_is_a_removal(registry: Registry, empty: object) -> None:
    # `null`, the empty string, the empty list and the written-out key alike
    # read as absent, so a field emptied is a removal, and the
    # absent side is the sentinel, never None.
    values: dict[str, object] = {} if empty is _MISSING else {"licence": empty}

    changes = diff_documents(
        Document(values={"annex_xi": {"licence": "Apache-2.0"}}),
        Document(values={"annex_xi": values}),
        registry,
    )

    assert changes == [
        FieldChange(location=XI_LICENCE, kind="removed", before="Apache-2.0")
    ]
    assert changes[0].after is _ABSENT
    assert changes[0].after is not None


@pytest.mark.parametrize(
    "absent",
    [None, "", [], _MISSING],
    ids=["null", "empty-string", "empty-list", "missing-key"],
)
def test_filling_an_absent_field_is_an_addition(
    registry: Registry, absent: object
) -> None:
    # The other direction: a field the old document does not answer, by any
    # of the absence spellings, is added when the new one holds a value.
    values: dict[str, object] = {} if absent is _MISSING else {"licence": absent}

    changes = diff_documents(
        Document(values={"annex_xi": values}),
        Document(values={"annex_xi": {"licence": "Apache-2.0"}}),
        registry,
    )

    assert changes == [
        FieldChange(location=XI_LICENCE, kind="added", after="Apache-2.0")
    ]
    assert changes[0].before is _ABSENT
    assert changes[0].before is not None


def test_two_absence_spellings_are_no_change(registry: Registry) -> None:
    # An absent side is absent however it is written: null against a missing
    # key is no change at all, and neither is an element mapping with no
    # non-null leaf beneath it.
    assert (
        diff_documents(
            Document(values={"annex_xi": {"licence": None}}),
            Document(values={"annex_xi": {}}),
            registry,
        )
        == []
    )
    assert (
        diff_documents(
            Document(
                values={
                    "annex_xi": {"computational_resources": {"training_flop": None}}
                }
            ),
            Document(values={"annex_xi": {}}),
            registry,
        )
        == []
    )


def test_a_section_the_loader_would_refuse_reads_as_absent(registry: Registry) -> None:
    # A hand-built Document can hold a non-mapping section the loader refuses;
    # diff never judges it: every field reads absent and nothing raises.
    assert (
        diff_documents(
            Document(values={"annex_xi": "oops"}),
            Document(values={}),
            registry,
        )
        == []
    )


def test_keys_the_registry_does_not_name_are_ignored(registry: Registry) -> None:
    # diff walks the registry, never the raw key set: a misspelt annex key
    # and an unknown top-level section are lint's findings, not changes.
    assert (
        diff_documents(
            Document(
                values={
                    "annex_xi": {"training_datasets": "the datasets"},
                    "not_a_section": {"licence": "fine"},
                }
            ),
            Document(
                values={
                    "annex_xi": {"training_datasets": "other datasets"},
                    "not_a_section": {"licence": "still fine"},
                }
            ),
            registry,
        )
        == []
    )


def test_changes_report_in_registry_order(registry: Registry) -> None:
    # The report order is the registry's, not the document's: annex_xii.licence
    # is written first below and its change still comes after Annex XI's, with
    # the records sections last.
    changes = diff_documents(
        Document(
            values={
                "annex_xii": {"licence": "old licence"},
                "annex_xi": {
                    "training_data": "old datasets",
                    "computational_resources": {"training_flop": 1},
                },
            },
            records={"notifications": [{"compute_flop": 1}]},
        ),
        Document(
            values={
                "annex_xi": {
                    "computational_resources": {"training_flop": 2},
                    "training_data": "new datasets",
                },
                "annex_xii": {"licence": "new licence"},
            },
            records={"notifications": [{"compute_flop": 2}]},
        ),
        registry,
    )

    assert [(change.location, change.kind) for change in changes] == [
        (XI_TRAINING_DATA, "changed"),  # XI.1.2.c
        (XI_COMPUTE, "changed"),  # XI.1.2.d
        (XII_LICENCE, "changed"),  # XII.1.h
        ("notifications[0].compute_flop", "changed"),
    ]


def test_a_marker_change_is_one_changed_change(registry: Registry) -> None:
    # The systemic-risk marker is a top-level
    # attribute the registry conditions Section 2 on, and diff compares it
    # directly: one `changed` change, with neither side absent.
    changes = diff_documents(
        Document(values={}), Document(values={"systemic_risk": True}), registry
    )

    assert changes == [
        FieldChange(location="systemic_risk", kind="changed", before=False, after=True)
    ]
    assert diff_documents(
        Document(values={"systemic_risk": True}), Document(values={}), registry
    ) == [
        FieldChange(location="systemic_risk", kind="changed", before=True, after=False)
    ]


def test_an_absent_marker_and_false_read_alike(registry: Registry) -> None:
    # The format's absent means false: spelling the default out is no change
    # at all, in either direction.
    assert (
        diff_documents(
            Document(values={}), Document(values={"systemic_risk": False}), registry
        )
        == []
    )
    assert (
        diff_documents(
            Document(values={"systemic_risk": False}),
            Document(values={"systemic_risk": False}),
            registry,
        )
        == []
    )


def test_a_malformed_marker_compares_as_itself(registry: Registry) -> None:
    # diff never judges: a non-boolean marker is the typed pass's malformed
    # finding, and here it compares as the raw value it is. Equal spellings
    # are no change, and a null marker is not the absent (false) one.
    assert (
        diff_documents(
            Document(values={"systemic_risk": "yes"}),
            Document(values={"systemic_risk": "yes"}),
            registry,
        )
        == []
    )
    assert diff_documents(
        Document(values={"systemic_risk": None}), Document(values={}), registry
    ) == [
        FieldChange(location="systemic_risk", kind="changed", before=None, after=False)
    ]


def test_the_marker_change_reports_after_the_fields_before_the_records(
    registry: Registry,
) -> None:
    # The marker sits after every registry field's
    # element and before the records sections' entries.
    changes = diff_documents(
        Document(
            values={"annex_xi": {"licence": "old licence"}},
            records={"notifications": [{"compute_flop": 1}]},
        ),
        Document(
            values={"annex_xi": {"licence": "new licence"}, "systemic_risk": True},
            records={"notifications": [{"compute_flop": 2}]},
        ),
        registry,
    )

    assert [(change.location, change.kind) for change in changes] == [
        (XI_LICENCE, "changed"),
        ("systemic_risk", "changed"),
        ("notifications[0].compute_flop", "changed"),
    ]


def _type_tag(field: Field) -> str:
    """The field's one declared ``type:`` tag, without its prefix."""
    tags = [rule for rule in field.rules if rule.startswith("type:")]
    assert len(tags) == 1, field.model_field
    return tags[0].removeprefix("type:")


def _revised_text(value: object) -> str:
    """One text value grown by a suffix: the pin's deliberate text edit."""
    assert isinstance(value, str)
    return value + " (revised)"


def _mutated(field: Field, value: object) -> object:
    """One by-value-different mutation of ``value``, per ``field``'s type.

    It must differ under the diff's own typed equality, so a missed field
    cannot be confused with a no-op: compute mutates ``training_time``
    because ``training_flop``'s double would not move by 1.
    """
    tag = _type_tag(field)
    if tag == "text":
        return _revised_text(value)
    if tag == "number":
        assert isinstance(value, (int, float))
        return value + 1
    if tag == "compute":
        assert isinstance(value, dict)
        mapping: dict[str, object] = dict(value)
        mapping["training_time"] = _revised_text(mapping["training_time"])
        return mapping
    if tag == "energy":
        assert isinstance(value, dict)
        training = value["training"]
        assert isinstance(training, dict)
        amount = training["amount"]
        assert isinstance(amount, int)
        mapping = {**value, "training": {**training, "amount": amount + 1}}
        return mapping
    raise AssertionError(f"the pin has no mutation for {tag!r} on {field.id}")


@pytest.mark.parametrize("field_id", REGISTRY_FIELD_IDS)
def test_a_change_in_every_registry_model_field_is_reported_once(
    registry: Registry, field_id: str
) -> None:
    # The registry is the diff's single source: the complete fixture answers
    # every element it names, so one deliberate, by-value-different edit is
    # exactly one `changed` change at that field's path. A field the engine
    # forgot fails here, by name.
    field = registry.by_id[field_id]
    fixture = load_document(EXAMPLE)
    mutated = Document(
        values=copy.deepcopy(fixture.values),
        records=copy.deepcopy(fixture.records),
    )
    section, _, key = field.model_field.partition(".")
    section_values = mutated.values[section]
    assert isinstance(section_values, dict)
    before = section_values[key]
    after = _mutated(field, before)
    section_values[key] = after

    changes = diff_documents(fixture, mutated, registry)

    assert changes == [
        FieldChange(
            location=field.model_field, kind="changed", before=before, after=after
        )
    ]


def test_equal_entries_in_any_key_order_are_no_change(registry: Registry) -> None:
    # Equal-length lists compare index-aligned, and an entry's identity is
    # canonical: the same entries at the same indices (the keys inside an
    # entry in another order) are no change at all, in either section.
    modification = {"description": "fine-tuned on licensed data"}

    changes = diff_documents(
        Document(
            values={},
            records={
                "notifications": [dict(NOTIFICATION)],
                "modifications": [dict(modification)],
            },
        ),
        Document(
            values={},
            records={
                "modifications": [dict(modification)],
                "notifications": [
                    {
                        "notified_on": NOTIFICATION["notified_on"],
                        "aware_on": NOTIFICATION["aware_on"],
                        "compute_flop": NOTIFICATION["compute_flop"],
                    }
                ],
            },
        ),
        registry,
    )

    assert changes == []


def test_an_edited_record_entry_reports_the_field(registry: Registry) -> None:
    # Equal-length lists compare index-aligned, so an edited
    # entry is one per-field change at `<section>[i].<field>` carrying the old
    # and new values, never a remove+add pair.
    edited = {**NOTIFICATION, "notified_on": "2026-05-01"}

    changes = diff_documents(
        Document(values={}, records={"notifications": [dict(NOTIFICATION)]}),
        Document(values={}, records={"notifications": [dict(edited)]}),
        registry,
    )

    assert changes == [
        FieldChange(
            location="notifications[0].notified_on",
            kind="changed",
            before="2026-04-30",
            after="2026-05-01",
        )
    ]


def test_every_differing_field_reports_in_canonical_key_order(
    registry: Registry,
) -> None:
    # One change per differing field, in the canonical (sorted) key order
    # rather than the document's own, and a field respelled between the
    # spellings of one double (compute_flop `1` against `1.0`) is no change.
    before = {
        "compute_flop": 1,
        "aware_on": "2026-04-20",
        "notified_on": "2026-04-30",
    }
    after = {
        "notified_on": "2026-05-01",
        "compute_flop": 1.0,
        "aware_on": "2026-08-01",
    }

    changes = diff_documents(
        Document(values={}, records={"notifications": [dict(before)]}),
        Document(values={}, records={"notifications": [dict(after)]}),
        registry,
    )

    assert changes == [
        FieldChange(
            location="notifications[0].aware_on",
            kind="changed",
            before="2026-04-20",
            after="2026-08-01",
        ),
        FieldChange(
            location="notifications[0].notified_on",
            kind="changed",
            before="2026-04-30",
            after="2026-05-01",
        ),
    ]


def test_an_untouched_neighbour_at_its_index_is_no_change(registry: Registry) -> None:
    # Index alignment compares pairs, not lists: the untouched pair at index
    # 0 contributes nothing, so the edit beside it reports alone.
    changes = diff_documents(
        Document(values={}, records={"notifications": [{"a": 1}, {"b": "x"}]}),
        Document(values={}, records={"notifications": [{"a": 1}, {"b": "y"}]}),
        registry,
    )

    assert changes == [
        FieldChange(
            location="notifications[1].b", kind="changed", before="x", after="y"
        )
    ]


def test_a_key_set_change_falls_back_to_remove_and_add(registry: Registry) -> None:
    # A pair whose key sets differ is not field-diffable, so the documented
    # remove+add reports it at the entry's index, in both directions.
    extended = {**NOTIFICATION, "note": "an extra key"}

    assert diff_documents(
        Document(values={}, records={"notifications": [dict(NOTIFICATION)]}),
        Document(values={}, records={"notifications": [dict(extended)]}),
        registry,
    ) == [
        FieldChange(location="notifications[0]", kind="removed", before=NOTIFICATION),
        FieldChange(location="notifications[0]", kind="added", after=extended),
    ]
    assert diff_documents(
        Document(values={}, records={"notifications": [dict(extended)]}),
        Document(values={}, records={"notifications": [dict(NOTIFICATION)]}),
        registry,
    ) == [
        FieldChange(location="notifications[0]", kind="removed", before=extended),
        FieldChange(location="notifications[0]", kind="added", after=NOTIFICATION),
    ]


def test_a_non_mapping_pair_falls_back_to_remove_and_add(registry: Registry) -> None:
    # diff never judges an entry the loader would refuse: a non-mapping pair
    # (here a string against a mapping) cannot be field-diffed, so the
    # fallback reports the old entry removed and the new one added.
    changes = diff_documents(
        Document(values={}, records={"modifications": ["the old shape"]}),
        Document(
            values={}, records={"modifications": [{"description": "the new shape"}]}
        ),
        registry,
    )

    assert changes == [
        FieldChange(
            location="modifications[0]", kind="removed", before="the old shape"
        ),
        FieldChange(
            location="modifications[0]",
            kind="added",
            after={"description": "the new shape"},
        ),
    ]


def test_reordered_equal_entries_fall_back_to_remove_and_add(
    registry: Registry,
) -> None:
    # With equal lengths the comparison is index-aligned, so two equal entries
    # swapped across the lists are unequal at every index and the section
    # falls back to remove+add, never the old silent multiset match. The
    # entries' key sets differ; a same-key-set reorder is field-wise (below).
    first = {"compute_flop": 1}
    second = {"training_flop": 2}

    changes = diff_documents(
        Document(values={}, records={"notifications": [dict(first), dict(second)]}),
        Document(values={}, records={"notifications": [dict(second), dict(first)]}),
        registry,
    )

    assert changes == [
        FieldChange(location="notifications[0]", kind="removed", before=first),
        FieldChange(location="notifications[1]", kind="removed", before=second),
        FieldChange(location="notifications[0]", kind="added", after=second),
        FieldChange(location="notifications[1]", kind="added", after=first),
    ]


def test_reordered_same_key_set_entries_report_field_changes(
    registry: Registry,
) -> None:
    # A same-key-set reorder is field-diffable, so each index reports its own
    # field change. The pin's real point is that a reorder is no longer
    # silent: the v0.1 multiset matcher reported nothing here, while the
    # index-aligned walk reads the swap as the two per-index differences it is.
    first = {"compute_flop": 1}
    second = {"compute_flop": 2}

    changes = diff_documents(
        Document(values={}, records={"notifications": [dict(first), dict(second)]}),
        Document(values={}, records={"notifications": [dict(second), dict(first)]}),
        registry,
    )

    assert changes == [
        FieldChange(
            location="notifications[0].compute_flop",
            kind="changed",
            before=1,
            after=2,
        ),
        FieldChange(
            location="notifications[1].compute_flop",
            kind="changed",
            before=2,
            after=1,
        ),
    ]


def test_one_unfieldable_pair_falls_the_whole_section_back(
    registry: Registry,
) -> None:
    # The fallback applies to the whole section, not to the pair: when any
    # unequal pair is not field-diffable (here the second pair's key sets
    # differ), every unequal index reports remove+add.
    old: list[dict[str, object]] = [{"a": 1, "b": "x"}, {"k": 1}]
    new: list[dict[str, object]] = [{"b": "y", "a": 1}, {"k": 2, "j": 3}]

    changes = diff_documents(
        Document(values={}, records={"notifications": [dict(entry) for entry in old]}),
        Document(values={}, records={"notifications": [dict(entry) for entry in new]}),
        registry,
    )

    assert changes == [
        FieldChange(location="notifications[0]", kind="removed", before=old[0]),
        FieldChange(location="notifications[1]", kind="removed", before=old[1]),
        FieldChange(location="notifications[0]", kind="added", after=new[0]),
        FieldChange(location="notifications[1]", kind="added", after=new[1]),
    ]


def test_a_length_change_keeps_the_multiset_reading(registry: Registry) -> None:
    # Length changes keep the v0.1 multiset behaviour: entries pair by
    # canonical identity wherever they sit, so a list shrunk from the front
    # reports the entry with no partner.
    first = {"compute_flop": 1}
    second = {"compute_flop": 2}

    changes = diff_documents(
        Document(values={}, records={"notifications": [dict(first), dict(second)]}),
        Document(values={}, records={"notifications": [dict(second)]}),
        registry,
    )

    assert changes == [
        FieldChange(location="notifications[0]", kind="removed", before=first)
    ]


def test_a_respelled_record_entry_is_no_change(registry: Registry) -> None:
    # A pair's canonical identity reads numbers uniformly as the doubles they
    # denote, so an entry respelled from the int spelling of its double is no
    # change at all, exactly as an element respelling is not.
    assert (
        diff_documents(
            Document(values={}, records={"notifications": [{"compute_flop": 1}]}),
            Document(values={}, records={"notifications": [{"compute_flop": 1.0}]}),
            registry,
        )
        == []
    )
    assert (
        diff_documents(
            Document(values={}, records={"notifications": [{"compute_flop": 2.3e25}]}),
            Document(
                values={},
                records={
                    "notifications": [{"compute_flop": 23000000000000000000000000}]
                },
            ),
            registry,
        )
        == []
    )


@pytest.mark.parametrize(
    ("old_value", "new_value"),
    [(1, 2), (1, "1.0"), (10**400, 10**401)],
    ids=["other-number", "numeric-string", "beyond-the-double"],
)
def test_a_field_edit_is_a_change_never_a_coercion(
    registry: Registry, old_value: object, new_value: object
) -> None:
    # The uniform canonical reading is not a licence to coerce: a field value
    # edited to another number, to the string that spells it, or to an int no
    # double can hold is one field-level change carrying the raw values.
    changes = diff_documents(
        Document(values={}, records={"notifications": [{"compute_flop": old_value}]}),
        Document(values={}, records={"notifications": [{"compute_flop": new_value}]}),
        registry,
    )

    assert changes == [
        FieldChange(
            location="notifications[0].compute_flop",
            kind="changed",
            before=old_value,
            after=new_value,
        )
    ]


def test_duplicate_entries_count_per_occurrence(registry: Registry) -> None:
    # Identical entries pair up in order, so the surplus copies are the
    # change: one per occurrence, each at its own index.
    assert diff_documents(
        Document(
            values={},
            records={"notifications": [dict(NOTIFICATION), dict(NOTIFICATION)]},
        ),
        Document(values={}, records={"notifications": [dict(NOTIFICATION)]}),
        registry,
    ) == [FieldChange(location="notifications[1]", kind="removed", before=NOTIFICATION)]

    assert diff_documents(
        Document(values={}, records={"notifications": [dict(NOTIFICATION)]}),
        Document(
            values={},
            records={"notifications": [dict(NOTIFICATION), dict(NOTIFICATION)]},
        ),
        registry,
    ) == [FieldChange(location="notifications[1]", kind="added", after=NOTIFICATION)]


def test_a_records_section_only_one_side_carries(registry: Registry) -> None:
    # A document without the section carries no entry, so the other side's
    # entries are removals (or additions, the other way round).
    modification = {"description": "fine-tuned on licensed data"}

    changes = diff_documents(
        Document(values={}, records={"modifications": [dict(modification)]}),
        Document(values={}),
        registry,
    )

    assert changes == [
        FieldChange(location="modifications[0]", kind="removed", before=modification)
    ]


def test_a_records_section_the_loader_would_refuse_has_no_entries(
    registry: Registry,
) -> None:
    # A hand-built Document can hold a records section the loader refuses;
    # diff never judges it: there are simply no entries to compare.
    changes = diff_documents(
        Document(values={}, records={"notifications": "oops"}),
        Document(values={}, records={"notifications": [{"compute_flop": 1}]}),
        registry,
    )

    assert changes == [
        FieldChange(
            location="notifications[0]", kind="added", after={"compute_flop": 1}
        )
    ]


def test_malformed_values_diff_by_their_raw_form(registry: Registry) -> None:
    # A string where the registry says number is not coerced and not judged:
    # the two raw values differ, so the element is changed, and lint is the
    # pass that reports the malformed value itself.
    changes = diff_documents(
        Document(
            values={
                "annex_xi": {"computational_resources": {"training_flop": "2.3e+25"}}
            }
        ),
        Document(
            values={"annex_xi": {"computational_resources": {"training_flop": 2.3e25}}}
        ),
        registry,
    )

    assert changes == [
        FieldChange(
            location=XI_COMPUTE,
            kind="changed",
            before={"training_flop": "2.3e+25"},
            after={"training_flop": 2.3e25},
        )
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1500, 1500),
        (10**400, 10**400),
        (2.5e25, "2.5e+25"),
        (1.0, "1.0"),
        (True, True),
        (False, False),
        ("text", "text"),
        (None, None),
        (datetime.date(2026, 4, 20), "2026-04-20"),
        (datetime.datetime(2026, 4, 20, 12, 30), "2026-04-20T12:30:00"),
        ([1, 2.5, None, "x"], [1, "2.5", None, "x"]),
        ({"b": 1, "a": 2.0}, {"a": "2.0", "b": 1}),
        ({"z", "a"}, ["a", "z"]),
        (b"x", "b'x'"),
        ({1: "one"}, {"1": "one"}),
    ],
)
def test_the_canonical_form_pins_each_value_kind(
    value: object, expected: object
) -> None:
    # Ints stay ints whatever their size; floats keep the repr spelling that
    # round-trips the double; dates render ISO; lists and mappings recurse;
    # a set renders sorted (its order is not its own); anything else renders
    # by its repr, so nothing is ever judged, only shown.
    assert _canonical(value) == expected


def test_the_canonical_form_sorts_mapping_keys() -> None:
    # Mapping key order is free in the reading and pinned in the rendering:
    # sorted, so two spellings of one value render byte-identically.
    canonical = _canonical({"b": 1, "a": 2})

    assert isinstance(canonical, dict)
    assert list(canonical) == ["a", "b"]


def test_a_recursive_alias_does_not_crash_the_comparison() -> None:
    # YAML anchors can make a value reference itself. Equality assumes such
    # a pair equal while it is being compared, and the canonical rendering
    # marks the re-entry, so neither walk traces back.
    old_cycle: list[object] = ["x"]
    old_cycle.append(old_cycle)
    new_cycle: list[object] = ["x"]
    new_cycle.append(new_cycle)
    assert typed_equal(old_cycle, new_cycle)

    old_mapping: dict[str, object] = {}
    old_mapping["self"] = old_mapping
    new_mapping: dict[str, object] = {}
    new_mapping["self"] = new_mapping
    assert typed_equal(old_mapping, new_mapping)

    assert _canonical(old_cycle) == ["x", "<recursive>"]
    assert _canonical(old_mapping) == {"self": "<recursive>"}


def test_a_modification_change_reports_after_the_notifications(
    registry: Registry,
) -> None:
    # The records sections report in the format's own order (RECORDS):
    # notifications before modifications, never the file's order, each
    # equal-length section compared index-aligned and field by field.
    changes = diff_documents(
        Document(
            values={},
            records={
                "modifications": [{"description": "one"}],
                "notifications": [{"compute_flop": 1}],
            },
        ),
        Document(
            values={},
            records={
                "notifications": [{"compute_flop": 2}],
                "modifications": [{"description": "two"}],
            },
        ),
        registry,
    )

    assert [(change.location, change.kind) for change in changes] == [
        ("notifications[0].compute_flop", "changed"),
        ("modifications[0].description", "changed"),
    ]


# --- the renderers ---


def test_render_changes_gives_one_line_per_change() -> None:
    # The sign says the kind, then the path, then the canonical value(s): an
    # addition and a removal show their one side, a change shows both, old
    # before new. Floats ride as their repr spelling, ints as digits, and a
    # mapping as compact JSON with sorted keys.
    changes = [
        FieldChange(location=XI_LICENCE, kind="added", after="Apache-2.0"),
        FieldChange(location=XI_LICENCE, kind="removed", before="Apache-2.0"),
        FieldChange(
            location=XI_COMPUTE,
            kind="changed",
            before={"training_flop": 2.5e25},
            after={"training_flop": 2.5e25, "estimation_method": None},
        ),
    ]

    assert render_changes(changes) == (
        '+ annex_xi.licence: "Apache-2.0"\n'
        '- annex_xi.licence: "Apache-2.0"\n'
        '~ annex_xi.computational_resources: {"training_flop":"2.5e+25"}'
        ' -> {"estimation_method":null,"training_flop":"2.5e+25"}'
    )


def test_render_changes_of_nothing_is_no_output() -> None:
    # An identical pair has nothing to print; the empty rendering is the
    # empty string, never a stray blank line.
    assert render_changes([]) == ""


def test_changes_json_always_carries_both_value_keys() -> None:
    # The payload: location and kind, then from and to, both always
    # present, null where the side is absent, values through the canonical
    # form (a float as the string spelling of its double, an int as digits).
    payload = changes_json(
        [
            FieldChange(location=XI_LICENCE, kind="removed", before="Apache-2.0"),
            FieldChange(location=XI_LICENCE, kind="added", after=2.5e25),
            FieldChange(
                location=XI_COMPUTE,
                kind="changed",
                before={"training_flop": 10**25},
                after={"training_flop": 10**25 + 1},
            ),
        ]
    )

    assert payload == {
        "changes": [
            {
                "location": "annex_xi.licence",
                "kind": "removed",
                "from": "Apache-2.0",
                "to": None,
            },
            {
                "location": "annex_xi.licence",
                "kind": "added",
                "from": None,
                "to": "2.5e+25",
            },
            {
                "location": "annex_xi.computational_resources",
                "kind": "changed",
                "from": {"training_flop": 10**25},
                "to": {"training_flop": 10**25 + 1},
            },
        ]
    }


def test_changes_json_of_nothing_is_the_empty_list() -> None:
    assert changes_json([]) == {"changes": []}


def test_changes_markdown_is_the_change_table() -> None:
    # The table's four columns, a row per change, the payload's null for a
    # side the change does not carry, and the canonical value in each cell.
    changes = [
        FieldChange(location="notifications[0]", kind="added", after=NOTIFICATION),
        FieldChange(
            location=XI_LICENCE, kind="changed", before="Apache-2.0", after="MIT"
        ),
    ]

    assert changes_markdown(changes) == (
        "| location | change | from | to |\n"
        "| --- | --- | --- | --- |\n"
        '| notifications[0] | added | null | {"aware_on":"2026-04-20",'
        '"compute_flop":"2.5e+25","notified_on":"2026-04-30"} |\n'
        '| annex_xi.licence | changed | "Apache-2.0" | "MIT" |'
    )


def test_changes_markdown_of_nothing_is_the_header_table() -> None:
    # A run with no changes still renders a table: the header and the rule,
    # with no rows to follow.
    assert changes_markdown([]) == (
        "| location | change | from | to |\n| --- | --- | --- | --- |"
    )


def test_a_pipe_in_a_value_cannot_break_the_markdown_row() -> None:
    # A document value may hold a table separator; the cell escapes it, so
    # the row keeps its four columns whatever the document spells.
    rendered = changes_markdown(
        [FieldChange(location=XI_LICENCE, kind="added", after="a|b")]
    )

    row = rendered.splitlines()[2]
    assert row == '| annex_xi.licence | added | null | "a\\|b" |'


def test_an_absent_side_reads_null_in_every_rendering() -> None:
    # The engine never builds a change whose kind contradicts its sides, but
    # a hand-built one still has to render deterministically: the absent side
    # reads null, never the private sentinel's repr, which carries an address.
    changes = [FieldChange(location=XI_LICENCE, kind="added")]

    assert render_changes(changes) == "+ annex_xi.licence: null"
    assert changes_json(changes) == {
        "changes": [
            {
                "location": "annex_xi.licence",
                "kind": "added",
                "from": None,
                "to": None,
            }
        ]
    }
    assert changes_markdown(changes).splitlines()[2] == (
        "| annex_xi.licence | added | null | null |"
    )


def test_the_renderers_read_a_documents_own_key_order_the_same_both_ways() -> None:
    # Determinism: the canonical form sorts a mapping's keys, so the same
    # change written in two key orders renders byte-identically in all
    # three forms.
    one_way = FieldChange(
        location=XI_ENERGY,
        kind="changed",
        before={"training": {"amount": 1500, "unit": "MWh"}},
        after={"training": {"unit": "MWh", "amount": 1500}},
    )
    the_other = FieldChange(
        location=XI_ENERGY,
        kind="changed",
        before={"training": {"unit": "MWh", "amount": 1500}},
        after={"training": {"amount": 1500, "unit": "MWh"}},
    )

    assert render_changes([one_way]) == render_changes([the_other])
    assert changes_json([one_way]) == changes_json([the_other])
    assert changes_markdown([one_way]) == changes_markdown([the_other])


# --- the CLI's JSON bytes ---


def test_diff_json_bytes_pin_the_key_order_and_the_indent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The payload's bytes are part of its contract: every entry keeps the
    # location/kind/from/to order and the document json.dumps' indent=2, so
    # a dict reorder or a sort_keys=True regression cannot land silently
    # behind a json.loads round-trip that would hide both.
    old = tmp_path / "old.yaml"
    old.write_text('schema: 1\nannex_xi:\n  licence: "Apache-2.0"\n', encoding="utf-8")
    new = tmp_path / "new.yaml"
    new.write_text('schema: 1\nannex_xi:\n  licence: "MIT"\n', encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["gpai-docs", "diff", str(old), str(new), "--json"]
    )

    code = cli.main()

    assert code == 1
    assert capsys.readouterr().out == (
        "{\n"
        '  "changes": [\n'
        "    {\n"
        '      "location": "annex_xi.licence",\n'
        '      "kind": "changed",\n'
        '      "from": "Apache-2.0",\n'
        '      "to": "MIT"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def test_diff_json_shapes_a_field_level_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The location shape through the CLI's JSON bytes: a record field change
    # reads `notifications[0].notified_on`, kind `changed`, both values
    # canonical, the shape a consumer keys on.
    old = tmp_path / "old.yaml"
    old.write_text(
        'schema: 1\nnotifications:\n  - notified_on: "2026-04-30"\n',
        encoding="utf-8",
    )
    new = tmp_path / "new.yaml"
    new.write_text(
        'schema: 1\nnotifications:\n  - notified_on: "2026-05-01"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv", ["gpai-docs", "diff", str(old), str(new), "--json"]
    )

    code = cli.main()

    assert code == 1
    assert capsys.readouterr().out == (
        "{\n"
        '  "changes": [\n'
        "    {\n"
        '      "location": "notifications[0].notified_on",\n'
        '      "kind": "changed",\n'
        '      "from": "2026-04-30",\n'
        '      "to": "2026-05-01"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
