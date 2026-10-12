"""The registry-driven document checks and their rendering.

An empty document yields exactly one finding per committed field, a typed
example yields none, ``null`` and the empty string are absences, and keys the
checks cannot place are findings too. Findings render citation-first, with the
shared footer as the run's closing line (the CLI prints it), not a block.
"""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from gpai_docs.documents import Document, load_document
from gpai_docs.lint import Finding, lint, render_finding
from gpai_docs.registry import Registry, load
from gpai_docs.registry.models import Field

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "model-docs-example.yaml"
FOOTER = "engineering evidence, not a compliance verdict"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


@pytest.fixture(scope="module")
def example() -> Document:
    return load_document(EXAMPLE)


def _one_field_document(path: str, value: object) -> Document:
    section, _, key = path.partition(".")
    return Document(values={section: {key: value}})


def _finding_for(findings: list[Finding], field_id: str) -> Finding:
    matches = [item for item in findings if item.field_id == field_id]
    assert len(matches) == 1
    return matches[0]


def test_an_empty_document_yields_exactly_22_missing_findings(
    registry: Registry,
) -> None:
    # The 22 unconditioned elements; the three Section 2 fields are skipped
    # while the systemic-risk marker is absent.
    findings = lint(Document(values={}), registry)

    assert len(findings) == 22
    assert [finding.kind for finding in findings] == ["missing"] * 22
    # Registry order is the report order: nothing sorts or groups findings.
    assert [finding.field_id for finding in findings] == [
        field.id for field in registry.fields if field.condition is None
    ]
    assert [finding.location for finding in findings] == [
        field.model_field for field in registry.fields if field.condition is None
    ]


def test_an_empty_document_with_the_true_marker_yields_25_missing_findings(
    registry: Registry,
) -> None:
    # With the marker set, Section 2 applies and its absence is exactly the
    # normal missing finding for each of the three items.
    findings = lint(Document(values={"systemic_risk": True}), registry)

    assert len(findings) == 25
    assert [finding.kind for finding in findings] == ["missing"] * 25
    assert [finding.field_id for finding in findings] == [
        field.id for field in registry.fields
    ]
    assert [finding.location for finding in findings] == [
        field.model_field for field in registry.fields
    ]


def test_the_example_fixture_lints_clean(registry: Registry, example: Document) -> None:
    # The example document is the demonstration document: every element present and
    # well-typed, so the run closes with no findings.
    assert lint(example, registry) == []


# A minimal present value per structured tag: presence needs at least one
# non-null leaf beneath the element's mapping. The compute sample
# stays under Art. 51(2)'s 10^25 threshold and carries its estimation method,
# so the consistency pass has nothing to add to this lockstep document.
_STRUCTURED_SAMPLES: dict[str, dict[str, object]] = {
    "type:compute": {"training_flop": 2.3e24, "estimation_method": "estimated"},
    "type:energy": {"training": {"amount": 1200}},
}


def _values_for(registry: Registry, fields: list[Field]) -> dict[str, object]:
    """A document's values with one present sample per listed registry field.

    A structured element takes a present mapping, every leaf takes text
    (presence semantics: a mapping with a non-null leaf beneath
    it is present).
    """
    values: dict[str, object] = {"annex_xi": {}, "annex_xii": {}}
    for field in fields:
        section, _, key = field.model_field.partition(".")
        sample = next(
            (value for tag, value in _STRUCTURED_SAMPLES.items() if tag in field.rules),
            "present",
        )
        mapping = cast("dict[str, object]", values[section])
        mapping[key] = sample
    return values


def test_lockstep_every_model_field_resolves_as_a_settable_document_key(
    registry: Registry,
) -> None:
    # The miniature lockstep: the document model and the registry
    # cannot drift: every model_field path can hold a value the checks see.
    values = _values_for(registry, registry.fields)
    assert set(values) == {"annex_xi", "annex_xii"}

    assert lint(Document(values=values), registry) == []


def test_the_marker_absent_or_false_skips_the_conditional_fields(
    registry: Registry,
) -> None:
    # With the marker absent or false the Section 2 fields are skipped,
    # whether their values are present or not.
    unconditional = [field for field in registry.fields if field.condition is None]
    absent = _values_for(registry, unconditional)

    assert lint(Document(values=absent), registry) == []
    assert lint(Document(values={**absent, "systemic_risk": False}), registry) == []


def test_section_2_values_are_no_finding_when_the_marker_is_absent_or_false(
    registry: Registry,
) -> None:
    # Providing the conditional values early is no finding.
    values = _values_for(registry, registry.fields)

    assert lint(Document(values=values), registry) == []
    assert lint(Document(values={**values, "systemic_risk": False}), registry) == []


def test_the_true_marker_checks_the_conditional_fields(
    registry: Registry,
) -> None:
    # With the marker true, each absent Section 2 item is exactly the normal
    # missing finding, in registry order.
    unconditional = [field for field in registry.fields if field.condition is None]
    findings = lint(
        Document(
            values={**_values_for(registry, unconditional), "systemic_risk": True}
        ),
        registry,
    )

    assert [
        (finding.kind, finding.location, finding.field_id) for finding in findings
    ] == [
        ("missing", field.model_field, field.id)
        for field in registry.fields
        if field.condition is not None
    ]


def test_the_true_marker_with_section_2_values_present_is_clean(
    registry: Registry,
) -> None:
    values = {**_values_for(registry, registry.fields), "systemic_risk": True}

    assert lint(Document(values=values), registry) == []


def test_a_malformed_marker_is_one_typed_finding_and_nothing_more(
    registry: Registry,
) -> None:
    # A non-boolean marker is exactly one malformed typed finding; the
    # conditional fields are skipped rather than guessed at, so no Section 2
    # missing or unknown finding joins it.
    unconditional = [field for field in registry.fields if field.condition is None]
    values = {**_values_for(registry, unconditional), "systemic_risk": "yes"}

    findings = lint(Document(values=values), registry)

    assert [
        (finding.kind, finding.location, finding.field_id, finding.message)
        for finding in findings
    ] == [
        (
            "malformed",
            "systemic_risk",
            None,
            "expected a boolean: 'yes' is not a boolean",
        )
    ]


def test_render_states_the_conditional_nature_of_a_section_2_finding(
    registry: Registry,
) -> None:
    # The reported finding carries the conditional nature through the
    # guidance the render quotes, so a reader of a marker-true run sees
    # why Section 2 is being asked for. Its row-less Form mapping renders the
    # recorded note where the rows and audience-flag lines would be, never
    # blank lines: the finding explains the empty mapping itself.
    finding = _finding_for(
        lint(Document(values={"systemic_risk": True}), registry), "XI.2.1"
    )
    field = registry.by_id["XI.2.1"]

    text = render_finding(finding, registry)

    assert text == (
        "[MISSING] XI.2.1 - Evaluation strategies\n"
        "  Key: annex_xi.evaluation_strategies\n"
        "  Annex XI, Section 2, point 1 - owed to: AI Office\n"
        "  Form: not carried by the Model Documentation Form\n"
        f'  "{registry.sources[field.source].text}"\n'
        "  Guidance: Applies to models with systemic risk; describe the "
        "evaluation strategies, including evaluation results, on the basis of "
        "available public evaluation protocols and tools or otherwise of other "
        "evaluation methodologies; state the evaluation criteria, metrics and "
        "the methodology for identifying limitations."
    )


@pytest.mark.parametrize("field_id", ["XI.2.1", "XI.2.2", "XI.2.3"])
def test_render_shows_the_form_note_for_every_row_less_field(
    registry: Registry, field_id: str
) -> None:
    # Each Section 2 field's mapping is row-less with its recorded note; the
    # render states that note and never prints a blank Form line.
    finding = _finding_for(
        lint(Document(values={"systemic_risk": True}), registry), field_id
    )

    text = render_finding(finding, registry)

    assert "  Form: not carried by the Model Documentation Form\n" in text
    assert "Form rows:" not in text
    assert "Form audience flags:" not in text


def test_an_empty_list_is_missing_for_a_list_typed_field(registry: Registry) -> None:
    # The presence column: `key: []` is an absence. No shipped field
    # carries `type:text-list` yet, so the field is synthetic; the model
    # declares no list slot at that path, so the typed pass also reports the
    # key unknown. The two checks are independent, as they are for a typo'd
    # annex key.
    synthetic = registry.by_id["XI.1.1.a"].model_copy(
        update={
            "id": "XI.1.1.g",
            "model_field": "annex_xi.synthetic_list",
            "rules": ["completeness", "type:text-list"],
        }
    )
    list_registry = replace(
        registry,
        fields=[*registry.fields, synthetic],
        by_id={**registry.by_id, "XI.1.1.g": synthetic},
    )

    empty = lint(Document(values={"annex_xi": {"synthetic_list": []}}), list_registry)
    filled = lint(
        Document(values={"annex_xi": {"synthetic_list": ["a"]}}), list_registry
    )

    assert [
        (finding.kind, finding.location, finding.field_id)
        for finding in empty
        if finding.field_id == "XI.1.1.g"
    ] == [("missing", "annex_xi.synthetic_list", "XI.1.1.g")]
    assert [finding for finding in filled if finding.field_id == "XI.1.1.g"] == []


def test_an_unknown_key_yields_an_unknown_finding(registry: Registry) -> None:
    document = _one_field_document("annex_xi.training_datasets", "the datasets")

    findings = lint(document, registry)

    unknown = [finding for finding in findings if finding.kind == "unknown"]
    assert len(unknown) == 1
    assert unknown[0].location == "annex_xi.training_datasets"
    assert unknown[0].field_id is None
    assert unknown[0].message == "no registry entry for this key"
    # The unknown key does not suppress the 22 missing findings around it.
    assert len(findings) == 23


def test_unknown_keys_are_reported_in_path_order(registry: Registry) -> None:
    # The unknown pass sorts by path string; the input order here is the
    # reverse, so document order cannot be what the assertions see.
    document = Document(
        values={
            "annex_xi": {"second_key": "b", "first_key": "a"},
            "annex_xii": {"third_key": "c"},
        }
    )

    unknown = [
        finding for finding in lint(document, registry) if finding.kind == "unknown"
    ]

    assert [finding.location for finding in unknown] == [
        "annex_xi.first_key",
        "annex_xi.second_key",
        "annex_xii.third_key",
    ]


@pytest.mark.parametrize("value", [None, ""], ids=["null", "empty-string"])
def test_an_absent_value_is_missing(registry: Registry, value: object) -> None:
    document = _one_field_document("annex_xi.intended_tasks", value)

    finding = _finding_for(lint(document, registry), "XI.1.1.a")

    assert finding.kind == "missing"
    assert finding.location == "annex_xi.intended_tasks"


@pytest.mark.parametrize(
    "value",
    [{}, {"nested": "map"}, [], ["a", "b"]],
    ids=["empty-map", "map", "empty-list", "list"],
)
def test_a_non_scalar_value_is_malformed(registry: Registry, value: object) -> None:
    document = _one_field_document("annex_xi.training_data", value)

    finding = _finding_for(lint(document, registry), "XI.1.2.c")

    assert finding.kind == "malformed"
    assert finding.location == "annex_xi.training_data"


def test_a_falsey_number_subfield_is_present(registry: Registry) -> None:
    # The declared shape decides: 0 is a number, so a structured element
    # carrying it is present; only completeness may call a value absent. The
    # estimation method accompanies it so the consistency pass adds nothing.
    document = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": 0,
                    "estimation_method": "estimated",
                }
            }
        }
    )

    assert not [
        finding
        for finding in lint(document, registry)
        if finding.field_id == "XI.1.2.d"
    ]


@pytest.mark.parametrize(
    ("entry", "field_id"),
    [
        ("licence: no", "XI.1.1.f"),
        ("intended_tasks: false", "XI.1.1.a"),
        ("energy_consumption: yes", "XI.1.2.e"),
    ],
)
def test_yaml_boolean_coercions_are_malformed(
    registry: Registry, tmp_path: Path, entry: str, field_id: str
) -> None:
    # YAML 1.1 turns no/yes/on/off into booleans; an English answer must not
    # read as a documented value through the loader.
    path = tmp_path / "coerced.yaml"
    path.write_text(f"schema: 1\nannex_xi:\n  {entry}\n", encoding="utf-8")

    finding = _finding_for(lint(load_document(path), registry), field_id)

    assert finding.kind == "malformed"
    assert finding.location == f"annex_xi.{entry.split(':')[0]}"


def test_a_typoed_top_level_section_yields_an_unknown_finding(
    registry: Registry, tmp_path: Path
) -> None:
    path = tmp_path / "typo.yaml"
    path.write_text("schema: 1\nannex_x1:\n  intended_tasks: text\n", encoding="utf-8")

    findings = lint(load_document(path), registry)

    unknown = [finding for finding in findings if finding.kind == "unknown"]
    assert [finding.location for finding in unknown] == ["annex_x1"]
    assert unknown[0].field_id is None
    # The typo does not hide the fields that are genuinely absent.
    assert len(findings) == 23


def test_a_document_of_mixed_values_never_crashes(registry: Registry) -> None:
    document = Document(
        values={
            "annex_xi": {"intended_tasks": ["a"], "licence": None},
            "annex_xii": {"software_versions": {"a": 1}},
        }
    )

    kinds = {
        finding.field_id: finding.kind
        for finding in lint(document, registry)
        if finding.field_id is not None
    }

    assert kinds["XI.1.1.a"] == "malformed"
    assert kinds["XI.1.1.f"] == "missing"
    assert kinds["XII.1.e"] == "malformed"


def test_render_cites_the_field_with_everything_the_registry_holds(
    registry: Registry,
) -> None:
    field = registry.by_id["XI.1.2.e"]
    finding = _finding_for(lint(Document(values={}), registry), "XI.1.2.e")

    text = render_finding(finding, registry)

    assert "[MISSING] XI.1.2.e" in text
    assert "Annex XI, Section 1, point 2(e)" in text
    assert "owed to: AI Office, NCAs" in text
    assert field.form.rows, "the fixture field carries no Form rows"
    for row in field.form.rows:
        assert row in text
    assert "known or estimated energy consumption of the model." in text
    assert "If the energy consumption is unknown" in text
    # The footer is the run's closing line, not part of a citation block.
    assert FOOTER not in text


def test_render_keeps_recipients_and_audience_flags_both(registry: Registry) -> None:
    # XI.1.2.a is flagged downstream-only in the Form while the Act owes it to
    # the AI Office and the NCAs; the render must not infer suppression.
    finding = _finding_for(lint(Document(values={}), registry), "XI.1.2.a")

    text = render_finding(finding, registry)

    assert "owed to: AI Office, NCAs" in text
    assert "Form audience flags: downstream" in text


def test_render_uses_the_annex_xii_citation_without_a_section(
    registry: Registry,
) -> None:
    finding = Finding("missing", "annex_xii.software_versions", "XII.1.e")

    text = render_finding(finding, registry)

    assert "Annex XII, point 1(e)" in text
    assert "owed to: downstream providers" in text


def test_render_cites_the_field_for_a_malformed_value(registry: Registry) -> None:
    finding = Finding("malformed", "annex_xi.training_data", "XI.1.2.c")

    text = render_finding(finding, registry)

    assert "[MALFORMED] XI.1.2.c" in text
    assert "Annex XI, Section 1, point 2(c)" in text


def test_render_reports_an_unknown_key_without_a_citation(registry: Registry) -> None:
    # The checks set the exact unknown message; the render only prints it.
    finding = Finding(
        "unknown",
        "annex_xi.training_datasets",
        message="no registry entry for this key",
    )

    text = render_finding(finding, registry)

    assert text.startswith(
        "[UNKNOWN] annex_xi.training_datasets - no registry entry for this key"
    )
    assert "Annex" not in text
    assert FOOTER not in text


def test_render_omits_the_guidance_line_when_the_field_carries_none(
    registry: Registry,
) -> None:
    # The render must cope with a field that carries no guidance.
    field = registry.by_id["XI.1.2.e"].model_copy(update={"guidance": None})
    without_guidance = replace(registry, by_id={**registry.by_id, "XI.1.2.e": field})
    finding = Finding("missing", "annex_xi.energy_consumption", "XI.1.2.e")

    text = render_finding(finding, without_guidance)

    assert "Guidance:" not in text
    assert "known or estimated energy consumption of the model." in text
