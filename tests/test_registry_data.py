"""Data pins for the four shipped registry files.

All four are read from package data through ``importlib.resources`` (the
files the installed package actually ships), never from the network; the
full default ``load()`` path is asserted here as well.
"""

import datetime
import importlib.resources
import re
from pathlib import Path
from typing import Any

import yaml

from gpai_docs.registry import load
from gpai_docs.registry.extract import normalise, sha256_of
from gpai_docs.registry.fetch import extract_from_locator
from gpai_docs.registry.models import (
    _RULE_TAG,
    CrosswalkFile,
    Field,
    FieldsFile,
    FormFile,
    FormRow,
    Source,
    SourcesFile,
)

REGISTRY_PACKAGE = importlib.resources.files("gpai_docs.registry")
SOURCES = REGISTRY_PACKAGE.joinpath("sources.yaml")
FIELDS = REGISTRY_PACKAGE.joinpath("fields.yaml")
FORM = REGISTRY_PACKAGE.joinpath("form.yaml")
CROSSWALK = REGISTRY_PACKAGE.joinpath("crosswalk.yaml")
# The committed EUR-Lex excerpt the extractor tests pin; its Annex XI span,
# Section 2 included, is byte-identical to the Cellar copy the sources'
# fetch_url pins.
EXCERPT = Path(__file__).parent / "fixtures" / "eurlex_annex_excerpt.html"

# The pinned consolidation and its canonical citation; the machine fetch is
# pinned separately because EUR-Lex sometimes serves a WAF challenge.
CELEX = "02024R1689-20260727"
CANONICAL_URL = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{CELEX}"
CELLAR_URL = (
    "https://publications.europa.eu/resource/cellar/"
    "b1730fb2-8f1c-11f1-9262-01aa75ed71a1.0001.03/DOC_1"
)

# Every extract-mode source the catalogue must carry:
# Annex XI's chapeau, its Section 1 lettered points and its letter-less
# Section 2 items, Annex XII's chapeau and points, and the articles.
ANNEX_XI_IDS = (
    ["reg-2024-1689-annex-xi-chapeau"]
    + [f"reg-2024-1689-annex-xi-1-1-{letter}" for letter in "abcdef"]
    + [f"reg-2024-1689-annex-xi-1-2-{letter}" for letter in "abcde"]
    + ["reg-2024-1689-annex-xi-1-2-e-note"]
    + [f"reg-2024-1689-annex-xi-2-{item}" for item in "123"]
)
ANNEX_XII_IDS = (
    ["reg-2024-1689-annex-xii-chapeau"]
    + [f"reg-2024-1689-annex-xii-1-{letter}" for letter in "abcdefgh"]
    + [f"reg-2024-1689-annex-xii-2-{letter}" for letter in "abc"]
)
ARTICLE_IDS = [
    "reg-2024-1689-art-51-1-a",
    "reg-2024-1689-art-51-2",
    "reg-2024-1689-art-52-1",
    "reg-2024-1689-art-53-1-a",
    "reg-2024-1689-art-53-1-b",
    "reg-2024-1689-art-53-4",
]
# Artifact-mode sources: the Code Transparency chapter and the guidelines
# excerpts the v0.1 consistency rules cite.
ARTIFACT_IDS = [
    "code-gpai-transparency-1-1-documentation",
    "code-gpai-transparency-1-1-retention",
    "guidelines-c2025-7719-31-compute-reporting",
    "guidelines-c2025-7719-60-one-third-criterion",
    "guidelines-c2025-7719-120-compute-estimation",
]

# Every published element, transcribed from the official consolidated text as
# stored in sources.yaml: Annex XI, Section 1, points 1(a)-(f) and 2(a)-(e);
# Annex XI, Section 2, the three letter-less items; Annex XII, points 1(a)-(h)
# and 2(a)-(c), eleven, three and eleven. The test below
# re-derives the same set;
# test_the_expected_ids_agree_with_the_stored_provisions re-derives the list
# mechanically from the stored provisions' locators as a third check.
ANNEX_XI_SECTION_1_FIELDS = [
    "XI.1.1.a",
    "XI.1.1.b",
    "XI.1.1.c",
    "XI.1.1.d",
    "XI.1.1.e",
    "XI.1.1.f",
    "XI.1.2.a",
    "XI.1.2.b",
    "XI.1.2.c",
    "XI.1.2.d",
    "XI.1.2.e",
]
ANNEX_XI_SECTION_2_FIELDS = ["XI.2.1", "XI.2.2", "XI.2.3"]
ANNEX_XII_FIELDS = [
    "XII.1.a",
    "XII.1.b",
    "XII.1.c",
    "XII.1.d",
    "XII.1.e",
    "XII.1.f",
    "XII.1.g",
    "XII.1.h",
    "XII.2.a",
    "XII.2.b",
    "XII.2.c",
]
EXPECTED_FIELD_IDS = (
    ANNEX_XI_SECTION_1_FIELDS + ANNEX_XI_SECTION_2_FIELDS + ANNEX_XII_FIELDS
)
# The fields the crosswalk maps: Section 2's targets are v2 candidates
# so its three fields carry no mapping.
MAPPED_FIELD_IDS = ANNEX_XI_SECTION_1_FIELDS + ANNEX_XII_FIELDS
# The systemic-risk condition, and the note the row-less Form mappings
# record why they carry no rows.
SECTION_2_CONDITION = "systemic_risk"
SECTION_2_FORM_NOTE = "not carried by the Model Documentation Form"

# The model-field grammar the field entries must satisfy;
# the rule-tag grammar is single-sourced from the models module.
MODEL_FIELD = re.compile(r"annex_(?:xi|xii)\.[a-z0-9_]+")

# The Form rows no field covers, with the one-line reason each is left out.
# These five rows carry no Annex XI, Section 1 or Annex XII element of their
# own: four identify the provider or the model, and the fifth is the pointer
# to the category definitions that elaborate the Data provenance row
# (docs/form-docx-structure.md, last section). Every other row is named by at
# least one field's `form.rows`.
OUT_OF_SCOPE_FORM_ROWS: dict[str, str] = {
    "general-information/legal-name-for-the-model-provider": (
        "provider identity, no element of its own"
    ),
    "general-information/model-name": "model identity, no element of its own",
    "general-information/model-authenticity": ("model identity, no element of its own"),
    "general-information/model-dependencies": (
        "dependency statement, no element of its own"
    ),
    "data-used-for-training-testing-and-validation/data-provenance-category-options": (
        "category-definitions pointer with no crosses; elaborates the "
        "Data provenance row"
    ),
}

# The connected instruments the crosswalk must carry: the EU code,
# the two NIST publications, ISO/IEC 42001 with its satellites and the
# terminology standard, the OECD principles, the CoE convention, and the Korea
# AI Basic Act. The three serialisation formats are recorded, `deferred`, and
# appear in no mapping.
EXPECTED_TARGET_IDS = {
    "eu-gpai-code",
    "nist-ai-rmf",
    "nist-ai-600-1",
    "iso-42001",
    "iso-23894",
    "iso-42005",
    "iso-22989",
    "oecd-ai-principles",
    "coe-cets-225",
    "kr-ai-basic-act",
    "cyclonedx-modelcard",
    "spdx-3-ai",
    "oscal",
}
DEFERRED_TARGET_IDS = {"cyclonedx-modelcard", "spdx-3-ai", "oscal"}
# No authorised copy of any ISO standard was available to
# verify identifiers, so every ISO target and every ISO row is provisional
# nothing else may carry the flag.
ISO_TARGET_IDS = {"iso-42001", "iso-23894", "iso-42005", "iso-22989"}
CODE_TARGET_ID = "eu-gpai-code"
CODE_MEASURES = {"Measure 1.1", "Measure 1.2", "Measure 1.3"}
# ISO rows cite clause and Annex identifiers only, never reproduced text.
ISO_IDENTIFIER = re.compile(r"(?:Clause|Annex) [A-Z0-9]+(?:\.[0-9]+)*")
# A mapping note is navigation, never conformance: these stems may
# not appear in one.
NON_NAVIGATION_WORDS = ("conform", "complian", "certif", "satisf")
# The Korea "AI system" definition, captured verbatim from the KLRI English
# translation of the AI Basic Act during authoring (Art. 2(2); statute
# hseq 73499), the open item.
KOREA_AI_SYSTEM_DEFINITION = (
    "an AI-based system that infers outputs such as predictions, "
    "recommendations, and decisions that affect real and virtual environments "
    "for a given goal with various levels of autonomy and adaptability"
)


def _raw() -> dict[str, Any]:
    data = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _sources() -> list[Source]:
    return SourcesFile.model_validate(_raw()).sources


def _has_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_has_null(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_null(item) for item in value)
    return False


def test_sources_yaml_ships_as_package_data() -> None:
    assert SOURCES.is_file()


def test_the_file_is_a_valid_catalogue_with_unique_ids() -> None:
    data = _raw()
    assert data["schema"] == 1
    assert data["pack"] == "eu-ai-act"
    identifiers = [entry["id"] for entry in data["sources"]]
    assert len(identifiers) == len(set(identifiers))
    SourcesFile.model_validate(data)


def test_every_stored_text_hashes_to_its_registered_sha256() -> None:
    for source in _sources():
        assert source.sha256 == sha256_of(source.text), source.id


def test_every_stored_text_is_already_normalised() -> None:
    for source in _sources():
        assert normalise(source.text) == source.text, source.id


def test_extract_sources_carry_a_locator_and_no_artifact_fields() -> None:
    for source in _sources():
        if source.verification != "extract":
            continue
        assert source.extraction is not None, source.id
        assert source.artifact_url is None, source.id
        assert source.artifact_sha256 is None, source.id


def test_artifact_sources_pin_the_file_and_carry_no_locator() -> None:
    for source in _sources():
        if source.verification != "artifact":
            continue
        assert source.artifact_url, source.id
        assert source.artifact_sha256, source.id
        assert source.extraction is None, source.id


def test_a_safe_dump_reload_round_trip_leaves_every_hash_unchanged() -> None:
    # Folded or rewrapped scalars by a YAML formatter must not
    # move a stored hash.
    entries = [source.model_dump(exclude_none=True) for source in _sources()]
    reloaded = yaml.safe_load(yaml.safe_dump(entries, sort_keys=False))
    assert isinstance(reloaded, list)
    assert len(reloaded) == len(entries)
    for before, after in zip(entries, reloaded, strict=True):
        assert after["id"] == before["id"]
        assert after["sha256"] == before["sha256"]
        assert sha256_of(after["text"]) == before["sha256"]


def test_the_catalogue_carries_no_nulls() -> None:
    assert not _has_null(_raw())


def test_the_catalogue_pins_every_planned_provision() -> None:
    by_mode: dict[str, list[str]] = {"extract": [], "artifact": []}
    for source in _sources():
        by_mode[source.verification].append(source.id)
    assert sorted(by_mode["extract"]) == sorted(
        ANNEX_XI_IDS + ANNEX_XII_IDS + ARTICLE_IDS
    )
    assert sorted(by_mode["artifact"]) == sorted(ARTIFACT_IDS)
    assert len(by_mode["extract"]) == 34


def test_regulation_sources_pin_the_pinned_celex_and_the_cellar_mirror() -> None:
    for source in _sources():
        assert source.language == "en", source.id
        if source.kind != "regulation":
            continue
        assert source.celex == CELEX, source.id
        assert source.url == CANONICAL_URL, source.id
        assert source.fetch_url == CELLAR_URL, source.id
        assert source.retrieved <= datetime.date.today(), source.id


def _raw_fields() -> dict[str, Any]:
    data = yaml.safe_load(FIELDS.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _fields() -> list[Field]:
    return FieldsFile.model_validate(_raw_fields()).fields


def _form_rows() -> list[FormRow]:
    data = yaml.safe_load(FORM.read_text(encoding="utf-8"))
    return FormFile.model_validate(data).rows


def _element_ids_from_sources() -> set[str]:
    # The element inventory as the stored extract provisions address it.
    identifiers: set[str] = set()
    for source in _sources():
        locator = source.extraction
        if locator is None or locator.kind != "element":
            continue
        assert locator.annex is not None
        assert locator.item is not None
        if locator.letter is None:
            # Section 2's letter-less items: XI.<section>.<item>.
            assert locator.annex == "XI"
            assert locator.section == 2
            identifiers.add(f"XI.{locator.section}.{locator.item}")
        elif locator.annex == "XI":
            assert locator.section == 1
            identifiers.add(f"XI.{locator.section}.{locator.item}.{locator.letter}")
        else:
            identifiers.add(f"XII.{locator.item}.{locator.letter}")
    return identifiers


def test_fields_yaml_ships_as_package_data() -> None:
    assert FIELDS.is_file()


def test_the_field_registry_carries_the_pack_manifest() -> None:
    data = _raw_fields()
    assert data["schema"] == 1
    assert data["pack"] == "eu-ai-act"
    assert data["jurisdiction"] == "EU"
    assert data["instrument"] == "Regulation (EU) 2024/1689"
    assert data["covers"] == ["technical-documentation", "transparency-information"]


def test_the_file_is_a_valid_registry_with_unique_ids() -> None:
    data = _raw_fields()
    FieldsFile.model_validate(data)
    identifiers = [entry["id"] for entry in data["fields"]]
    assert len(identifiers) == len(set(identifiers))


def test_the_registry_carries_exactly_the_published_elements() -> None:
    fields = _fields()
    assert len(fields) == 25
    assert {field.id for field in fields if field.annex == "XI"} == set(
        ANNEX_XI_SECTION_1_FIELDS + ANNEX_XI_SECTION_2_FIELDS
    )
    assert {field.id for field in fields if field.annex == "XII"} == set(
        ANNEX_XII_FIELDS
    )


def test_the_expected_ids_agree_with_the_stored_provisions() -> None:
    # Two independent transcriptions of the published element inventory: the
    # literal list above (from the official text) and this re-derivation from
    # the locators of the provisions stored in sources.yaml. They must agree,
    # and the registry must carry exactly that set.
    derived = _element_ids_from_sources()
    assert derived == set(EXPECTED_FIELD_IDS)
    assert {field.id for field in _fields()} == derived


def test_every_field_pins_its_annex_section_and_enumerator() -> None:
    for field in _fields():
        parts = field.id.split(".")
        assert field.annex == parts[0], field.id
        if field.section == 2:
            # A Section 2 item is letter-less: point names the item alone.
            assert field.point == parts[-1], field.id
        else:
            assert field.point == f"{parts[-2]}({parts[-1]})", field.id
        if field.annex == "XI":
            assert field.section in (1, 2), field.id
        else:
            assert field.section is None, field.id


def test_the_systemic_risk_condition_sits_on_section_2_alone() -> None:
    # The condition is first-class in the registry: the three
    # Section 2 fields carry it and no other field does.
    conditional = [field.id for field in _fields() if field.condition is not None]
    assert conditional == ANNEX_XI_SECTION_2_FIELDS
    for field in _fields():
        if field.id in ANNEX_XI_SECTION_2_FIELDS:
            assert field.condition == SECTION_2_CONDITION, field.id
        else:
            assert field.condition is None, field.id


def test_section_2_fields_ship_without_form_rows_and_record_why() -> None:
    # The Form does not carry Section 2 rows: the mapping is empty
    # with the recorded note, and carries no audience flags.
    for field in _fields():
        if field.id not in ANNEX_XI_SECTION_2_FIELDS:
            continue
        assert field.form.rows == [], field.id
        assert field.form.note == SECTION_2_FORM_NOTE, field.id
        assert field.form.audience_flags == [], field.id


def test_section_2_guidance_states_the_conditional_nature() -> None:
    for field in _fields():
        if field.condition is None:
            continue
        assert field.guidance is not None, field.id
        assert "systemic risk" in field.guidance.lower(), field.id


def test_the_section_2_sources_re_extract_from_the_committed_excerpt() -> None:
    # The three sources are bound to the extractor and the committed excerpt:
    # re-extraction through the stored locator reproduces the stored text and
    # hash. The excerpt's Section 2 span is byte-identical to the Cellar copy
    # the sources' fetch_url pins, so the offline check pins the live
    # pipeline's output.
    html = EXCERPT.read_bytes()
    re_extracted = 0
    for source in _sources():
        locator = source.extraction
        if locator is None or locator.annex != "XI" or locator.section != 2:
            continue
        assert extract_from_locator(locator, html) == source.text, source.id
        assert sha256_of(source.text) == source.sha256, source.id
        re_extracted += 1
    assert re_extracted == len(ANNEX_XI_SECTION_2_FIELDS)


def test_every_source_and_context_reference_resolves() -> None:
    known = {source.id for source in _sources()}
    for field in _fields():
        assert field.source in known, field.id
        for reference in field.context:
            assert reference in known, field.id


def test_every_form_row_is_covered_or_declared_out_of_scope() -> None:
    rows = {row.row for row in _form_rows()}
    covered: set[str] = set()
    for field in _fields():
        # Required direction: no field cites a row the Form inventory lacks,
        # and a field does not cite the same row twice.
        assert set(field.form.rows) <= rows, field.id
        assert len(field.form.rows) == len(set(field.form.rows)), field.id
        covered |= set(field.form.rows)
    # Reverse direction: every Form row is either covered by a field's
    # `form.rows` or declared above, with a reason, as carrying no element of
    # its own.
    assert rows - covered == set(OUT_OF_SCOPE_FORM_ROWS)


def test_audience_flags_are_the_crosses_of_the_mapped_rows() -> None:
    crosses = {row.row: set(row.audience_flags) for row in _form_rows()}
    canonical = ["ai_office", "nca", "downstream"]
    for field in _fields():
        union: set[str] = set()
        for row in field.form.rows:
            union |= crosses[row]
        assert field.form.audience_flags == [
            audience for audience in canonical if audience in union
        ], field.id


def test_model_field_paths_are_unique_and_well_formed() -> None:
    paths = [field.model_field for field in _fields()]
    assert len(paths) == len(set(paths))
    for field in _fields():
        assert MODEL_FIELD.fullmatch(field.model_field), field.id
        namespace = "xi" if field.annex == "XI" else "xii"
        assert field.model_field.startswith(f"annex_{namespace}."), field.id


def test_every_field_carries_a_label_and_a_guidance_note() -> None:
    for field in _fields():
        assert field.label.strip(), field.id
        assert field.guidance is not None, field.id
        assert field.guidance.strip(), field.id


def test_rule_tags_are_v0_vocabulary_tags() -> None:
    for field in _fields():
        assert field.rules, field.id
        for tag in field.rules:
            assert _RULE_TAG.fullmatch(tag), (field.id, tag)


def test_the_structured_tags_sit_on_their_elements() -> None:
    # The registry pins compute to XI.1.2.d and energy to XI.1.2.e;
    # swapping the two tags must fail here, not stay green.
    # The two v0.1 consistency tags map to XI.1.2.d and to no other element:
    # equality, not membership, keeps the mapping exact in both directions.
    by_id = {field.id: field for field in _fields()}
    assert by_id["XI.1.2.d"].rules == [
        "completeness",
        "type:compute",
        "consistency:notification.due",
        "consistency:compute.reporting",
    ]
    assert by_id["XI.1.2.e"].rules == ["completeness", "type:energy"]
    consistency_tags = {
        (field.id, tag)
        for field in _fields()
        for tag in field.rules
        if tag.startswith("consistency:")
    }
    assert consistency_tags == {
        ("XI.1.2.d", "consistency:notification.due"),
        ("XI.1.2.d", "consistency:compute.reporting"),
    }


def test_recipients_follow_the_annex() -> None:
    # Section 2's documentation serves the AI Office's oversight alone
    # unlike Section 1's AI Office-and-NCA pair.
    expected = {"XI": ["ai_office", "nca"], "XII": ["downstream"]}
    for field in _fields():
        if field.section == 2:
            assert field.recipients == ["ai_office"], field.id
        else:
            assert field.recipients == expected[field.annex], field.id


def test_the_registry_carries_no_nulls() -> None:
    assert not _has_null(_raw_fields())


def _raw_crosswalk() -> dict[str, Any]:
    data = yaml.safe_load(CROSSWALK.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _crosswalk() -> CrosswalkFile:
    return CrosswalkFile.model_validate(_raw_crosswalk())


def test_crosswalk_yaml_ships_as_package_data() -> None:
    assert CROSSWALK.is_file()


def test_the_crosswalk_carries_the_pack_manifest() -> None:
    data = _raw_crosswalk()
    assert data["schema"] == 1
    assert data["pack"] == "eu-ai-act"


def test_the_crosswalk_is_valid_with_unique_target_ids() -> None:
    data = _raw_crosswalk()
    CrosswalkFile.model_validate(data)
    identifiers = [target["id"] for target in data["targets"]]
    assert len(identifiers) == len(set(identifiers))


def test_the_crosswalk_carries_every_planned_target() -> None:
    assert {target.id for target in _crosswalk().targets} == EXPECTED_TARGET_IDS


def test_every_target_carries_its_pinned_metadata() -> None:
    for target in _crosswalk().targets:
        assert target.name.strip(), target.id
        assert target.version.strip(), target.id
        assert target.url.startswith("https://"), target.id
        assert target.licence.strip(), target.id
        assert target.identifier_style.strip(), target.id
        assert target.date <= datetime.date.today(), target.id


def test_every_mapping_and_alias_target_resolves() -> None:
    # The model enforces this too; the test pins it against the raw file so a
    # future model change cannot quietly drop the check.
    data = _raw_crosswalk()
    known = {target["id"] for target in data["targets"]}
    for mapping in data["mappings"]:
        for target in mapping["targets"]:
            assert target["target"] in known, (mapping["field"], target["target"])
    for entry in data["terminology"]:
        for alias in entry["aliases"]:
            assert alias["target"] in known, (entry["act_term"], alias["target"])


def test_the_eu_axis_covers_every_field() -> None:
    mappings = _crosswalk().mappings
    fields = [mapping.field for mapping in mappings]
    assert len(fields) == len(set(fields))
    assert set(fields) == set(MAPPED_FIELD_IDS)
    for mapping in mappings:
        # Every element's documentation sits in the Code's Model Documentation
        # (Measure 1.1); the other measures carry it too, per the Code text.
        measures = {
            target.ref for target in mapping.targets if target.target == CODE_TARGET_ID
        }
        assert "Measure 1.1" in measures, mapping.field
        assert measures <= CODE_MEASURES, mapping.field


def test_the_crosswalk_leaves_the_section_2_fields_unmapped() -> None:
    # Annex XI Section 2's crosswalk targets are v2 candidates, so
    # the three letter-less fields carry no mapping yet.
    mapped = {mapping.field for mapping in _crosswalk().mappings}
    assert set(ANNEX_XI_SECTION_2_FIELDS).isdisjoint(mapped)
    assert set(EXPECTED_FIELD_IDS) - mapped == set(ANNEX_XI_SECTION_2_FIELDS)


def test_deferred_targets_appear_in_no_mapping_or_alias() -> None:
    crosswalk = _crosswalk()
    deferred = {
        target.id for target in crosswalk.targets if target.status == "deferred"
    }
    assert deferred == DEFERRED_TARGET_IDS
    referenced = {
        target.target for mapping in crosswalk.mappings for target in mapping.targets
    }
    referenced |= {
        alias.target for entry in crosswalk.terminology for alias in entry.aliases
    }
    assert referenced & deferred == set()


def test_iso_rows_follow_the_unavailable_authorised_copy_outcome() -> None:
    crosswalk = _crosswalk()
    # No authorised copy was available, so every ISO target
    # is provisional and no other target is.
    assert {target.id for target in crosswalk.targets if target.provisional} == (
        ISO_TARGET_IDS
    )
    for mapping in crosswalk.mappings:
        for target in mapping.targets:
            if target.target in ISO_TARGET_IDS:
                assert ISO_IDENTIFIER.fullmatch(target.ref), (
                    mapping.field,
                    target.ref,
                )


def test_every_mapping_note_is_navigation() -> None:
    for mapping in _crosswalk().mappings:
        assert mapping.targets, mapping.field
        for target in mapping.targets:
            note = target.note.strip()
            assert note, (mapping.field, target.target)
            lowered = note.lower()
            for word in NON_NAVIGATION_WORDS:
                assert word not in lowered, (mapping.field, target.target, word)


def test_the_terminology_keys_the_act_terms_to_their_aliases() -> None:
    terminology = _crosswalk().terminology
    assert {entry.act_term for entry in terminology} == {
        "AI system",
        "provider",
        "deployer",
        "general-purpose AI model",
        "high-risk AI system",
    }
    for entry in terminology:
        assert entry.aliases, entry.act_term
        for alias in entry.aliases:
            note = alias.note.strip()
            assert note, (entry.act_term, alias.target)
            assert alias.term.strip(), (entry.act_term, alias.target)
            if alias.target == "iso-22989":
                assert "partial" in note.lower(), entry.act_term
            if alias.target == "kr-ai-basic-act":
                assert any(
                    marker in note.lower() for marker in ("divergence", "false friend")
                ), entry.act_term


def test_the_korea_ai_system_definition_is_captured_verbatim() -> None:
    notes = [
        alias.note
        for entry in _crosswalk().terminology
        for alias in entry.aliases
        if alias.target == "kr-ai-basic-act"
    ]
    assert any(KOREA_AI_SYSTEM_DEFINITION in note for note in notes)


def test_the_default_load_reads_the_four_shipped_files() -> None:
    # The full default ``load()`` path, all four files as the package ships
    # them, is asserted here.
    registry = load()
    assert len(registry.fields) == 25
    assert set(registry.by_id) == set(EXPECTED_FIELD_IDS)
    assert set(registry.sources) == {source.id for source in _sources()}
    assert len(registry.form.rows) == 46
    assert registry.form.schema_ == 1
    assert registry.form.pack == "eu-ai-act"
    assert registry.crosswalk.schema_ == 1
    assert registry.crosswalk.pack == "eu-ai-act"
    assert len(registry.crosswalk.mappings) == 22
    assert {target.id for target in registry.crosswalk.targets} == EXPECTED_TARGET_IDS
