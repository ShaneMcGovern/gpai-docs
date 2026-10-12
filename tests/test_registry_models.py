"""Tests for the registry models and loader.

``tests/fixtures/registry_mini`` is the one valid instance of all four data
files: a registry with an extract-mode and an artifact-mode source, one field
whose ``source`` and ``form.rows`` both resolve, and a crosswalk whose
references resolve. The deliberately malformed inputs (bad YAML, duplicated
keys, schema violations) are written per test, so no invalid YAML has to sit
in the tree past the repository's own check-yaml hook.
"""

import datetime
import importlib.resources
import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from gpai_docs.registry import Registry, RegistryError, load, load_yaml_mapping
from gpai_docs.registry.models import (
    CrosswalkFile,
    Field,
    FieldsFile,
    Source,
    SourcesFile,
)

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "registry_mini"


def _source(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "xi-1-1-a",
        "kind": "regulation",
        "instrument": "Regulation (EU) 2024/1689",
        "celex": "02024R1689-20260727",
        "location": "Annex XI, Section 1, point 1(a)",
        "language": "en",
        "url": "https://example.invalid/regulation",
        "extraction": {
            "kind": "element",
            "annex": "XI",
            "section": 1,
            "item": 1,
            "letter": "a",
        },
        "retrieved": datetime.date(2026, 10, 8),
        "verification": "extract",
        "text": "the tasks that the model is intended to perform",
        "sha256": "a" * 64,
    }
    data.update(overrides)
    return data


def _field(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "XI.1.1.a",
        "annex": "XI",
        "section": 1,
        "point": "1(a)",
        "label": "Tasks the model is intended to perform",
        "recipients": ["ai_office", "nca"],
        "form": {"rows": ["1"], "audience_flags": ["ai_office", "nca"]},
        "source": "xi-1-1-a",
        "model_field": "annex_xi.intended_tasks",
        "rules": ["completeness", "type:text"],
    }
    data.update(overrides)
    return data


def _fields_file(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": 1,
        "pack": "eu-ai-act",
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2024/1689",
        "covers": ["technical-documentation", "transparency-information"],
        "fields": [_field()],
    }
    data.update(overrides)
    return data


def _crosswalk(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": 1,
        "pack": "eu-ai-act",
        "targets": [
            {
                "id": "nist-ai-rmf",
                "name": "NIST AI Risk Management Framework",
                "version": "1.0",
                "date": datetime.date(2023, 1, 26),
                "url": "https://example.invalid/nist",
                "licence": "NIST-authored; attribution and disclaimer",
                "identifier_style": "GV 1.1",
                "status": "active",
                "provisional": False,
            }
        ],
        "mappings": [
            {
                "field": "XI.1.1.a",
                "targets": [
                    {"target": "nist-ai-rmf", "ref": "MAP 2.2", "note": "documentation"}
                ],
            }
        ],
        "terminology": [
            {
                "act_term": "provider",
                "aliases": [
                    {"target": "nist-ai-rmf", "term": "AI actor", "note": "alias"}
                ],
            }
        ],
    }
    data.update(overrides)
    return data


def _registry_copy(tmp_path: Path) -> Path:
    directory = tmp_path / "registry"
    shutil.copytree(MINI, directory)
    return directory


def _fixtures_are_the_package(_package: str) -> Path:
    # The stand-in for importlib.resources.files("gpai_docs.registry").
    return MINI


@pytest.mark.parametrize(
    "field_id",
    ["XI.1.1.a", "XI.1.1.f", "XI.1.2.e", "XI.2.1", "XI.2.3", "XII.2.c"],
)
def test_field_id_grammar_accepts_published_ids(field_id: str) -> None:
    assert Field.model_validate(_field(id=field_id)).id == field_id


@pytest.mark.parametrize(
    "field_id",
    ["XI.1.a", "xii.1.a", "XI.1.1.aa", "XI.1.1", "XI.2", "XI.2.1.a", "XI.3.1"],
)
def test_field_id_grammar_rejects_other_ids(field_id: str) -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(_field(id=field_id))


def test_recipients_enum_accepts_the_published_audiences() -> None:
    field = Field.model_validate(_field(recipients=["downstream"]))
    assert field.recipients == ["downstream"]


def test_recipients_enum_rejects_an_unknown_audience() -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(_field(recipients=["ai_office2"]))


def test_a_form_mapping_carries_at_least_one_row() -> None:
    empty = {"rows": [], "audience_flags": ["ai_office", "nca"]}
    with pytest.raises(ValidationError, match="no row"):
        Field.model_validate(_field(form=empty))


def test_an_empty_form_mapping_with_a_note_validates() -> None:
    # Rows may be empty only when the note records why (Section 2's
    # fields ship without Form rows because the Form does not carry them).
    note = "not carried by the Model Documentation Form"
    form = {"rows": [], "note": note, "audience_flags": []}
    field = Field.model_validate(_field(form=form))
    assert field.form.rows == []
    assert field.form.note == note
    assert field.form.audience_flags == []


@pytest.mark.parametrize("note", ["", "   "], ids=["empty", "whitespace"])
def test_an_empty_form_mapping_with_a_blank_note_is_refused(note: str) -> None:
    form = {"rows": [], "audience_flags": [], "note": note}
    with pytest.raises(ValidationError, match="no row"):
        Field.model_validate(_field(form=form))


def test_a_form_mapping_with_rows_may_still_carry_a_note() -> None:
    # The note is provenance about the mapping; the relaxation's condition is
    # only that an empty row list must explain itself.
    form = {"rows": ["1"], "audience_flags": [], "note": "why"}
    field = Field.model_validate(_field(form=form))
    assert field.form.note == "why"


@pytest.mark.parametrize("condition", [None, "systemic_risk"])
def test_the_condition_grammar_accepts_its_vocabulary(
    condition: str | None,
) -> None:
    field = Field.model_validate(_field(condition=condition))
    assert field.condition == condition


@pytest.mark.parametrize(
    "condition",
    ["systemic-risk", "Systemic_Risk", "systemic_risk2", "systemic", ""],
)
def test_the_condition_grammar_rejects_unknown_conditions(condition: str) -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(_field(condition=condition))


@pytest.mark.parametrize(
    "rule",
    [
        "completeness",
        "type:text",
        "type:text-list",
        "type:number",
        "type:compute",
        "type:energy",
        "consistency:notification.due",
        "consistency:compute.reporting",
        "consistency:modification.one-third",
    ],
)
def test_rule_tag_grammar_accepts_v0_tags(rule: str) -> None:
    assert Field.model_validate(_field(rules=[rule])).rules == [rule]


@pytest.mark.parametrize(
    "rule",
    [
        "type:banana",
        "completeness:x",
        "type:compute-value",
        "type:object",
    ],
)
def test_rule_tag_grammar_rejects_unknown_tags(rule: str) -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(_field(rules=[rule]))


@pytest.mark.parametrize(
    "rule",
    [
        "consistency:",
        "consistency:notification.Due",
        "consistency:Notification.due",
        "consistency:.due",
        "consistency:-due",
        "consistency::due",
    ],
)
def test_consistency_tag_grammar_rejects_malformed_ids(rule: str) -> None:
    # The id must start with a letter or digit and stay lowercase; an empty,
    # uppercase or leading-punctuation id is no rule id.
    with pytest.raises(ValidationError):
        Field.model_validate(_field(rules=[rule]))


@pytest.mark.parametrize(
    "path",
    ["annex_xi.intended_tasks", "annex_xii.energy_consumption", "annex_xi.field_2"],
)
def test_model_field_grammar_accepts_registry_paths(path: str) -> None:
    assert Field.model_validate(_field(model_field=path)).model_field == path


@pytest.mark.parametrize(
    "path", ["annex_xi.IntendedTasks", "annex_iii.tasks", "intended_tasks", "annex_xi."]
)
def test_model_field_grammar_rejects_other_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(_field(model_field=path))


def test_an_extract_source_carries_no_artifact_fields() -> None:
    source = Source.model_validate(_source())
    assert source.verification == "extract"
    assert source.artifact_url is None
    assert source.artifact_sha256 is None


def test_a_source_may_pin_a_separate_fetch_url() -> None:
    # The canonical URL stays the human-facing citation; the pipeline may fetch
    # the same text from a machine endpoint instead.
    source = Source.model_validate(_source(fetch_url="https://cellar.invalid/celex"))
    assert source.fetch_url == "https://cellar.invalid/celex"


def test_a_source_without_a_fetch_url_has_none() -> None:
    assert Source.model_validate(_source()).fetch_url is None


def test_a_shape_matching_celex_without_a_calendar_date_raises() -> None:
    # The watch derives a resolver from every shape-matching pin; an
    # impossible date such as 02024R1689-20269999 is a registry defect and
    # must fail at load, never inside an online pass.
    with pytest.raises(ValidationError, match="no calendar date"):
        Source.model_validate(_source(celex="02024R1689-20269999"))


def test_a_non_dated_celex_stays_allowed() -> None:
    # Only the dated-consolidation shape is constrained; other celex values
    # are legal (the watch simply does not watch them).
    source = Source.model_validate(_source(celex="32024R1689"))
    assert source.celex == "32024R1689"


def test_an_extract_source_carries_its_extraction_locator() -> None:
    source = Source.model_validate(_source())
    assert source.extraction is not None
    assert source.extraction.kind == "element"
    assert source.extraction.annex == "XI"
    assert source.extraction.section == 1
    assert source.extraction.item == 1
    assert source.extraction.letter == "a"


def test_an_extract_source_without_an_extraction_locator_raises() -> None:
    with pytest.raises(ValidationError, match="extraction"):
        Source.model_validate(_source(extraction=None))


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "element", "annex": "XI"},
        {"kind": "element", "annex": "XI", "item": 1},
        {"kind": "element", "annex": "XI", "letter": "a"},
        {"kind": "following_note", "annex": "XII"},
    ],
)
def test_element_and_note_kinds_require_item_and_letter(
    extraction: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="extraction"):
        Source.model_validate(_source(extraction=extraction))


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "chapeau", "annex": "XI"},
        {"kind": "chapeau", "annex": "XII", "section": None},
        {"kind": "element", "annex": "XII", "item": 2, "letter": "c"},
        {
            "kind": "following_note",
            "annex": "XI",
            "section": 1,
            "item": 2,
            "letter": "e",
        },
        {"kind": "element", "annex": "XI", "section": 2, "item": 1},
        {"kind": "element", "annex": "XI", "section": 2, "item": 3, "letter": None},
    ],
)
def test_extraction_locators_that_match_their_kind_validate(
    extraction: dict[str, Any],
) -> None:
    source = Source.model_validate(_source(extraction=extraction))
    assert source.extraction is not None


def test_a_section_2_element_locator_forbids_a_letter() -> None:
    # Section 2's items are letter-less: a letter on that shape is
    # a locator defect, never a silently ignored field.
    with pytest.raises(ValidationError, match="letter"):
        Source.model_validate(
            _source(
                extraction={
                    "kind": "element",
                    "annex": "XI",
                    "section": 2,
                    "item": 1,
                    "letter": "a",
                }
            )
        )


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "element", "annex": "XI", "item": 1},
        {"kind": "element", "annex": "XI", "section": 1, "item": 1},
        {"kind": "element", "annex": "XII", "item": 1},
    ],
    ids=["no-section", "section-1", "annex-xii"],
)
def test_a_letterless_element_locator_needs_section_2(
    extraction: dict[str, Any],
) -> None:
    # The letter-less shape is Section 2's alone; everywhere else a lettered
    # point is the only element shape, so the missing letter is named.
    with pytest.raises(ValidationError, match="letter"):
        Source.model_validate(_source(extraction=extraction))


def test_a_section_2_element_locator_still_needs_its_item() -> None:
    with pytest.raises(ValidationError, match="item"):
        Source.model_validate(
            _source(extraction={"kind": "element", "annex": "XI", "section": 2})
        )


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "element", "annex": "XII", "section": 2, "item": 1},
        {"kind": "element", "annex": "XII", "section": 1, "item": 1, "letter": "a"},
        {
            "kind": "following_note",
            "annex": "XII",
            "section": 1,
            "item": 1,
            "letter": "a",
        },
    ],
    ids=["letter-less", "lettered", "following-note"],
)
def test_a_sectioned_element_locator_needs_annex_xi(
    extraction: dict[str, Any],
) -> None:
    # Sections exist in Annex XI alone: a section on an Annex XII element or
    # note locator is a registry defect at load, never a fetch-time failure.
    with pytest.raises(ValidationError, match="section"):
        Source.model_validate(_source(extraction=extraction))


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "chapeau", "annex": "XI", "section": 1},
        {"kind": "chapeau", "annex": "XI", "item": 1},
        {"kind": "chapeau", "annex": "XI", "letter": "a"},
    ],
)
def test_chapeau_extraction_takes_the_annex_alone(
    extraction: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="chapeau"):
        Source.model_validate(_source(extraction=extraction))


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "article", "article": 52, "paragraph": 1},
        {"kind": "article", "article": 53, "paragraph": 1, "point": "a"},
        {"kind": "article", "article": 53, "paragraph": 4},
        {"kind": "article", "article": 51},
    ],
)
def test_article_extraction_locators_that_match_their_kind_validate(
    extraction: dict[str, Any],
) -> None:
    source = Source.model_validate(_source(extraction=extraction))
    assert source.extraction is not None
    assert source.extraction.article == extraction["article"]


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "article"},
        {"kind": "article", "paragraph": 1},
        {"kind": "article", "article": 52, "annex": "XI"},
        {"kind": "article", "article": 52, "section": 1},
        {"kind": "article", "article": 52, "item": 1, "letter": "a"},
        {"kind": "article", "article": 53, "point": "a"},
        {
            "kind": "element",
            "annex": "XI",
            "section": 1,
            "item": 1,
            "letter": "a",
            "article": 52,
        },
        {"kind": "chapeau", "annex": "XI", "article": 51},
    ],
)
def test_extraction_locators_that_misplace_their_fields_raise(
    extraction: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(_source(extraction=extraction))


def test_an_article_locator_without_an_article_number_names_the_missing_field() -> None:
    with pytest.raises(ValidationError, match="article"):
        Source.model_validate(_source(extraction={"kind": "article", "paragraph": 1}))


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "element", "section": 1, "item": 1, "letter": "a"},
        {"kind": "chapeau"},
        {"kind": "following_note", "item": 1, "letter": "a"},
    ],
)
def test_annex_locators_without_an_annex_name_the_missing_field(
    extraction: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="annex"):
        Source.model_validate(_source(extraction=extraction))


def test_a_point_in_an_article_locator_needs_its_paragraph() -> None:
    with pytest.raises(ValidationError, match="paragraph"):
        Source.model_validate(
            _source(extraction={"kind": "article", "article": 53, "point": "a"})
        )


@pytest.mark.parametrize(
    "extraction",
    [
        {"kind": "article", "annex": "XI", "item": 1, "letter": "a"},
        {"kind": "element", "annex": "XIII", "item": 1, "letter": "a"},
    ],
)
def test_unknown_extraction_kinds_and_annexes_raise(
    extraction: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(_source(extraction=extraction))


def test_an_artifact_source_with_both_artifact_fields_validates() -> None:
    source = Source.model_validate(
        _source(
            verification="artifact",
            extraction=None,
            artifact_url="https://example.invalid/guidelines.pdf",
            artifact_sha256="b" * 64,
        )
    )
    assert source.verification == "artifact"
    assert source.extraction is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"verification": "artifact"},
        {"verification": "artifact", "artifact_url": "https://example.invalid/x.pdf"},
        {"verification": "artifact", "artifact_sha256": "b" * 64},
    ],
)
def test_an_artifact_source_requires_url_and_byte_hash(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(_source(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"artifact_url": "https://example.invalid/x.pdf"},
        {"artifact_sha256": "b" * 64},
    ],
)
def test_an_extract_source_forbids_artifact_fields(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Source.model_validate(_source(**overrides))


def test_an_artifact_source_forbids_an_extraction_locator() -> None:
    with pytest.raises(ValidationError, match="extraction"):
        Source.model_validate(
            _source(
                verification="artifact",
                artifact_url="https://example.invalid/guidelines.pdf",
                artifact_sha256="b" * 64,
            )
        )


def test_a_mapping_to_an_unknown_target_raises() -> None:
    data = _crosswalk(
        mappings=[
            {
                "field": "XI.1.1.a",
                "targets": [{"target": "iso-42001", "ref": "7.5", "note": "n"}],
            }
        ]
    )
    with pytest.raises(ValidationError):
        CrosswalkFile.model_validate(data)


def test_a_terminology_alias_to_an_unknown_target_raises() -> None:
    data = _crosswalk(
        terminology=[
            {
                "act_term": "provider",
                "aliases": [
                    {"target": "kr-ai-basic-act", "term": "operator", "note": "n"}
                ],
            }
        ]
    )
    with pytest.raises(ValidationError):
        CrosswalkFile.model_validate(data)


def test_a_crosswalk_whose_references_resolve_validates() -> None:
    crosswalk = CrosswalkFile.model_validate(_crosswalk())
    assert crosswalk.targets[0].id == "nist-ai-rmf"


def test_a_mapping_field_must_be_a_field_id() -> None:
    data = _crosswalk(
        mappings=[
            {
                "field": "XI.1.a",
                "targets": [{"target": "nist-ai-rmf", "ref": "MAP 2.2", "note": "n"}],
            }
        ]
    )
    with pytest.raises(ValidationError):
        CrosswalkFile.model_validate(data)


def test_duplicate_source_ids_within_the_catalogue_raise() -> None:
    data = {"schema": 1, "pack": "eu-ai-act", "sources": [_source(), _source()]}
    with pytest.raises(ValidationError, match="duplicate source id"):
        SourcesFile.model_validate(data)


def test_duplicate_field_ids_within_the_registry_raise() -> None:
    with pytest.raises(ValidationError, match="duplicate field id"):
        FieldsFile.model_validate(_fields_file(fields=[_field(), _field()]))


def test_load_returns_a_registry_from_a_fixture_directory() -> None:
    registry: Registry = load(MINI)
    field = registry.by_id["XI.1.1.a"]
    assert registry.fields == [field]
    # The field's source resolves to the extract-mode catalogue entry...
    assert registry.sources[field.source].verification == "extract"
    # ...and its form rows all resolve to rows of the form inventory.
    assert set(field.form.rows) <= {row.row for row in registry.form.rows}
    # The fixture also carries an artifact-mode source, which the model's
    # artifact rules only let through with url and byte hash present.
    artifact = next(
        source
        for source in registry.sources.values()
        if source.verification == "artifact"
    )
    assert artifact.artifact_url is not None
    assert artifact.artifact_sha256 is not None


def test_load_with_no_path_reads_package_data(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pointing importlib.resources at the fixture directory exercises the
    # package-data route the real registry takes.
    monkeypatch.setattr(importlib.resources, "files", _fixtures_are_the_package)
    assert "XI.1.1.a" in load().by_id


def test_a_duplicated_yaml_key_raises_registry_error(tmp_path: Path) -> None:
    directory = _registry_copy(tmp_path)
    (directory / "fields.yaml").write_text(
        textwrap.dedent(
            """\
            schema: 1
            pack: eu-ai-act
            pack: eu-ai-act
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="duplicate key"):
        load(directory)


def test_a_duplicated_key_inside_an_entry_raises_registry_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            schema: 1
            pack: eu-ai-act
            sources:
              - id: xi-1-1-a
                kind: regulation
                id: xi-1-1-b
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="duplicate key"):
        load_yaml_mapping(path)


def test_load_yaml_mapping_reads_a_plain_mapping(tmp_path: Path) -> None:
    path = tmp_path / "sample.yaml"
    path.write_text("schema: 1\npack: eu-ai-act\n", encoding="utf-8")
    assert load_yaml_mapping(path) == {"schema": 1, "pack": "eu-ai-act"}


def test_load_yaml_mapping_reports_a_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "latin-1.yaml"
    path.write_bytes(b"schema: caf\xe9\n")

    with pytest.raises(RegistryError, match="cannot read"):
        load_yaml_mapping(path)


def test_load_yaml_mapping_rejects_an_unhashable_key(tmp_path: Path) -> None:
    path = tmp_path / "sequence-key.yaml"
    path.write_text("? [a, b]\n: value\n", encoding="utf-8")

    with pytest.raises(RegistryError, match="unhashable key"):
        load_yaml_mapping(path)


def test_load_reports_a_missing_file(tmp_path: Path) -> None:
    directory = _registry_copy(tmp_path)
    (directory / "crosswalk.yaml").unlink()
    with pytest.raises(RegistryError, match=r"crosswalk\.yaml"):
        load(directory)


def test_load_reports_malformed_yaml(tmp_path: Path) -> None:
    directory = _registry_copy(tmp_path)
    (directory / "crosswalk.yaml").write_text("targets: [\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"crosswalk\.yaml"):
        load(directory)


def test_load_reports_a_non_utf8_file(tmp_path: Path) -> None:
    directory = _registry_copy(tmp_path)
    (directory / "crosswalk.yaml").write_bytes(b"targets: caf\xe9\n")
    with pytest.raises(RegistryError, match=r"crosswalk\.yaml"):
        load(directory)


def test_load_reports_a_file_that_is_not_a_mapping(tmp_path: Path) -> None:
    directory = _registry_copy(tmp_path)
    (directory / "crosswalk.yaml").write_text("- targets\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"crosswalk\.yaml"):
        load(directory)


def test_load_reports_a_schema_violation(tmp_path: Path) -> None:
    directory = _registry_copy(tmp_path)
    (directory / "crosswalk.yaml").write_text(
        "schema: 1\npack: eu-ai-act\ntargets: not-a-list\n", encoding="utf-8"
    )
    with pytest.raises(RegistryError, match=r"crosswalk\.yaml"):
        load(directory)
