"""The registry-to-models lockstep: four assertions, one contract.

The registry and the models never read each other, so this file is the bind.
The consistency lockstep is pinned here too.
"""

from typing import Any, cast, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from gpai_docs.lint.consistency import RULES
from gpai_docs.models import (
    DateValue,
    NumberValue,
    TextListValue,
    TextValue,
    UrlValue,
)
from gpai_docs.models.annex_xi import (
    AnnexXI,
    ComputationalResources,
    EnergyConsumption,
)
from gpai_docs.models.annex_xii import AnnexXII
from gpai_docs.models.leaves import Model
from gpai_docs.registry import load
from gpai_docs.registry.models import _RULE_TAG

SECTION_MODELS: dict[str, type[Model]] = {
    "annex_xi": AnnexXI,
    "annex_xii": AnnexXII,
}

# Each tag's (valid, invalid) sample, the shape read off the format table.
# The pair differs only in the one wrong thing the tag refuses, so a reading
# that cannot tell them apart would be vacuous.
TAG_HANDLERS: dict[str, tuple[object, object]] = {
    "type:text": ("An ordinary sentence.", 5),
    "type:text-list": (["first", "second"], "first"),
    "type:number": (2.3e25, True),
    "type:date": ("2026-07-20", "2026-13-01"),
    "type:url": ("https://example.org/model", "example.org/model"),
    "type:compute": (
        {
            "training_flop": 2.3e25,
            "estimation_method": "hardware counters",
            "training_time": "30 days",
        },
        {"training_flop": "2.3e+25"},
    ),
    "type:energy": (
        {
            "training": {"amount": 1200, "unit": "MWh", "method": "metered"},
            "inference": {
                "amount": 8.1e18,
                "unit": "FLOP",
                "method": "benchmarked",
            },
        },
        {"training": {"amount": "1200", "unit": "MWh"}},
    ),
}

# The model reading of each tag (assertion 3): the pydantic type
# that consumes a value with that tag. The five leaves are the format
# vocabulary the tags name; the two structured tags are read by their element
# models.
MODEL_READING: dict[str, TypeAdapter[Any]] = {
    "type:text": TypeAdapter(TextValue),
    "type:text-list": TypeAdapter(TextListValue),
    "type:number": TypeAdapter(NumberValue),
    "type:date": TypeAdapter(DateValue),
    "type:url": TypeAdapter(UrlValue),
    "type:compute": TypeAdapter(ComputationalResources),
    "type:energy": TypeAdapter(EnergyConsumption),
}

# Counts, not the id list: the full 25-id literal lives in
# tests/test_registry_data.py, and the tests directory is no package, so
# nothing clean imports it here. The shape (assertion 4): fourteen
# Annex XI ids (eleven Section 1 points, three Section 2 items), eleven XII.
EXPECTED_XI_COUNT = 14
EXPECTED_XII_COUNT = 11

# The ids carrying at least one document-scoped catalogue entry.
# ``compute.reporting`` and ``record.completeness`` each also carry a second
# entry sharing the id, which is why scoping is read off entries, not ids.
DOCUMENT_SCOPED_RULE_IDS = {
    "compute.reporting",
    "modification.one-third",
    "record.completeness",
}


def _section_and_name(model_field: str) -> tuple[str, str]:
    section, _, name = model_field.partition(".")
    return section, name


def _element_class(section: str, name: str) -> type[Any]:
    """The ``X`` of a section field's ``X | None`` model annotation."""
    annotation = SECTION_MODELS[section].model_fields[name].annotation
    assert annotation is not None
    arms = [arg for arg in get_args(annotation) if arg is not type(None)]
    assert len(arms) == 1, annotation
    return cast(type[Any], arms[0])


def test_every_registry_model_field_resolves_to_its_section_model() -> None:
    # Assertion 1: registry to model, exact names.
    for field in load().fields:
        section, name = _section_and_name(field.model_field)
        assert section in SECTION_MODELS, field.id
        assert name in SECTION_MODELS[section].model_fields, field.id


def test_every_section_model_field_maps_back_to_a_registry_entry() -> None:
    # Assertion 2: model to registry, no orphaned model field.
    mapped = {field.model_field for field in load().fields}
    for section, model in SECTION_MODELS.items():
        for name in model.model_fields:
            assert f"{section}.{name}" in mapped, (section, name)


def test_every_element_model_carries_its_registry_id_and_label() -> None:
    # A model field "claims a registry id" through its schema title (and its
    # docstring's description), so the exported schema is self-describing.
    for field in load().fields:
        section, name = _section_and_name(field.model_field)
        schema = TypeAdapter(_element_class(section, name)).json_schema()
        assert schema["title"] == field.id, field.id
        assert schema["description"] == field.label, field.id


def test_the_tag_table_is_exactly_the_grammar_vocabulary() -> None:
    # Assertion 3, the literal totality pin: the table's keys are
    # the seven alternatives, no more and no fewer.
    assert set(TAG_HANDLERS) == {
        "type:text",
        "type:text-list",
        "type:number",
        "type:date",
        "type:url",
        "type:compute",
        "type:energy",
    }
    assert len(TAG_HANDLERS) == 7
    assert set(MODEL_READING) == set(TAG_HANDLERS)


def test_every_table_tag_is_accepted_by_the_registry_grammar() -> None:
    # Assertion 3: the grammar is single-sourced from the registry,
    # so a table tag the registry would refuse is a defect here.
    for tag in TAG_HANDLERS:
        assert _RULE_TAG.fullmatch(tag), tag


def test_every_shipped_type_tag_has_a_table_row() -> None:
    # Assertion 3: the registered direction. A tag a field uses
    # must have a row; a run that finds no typed element at all is a defect
    # too, not a vacuously green lockstep.
    used = {
        tag for field in load().fields for tag in field.rules if tag.startswith("type:")
    }
    assert used
    assert used <= set(TAG_HANDLERS)


@pytest.mark.parametrize("tag", sorted(TAG_HANDLERS))
def test_every_tag_has_a_model_reading(tag: str) -> None:
    valid, invalid = TAG_HANDLERS[tag]
    # The valid sample validates; the invalid one is refused, never coerced:
    # that is what the tag's shape means in the models.
    MODEL_READING[tag].validate_python(valid)
    with pytest.raises(ValidationError):
        MODEL_READING[tag].validate_python(invalid)


def test_every_element_reads_its_tags_samples_through_its_own_model() -> None:
    # The element's own model is what the typed lint pass validates it with,
    # so a retag leaving tag and model disagreeing (compute's mapping on a
    # text element, say) fails here instead of staying green.
    for field in load().fields:
        section, name = _section_and_name(field.model_field)
        reader = TypeAdapter(_element_class(section, name))
        for tag in field.rules:
            if tag not in TAG_HANDLERS:
                continue
            valid, invalid = TAG_HANDLERS[tag]
            reader.validate_python(valid)
            with pytest.raises(ValidationError):
                reader.validate_python(invalid)


def test_the_expected_id_list_still_holds() -> None:
    # Assertion 4: fourteen Annex XI ids (eleven Section 1 points
    # and three Section 2 items) and eleven Annex XII ids, partitioning the
    # registry with nothing doubled or left over.
    registry = load()
    xi = [field.id for field in registry.fields if field.annex == "XI"]
    xii = [field.id for field in registry.fields if field.annex == "XII"]
    assert len(xi) == EXPECTED_XI_COUNT
    assert len(xii) == EXPECTED_XII_COUNT
    assert set(xi).isdisjoint(xii)
    assert sorted(set(xi) | set(xii)) == sorted(registry.by_id)


def _shipped_consistency_ids() -> set[str]:
    """The ids the shipped ``fields.yaml`` names as ``consistency:`` tags."""
    return {
        tag.removeprefix("consistency:")
        for field in load().fields
        for tag in field.rules
        if tag.startswith("consistency:")
    }


def test_every_shipped_consistency_tag_resolves_to_an_element_rule() -> None:
    # Every ``consistency:<id>`` tag a field carries names at least
    # one element-scoped catalogue entry, so the registry never announces a
    # rule the engine does not run. A run that finds no consistency tag at
    # all is a defect too, not a vacuously green lockstep.
    tagged = _shipped_consistency_ids()
    assert tagged
    element_ids = {rule.id for rule in RULES if rule.scope == "element"}
    assert tagged <= element_ids


def test_every_element_scoped_rule_id_is_a_shipped_consistency_tag() -> None:
    # The other direction: an element-scoped entry names a registry
    # field through its tag, so an entry the registry does not tag is a rule
    # bound to no field, the orphan the lockstep exists to catch.
    element_ids = {rule.id for rule in RULES if rule.scope == "element"}
    assert element_ids
    assert element_ids <= _shipped_consistency_ids()


def test_only_the_known_ids_carry_a_document_scoped_entry() -> None:
    # The exact list: document-scoped entries belong to these ids and no
    # others. ``compute.reporting``'s element entry carries a tag as well, and
    # ``record.completeness`` carries two document entries, so the set is read
    # off entries (which id has a document-scoped one), never off the id's
    # tag.
    document_ids = {rule.id for rule in RULES if rule.scope == "document"}
    assert document_ids == DOCUMENT_SCOPED_RULE_IDS


def test_every_rule_basis_form_resolves_to_a_registry_row() -> None:
    # A rule's Form basis is registry data, not a code copy: the row
    # id must exist in ``form.yaml`` and the label must be that row's label
    # exactly, the way a cited source resolves. The bases must be non-empty,
    # or the binding would be vacuously green.
    rows = {row.row: row.label for row in load().form.rows}
    bases = [entry for rule in RULES for entry in rule.basis_forms]
    assert bases
    for row_id, label in bases:
        assert row_id in rows, row_id
        assert rows[row_id] == label, (row_id, label)
