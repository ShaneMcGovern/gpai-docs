"""The typed pass inside ``lint``.

Every validation error becomes one finding: an extra key is unknown, anything
else malformed in one uniform style, with YAML's coercion traps caught rather
than coerced. Pass order: typed, then completeness, then unknown.
"""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from gpai_docs.documents import Document, load_document
from gpai_docs.lint import Finding, lint, render_finding
from gpai_docs.lint.findings import _shape_word, malformed_message
from gpai_docs.models import (
    DateValue,
    ModificationRecord,
    NotificationRecord,
    NumberValue,
    TextListValue,
    TextValue,
    UrlValue,
)
from gpai_docs.models.leaves import BooleanValue
from gpai_docs.registry import Registry, load

FOOTER = "engineering evidence, not a compliance verdict"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


def _lint_yaml(tmp_path: Path, registry: Registry, text: str) -> list[Finding]:
    path = tmp_path / "document.yaml"
    path.write_text(text, encoding="utf-8")
    return lint(load_document(path), registry)


def _malformed_for(findings: list[Finding], location: str) -> Finding:
    matches = [
        finding
        for finding in findings
        if finding.kind == "malformed" and finding.location == location
    ]
    assert len(matches) == 1, [finding.location for finding in findings]
    return matches[0]


def _unknowns(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.kind == "unknown"]


class _UrlProbe(BaseModel):
    """One url-typed field: no committed element carries ``type:url`` yet."""

    link: UrlValue | None = None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("schema: 1\n", 22),
        ("schema: 1\nsystemic_risk: true\n", 25),
        ("schema: 1\nsystemic_risk: false\n", 22),
    ],
    ids=["absent", "true", "false"],
)
def test_the_systemic_risk_marker_is_never_malformed_or_unknown(
    registry: Registry, tmp_path: Path, text: str, expected: int
) -> None:
    # Absent, true and false all read cleanly; the marker is a
    # top-level key like any other, and the conditional fields are skipped
    # while it is absent or false and checked when it is true.
    findings = _lint_yaml(tmp_path, registry, text)

    assert {finding.kind for finding in findings} == {"missing"}
    assert len(findings) == expected
    assert not _unknowns(findings)


def test_a_non_boolean_marker_is_one_typed_finding_and_nothing_more(
    registry: Registry, tmp_path: Path
) -> None:
    # A quoted "true" in the marker slot is malformed, never coerced, and
    # reads as no assertion at all: no second finding about the marker, and
    # no guessed Section 2 reading beside it.
    findings = _lint_yaml(tmp_path, registry, "schema: 1\nsystemic_risk: 'true'\n")

    marker = [finding for finding in findings if finding.location == "systemic_risk"]
    assert [
        (finding.kind, finding.field_id, finding.message) for finding in marker
    ] == [("malformed", None, "expected a boolean: 'true' is not a boolean")]
    assert not _unknowns(findings)
    assert not [
        finding
        for finding in findings
        if finding.field_id in {"XI.2.1", "XI.2.2", "XI.2.3"}
    ]


@pytest.mark.parametrize(
    "value",
    [
        "schema: 1\nsystemic_risk: 1\n",
        "schema: 1\nsystemic_risk: 0\n",
        "schema: 1\nsystemic_risk: null\n",
    ],
    ids=["one", "zero", "null"],
)
def test_a_coerced_marker_value_is_malformed(
    registry: Registry, tmp_path: Path, value: str
) -> None:
    findings = _lint_yaml(tmp_path, registry, value)

    marker = [finding for finding in findings if finding.kind == "malformed"]
    assert len(marker) == 1
    assert marker[0].location == "systemic_risk"


def test_a_text_element_with_a_non_string_value_is_malformed(
    registry: Registry,
) -> None:
    document = Document(values={"annex_xi": {"intended_tasks": 5}})

    finding = _malformed_for(lint(document, registry), "annex_xi.intended_tasks")

    assert finding.field_id == "XI.1.1.a"
    assert finding.message == "expected text: 5 is not text"


def test_a_list_where_text_belongs_is_malformed(registry: Registry) -> None:
    document = Document(values={"annex_xi": {"licence": ["Apache"]}})

    finding = _malformed_for(lint(document, registry), "annex_xi.licence")

    assert finding.message == "expected text: ['Apache'] is not text"


def test_a_yaml_boolean_is_malformed_and_not_also_missing(
    registry: Registry, tmp_path: Path
) -> None:
    # YAML 1.1 turns `no` into False; the declared shape is text, and the
    # malformed finding replaces the completeness one (malformed wins).
    findings = _lint_yaml(tmp_path, registry, "schema: 1\nannex_xi:\n  licence: no\n")

    licence = [finding for finding in findings if finding.field_id == "XI.1.1.f"]

    assert [(finding.kind, finding.message) for finding in licence] == [
        ("malformed", "expected text: False is not text")
    ]


@pytest.mark.parametrize(
    ("value", "shown", "hint"),
    [
        (True, "True", ""),
        ("2.3", "'2.3'", " (it reads as text when quoted; write it unquoted)"),
    ],
    ids=["bool", "numeric-string"],
)
def test_a_non_number_is_malformed(
    registry: Registry, value: object, shown: str, hint: str
) -> None:
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": value}}}
    )

    finding = _malformed_for(
        lint(document, registry), "annex_xi.computational_resources.training_flop"
    )

    assert finding.field_id == "XI.1.2.d"
    assert finding.message == f"expected a number: {shown} is not a number{hint}"


@pytest.mark.parametrize(
    ("value", "shown"),
    [(float("nan"), "nan"), (float("inf"), "inf")],
    ids=["nan", "inf"],
)
def test_a_non_finite_number_is_malformed(
    registry: Registry, value: float, shown: str
) -> None:
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": value}}}
    )

    finding = _malformed_for(
        lint(document, registry), "annex_xi.computational_resources.training_flop"
    )

    assert finding.message == f"expected a number: {shown} is not a number"


def test_a_non_scalar_number_is_one_malformed_finding(registry: Registry) -> None:
    # Pydantic reports both arms of the int | float union; one value is one
    # defect, at the field's own path.
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": [2.3e25]}}}
    )

    findings = lint(document, registry)

    assert [
        (finding.location, finding.message)
        for finding in findings
        if finding.field_id == "XI.1.2.d"
    ] == [
        (
            "annex_xi.computational_resources.training_flop",
            "expected a number: [2.3e+25] is not a number",
        )
    ]


def test_an_iso_datetime_string_is_not_a_date(
    registry: Registry, tmp_path: Path
) -> None:
    # The reader constructs no dates: the unquoted timestamp
    # arrives as a string, and the date shape accepts only the exact
    # YYYY-MM-DD form, refusing the time rather than truncating it.
    text = "schema: 1\nnotifications:\n  - notified_on: 2026-07-30T10:00:00Z\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "notifications[0].notified_on"
    )

    assert finding.field_id is None
    assert finding.message == ("expected a date: '2026-07-30T10:00:00Z' is not a date")


@pytest.mark.parametrize(
    ("entry", "shown"),
    [('"2026-13-01"', "'2026-13-01'"), ('"2026-7-2"', "'2026-7-2'")],
    ids=["bad-calendar-date", "bad-shape"],
)
def test_a_bad_date_string_is_malformed(
    registry: Registry, tmp_path: Path, entry: str, shown: str
) -> None:
    text = f"schema: 1\nnotifications:\n  - notified_on: {entry}\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "notifications[0].notified_on"
    )

    assert finding.message == f"expected a date: {shown} is not a date"


@pytest.mark.parametrize(
    "day", ["2026-13-01", "2026-02-30"], ids=["bad-month", "bad-day"]
)
def test_an_out_of_range_unquoted_date_is_malformed(
    registry: Registry, tmp_path: Path, day: str
) -> None:
    # The malformed example: the unquoted form is a finding, never a
    # parser exception.
    text = f"schema: 1\nnotifications:\n  - aware_on: {day}\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "notifications[0].aware_on"
    )

    assert finding.kind == "malformed"
    assert finding.message == f"expected a date: '{day}' is not a date"


def test_an_unquoted_timestamp_with_an_impossible_time_is_malformed(
    registry: Registry, tmp_path: Path
) -> None:
    text = "schema: 1\nnotifications:\n  - notified_on: 2026-01-01 25:00:00\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "notifications[0].notified_on"
    )

    assert finding.message == ("expected a date: '2026-01-01 25:00:00' is not a date")


def test_the_url_message_pins_the_scheme_rule(registry: Registry) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _UrlProbe(link="ftp://example.org")
    error = excinfo.value.errors(include_url=False)[0]

    assert malformed_message(error, registry, root=_UrlProbe) == (
        "expected an http or https URL: 'ftp://example.org' is not an http or https URL"
    )


def test_a_structured_element_that_is_not_a_mapping_is_malformed(
    registry: Registry,
) -> None:
    document = Document(values={"annex_xi": {"energy_consumption": "1,500 MWh"}})

    finding = _malformed_for(lint(document, registry), "annex_xi.energy_consumption")

    assert finding.field_id == "XI.1.2.e"
    assert finding.message == (
        "expected an energy mapping: '1,500 MWh' is not an energy mapping"
    )


def test_a_structured_subfield_of_the_wrong_type_is_malformed(
    registry: Registry,
) -> None:
    document = Document(
        values={"annex_xi": {"computational_resources": {"estimation_method": 7}}}
    )

    finding = _malformed_for(
        lint(document, registry), "annex_xi.computational_resources.estimation_method"
    )

    assert finding.field_id == "XI.1.2.d"
    assert finding.message == "expected text: 7 is not text"


def test_a_non_string_key_below_an_element_is_malformed(
    registry: Registry, tmp_path: Path
) -> None:
    # A non-string subfield key is a structural violation, not a
    # misspelt name; pydantic reports it as an invalid key, and the typed
    # pass pins it malformed at the bracket path.
    text = "schema: 1\nannex_xi:\n  computational_resources:\n    1: x\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "annex_xi.computational_resources[1]"
    )

    assert finding.kind == "malformed"
    assert finding.field_id == "XI.1.2.d"
    assert finding.message == "expected a valid value: 1 is not a valid value"


@pytest.mark.parametrize("token", ["2.3e24", "9e+24"], ids=["dot-less", "json-style"])
def test_an_unquoted_exponent_is_a_number(
    registry: Registry, tmp_path: Path, token: str
) -> None:
    # YAML 1.2 core floats take an optional dot and a signed-or-unsigned
    # exponent, so both spellings are numbers, no finding. Both
    # values stay under Art. 51(2)'s 10^25 threshold and carry their
    # estimation method, so the consistency pass adds nothing to the element
    # either.
    text = (
        "schema: 1\nannex_xi:\n  computational_resources:\n"
        f"    training_flop: {token}\n"
        "    estimation_method: extrapolated from the training logs\n"
    )

    findings = _lint_yaml(tmp_path, registry, text)

    assert [finding for finding in findings if finding.field_id == "XI.1.2.d"] == []


@pytest.mark.parametrize(
    "token",
    ["2.3e25", "9e+24", "017", "0x1F"],
    ids=["dot-less", "json-style", "leading-zero", "hex"],
)
def test_a_quoted_number_is_a_string_with_the_unquote_hint(
    registry: Registry, tmp_path: Path, token: str
) -> None:
    # A quoted numeric string is a string: malformed, never coerced. The
    # hint names the one mechanical remedy (unquoting) and fires exactly for
    # the strings the reader would construct as numbers without quotes.
    text = (
        "schema: 1\nannex_xi:\n  computational_resources:\n"
        f'    training_flop: "{token}"\n'
    )

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text),
        "annex_xi.computational_resources.training_flop",
    )

    assert finding.message == (
        f"expected a number: '{token}' is not a number "
        "(it reads as text when quoted; write it unquoted)"
    )


@pytest.mark.parametrize(
    "token", ["12:30", "1_000", "lots"], ids=["sexagesimal", "underscored", "text"]
)
def test_a_quoted_string_that_is_not_a_number_gets_no_unquote_hint(
    registry: Registry, tmp_path: Path, token: str
) -> None:
    # Unquoting would leave these strings, so promising a number would
    # mislabel the value: the hint stays off for them.
    text = (
        "schema: 1\nannex_xi:\n  computational_resources:\n"
        f'    training_flop: "{token}"\n'
    )

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text),
        "annex_xi.computational_resources.training_flop",
    )

    assert finding.message == f"expected a number: '{token}' is not a number"


@pytest.mark.parametrize(
    "token", ["12:30", "1_000"], ids=["sexagesimal", "underscored"]
)
def test_yaml_1_1_number_spellings_stay_strings(
    registry: Registry, tmp_path: Path, token: str
) -> None:
    # Neither YAML 1.1 form is constructed as a number, so both
    # are malformed in a number slot, never silently reinterpreted.
    text = (
        "schema: 1\nannex_xi:\n  computational_resources:\n"
        f"    training_flop: {token}\n"
    )

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text),
        "annex_xi.computational_resources.training_flop",
    )

    assert finding.message == f"expected a number: '{token}' is not a number"


def test_a_yaml_float_round_trips_as_a_number(
    registry: Registry, tmp_path: Path
) -> None:
    # The value stays under Art. 51(2)'s 10^25 threshold and carries its
    # estimation method, so the consistency pass adds nothing to the element
    # either.
    text = (
        "schema: 1\nannex_xi:\n  computational_resources:\n"
        "    training_flop: 2.3e+24\n"
        "    estimation_method: extrapolated from the training logs\n"
    )

    findings = _lint_yaml(tmp_path, registry, text)

    assert [finding for finding in findings if finding.field_id == "XI.1.2.d"] == []


def test_the_loader_rides_records_through_to_the_typed_pass(
    registry: Registry, tmp_path: Path
) -> None:
    # The record values include unquoted dates, which stay strings under the
    # 1.2-core reader and still validate.
    text = (
        "schema: 1\n"
        "notifications:\n"
        "  - compute_flop: 2.3e+25\n"
        "    estimation_method: estimated from training time\n"
        "    aware_on: 2026-07-20\n"
        "    notified_on: 2026-07-30\n"
        "modifications:\n"
        "  - description: continued pre-training\n"
        "    training_flop: 9.0e+24\n"
        "    provider_record: true\n"
    )
    path = tmp_path / "document.yaml"
    path.write_text(text, encoding="utf-8")

    loaded = load_document(path)

    assert set(loaded.records) == {"notifications", "modifications"}
    assert [finding.kind for finding in lint(loaded, registry)] == ["missing"] * 22

    # The same pass refusing a record proves it reads them at all: a
    # number where a date belongs is malformed, not silently dropped.
    broken = tmp_path / "broken.yaml"
    broken.write_text("schema: 1\nnotifications:\n  - aware_on: 12345\n", "utf-8")
    kinds = [finding.kind for finding in lint(load_document(broken), registry)]
    assert "malformed" in kinds, kinds


def test_a_record_entry_field_of_the_wrong_type_is_malformed(
    registry: Registry, tmp_path: Path
) -> None:
    text = "schema: 1\nnotifications:\n  - compute_flop: lots\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "notifications[0].compute_flop"
    )

    assert finding.field_id is None
    assert finding.message == "expected a number: 'lots' is not a number"


def test_a_provider_record_that_is_not_a_boolean_is_malformed(
    registry: Registry, tmp_path: Path
) -> None:
    text = "schema: 1\nmodifications:\n  - provider_record: 'true'\n"

    finding = _malformed_for(
        _lint_yaml(tmp_path, registry, text), "modifications[0].provider_record"
    )

    assert finding.message == "expected a boolean: 'true' is not a boolean"


def test_a_non_mapping_record_entry_in_a_raw_document_is_malformed(
    registry: Registry,
) -> None:
    # The loader refuses this shape on disk (exit 2); a Document
    # built in code bypasses the loader, and the typed pass still reports the
    # entry rather than crashing.
    document = Document(values={}, records={"notifications": [1]})

    finding = _malformed_for(lint(document, registry), "notifications[0]")

    assert finding.message == "expected a mapping: 1 is not a mapping"


def test_an_unknown_structured_subfield_names_the_full_path(
    registry: Registry,
) -> None:
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flops": 2.3e25}}}
    )

    findings = lint(document, registry)

    assert [
        (finding.location, finding.field_id, finding.message)
        for finding in _unknowns(findings)
    ] == [("annex_xi.computational_resources.training_flops", None, "no such field")]
    # The element itself is present (its mapping exists); only the typo shows.
    assert [finding for finding in findings if finding.field_id == "XI.1.2.d"] == []


def test_an_unknown_record_field_is_a_finding_with_the_entry_path(
    registry: Registry, tmp_path: Path
) -> None:
    text = "schema: 1\nnotifications:\n  - notified_at: 2026-07-30\n"

    unknowns = _unknowns(_lint_yaml(tmp_path, registry, text))

    assert [(finding.location, finding.message) for finding in unknowns] == [
        ("notifications[0].notified_at", "no such field")
    ]


def test_a_top_level_typo_keeps_the_bare_key(registry: Registry) -> None:
    document = Document(values={"annex_x1": {"intended_tasks": "text"}})

    unknowns = _unknowns(lint(document, registry))

    assert [(finding.location, finding.message) for finding in unknowns] == [
        ("annex_x1", "no registry entry for this key")
    ]


def test_a_section_level_typo_is_unknown_with_the_section_path(
    registry: Registry,
) -> None:
    document = Document(values={"annex_xi": {"training_datasets": "the datasets"}})

    unknowns = _unknowns(lint(document, registry))

    assert [(finding.location, finding.message) for finding in unknowns] == [
        ("annex_xi.training_datasets", "no registry entry for this key")
    ]


def test_unknowns_are_sorted_by_path_not_validation_order(
    registry: Registry,
) -> None:
    # Pydantic reports the extras in input order (notified_at first); the
    # unknown pass re-sorts them by path string.
    document = Document(values={"notifications": [{"notified_at": 1, "bogus": 2}]})

    unknowns = _unknowns(lint(document, registry))

    assert [finding.location for finding in unknowns] == [
        "notifications[0].bogus",
        "notifications[0].notified_at",
    ]


@pytest.mark.parametrize(
    ("path", "field_id", "value", "missing"),
    [
        ("annex_xi.computational_resources", "XI.1.2.d", {}, True),
        (
            "annex_xi.computational_resources",
            "XI.1.2.d",
            {"training_flop": None, "estimation_method": None},
            True,
        ),
        (
            "annex_xi.computational_resources",
            "XI.1.2.d",
            {"training_flop": 1, "estimation_method": "extrapolated"},
            False,
        ),
        ("annex_xi.energy_consumption", "XI.1.2.e", {"training": {}}, True),
        (
            "annex_xi.energy_consumption",
            "XI.1.2.e",
            {"training": {"amount": None}, "inference": None},
            True,
        ),
        (
            "annex_xi.energy_consumption",
            "XI.1.2.e",
            {"training": {"amount": 1200}},
            False,
        ),
    ],
    ids=[
        "empty-compute",
        "all-null-compute",
        "compute-leaves",
        "empty-training-arm",
        "all-null-energy",
        "one-leaf-energy",
    ],
)
def test_structured_presence_needs_a_non_null_leaf(
    registry: Registry,
    path: str,
    field_id: str,
    value: dict[str, object],
    missing: bool,
) -> None:
    # A structured element is present iff at least one non-null leaf sits
    # beneath it: an empty or all-null mapping describes nothing
    # and is an absence, reported by completeness like any other.
    section, _, key = path.partition(".")
    document = Document(values={section: {key: value}})

    findings = [
        finding for finding in lint(document, registry) if finding.location == path
    ]

    assert [(finding.kind, finding.field_id) for finding in findings] == (
        [("missing", field_id)] if missing else []
    )


def test_an_empty_structured_mapping_is_missing_with_the_element_citation(
    registry: Registry,
) -> None:
    document = Document(values={"annex_xi": {"computational_resources": {}}})
    finding = next(
        finding
        for finding in lint(document, registry)
        if finding.location == "annex_xi.computational_resources"
    )

    text = render_finding(finding, registry)

    assert text.startswith(
        "[MISSING] XI.1.2.d - Computational resources used to train the model\n"
        "  Key: annex_xi.computational_resources\n"
        "  Annex XI, Section 1, point 2(d)"
    )


def test_a_recursive_mapping_alias_does_not_crash_the_presence_walk(
    registry: Registry, tmp_path: Path
) -> None:
    # YAML anchors can make a mapping reference itself; the walk that looks
    # for a non-null leaf must terminate on one.
    text = "schema: 1\nannex_xi:\n  computational_resources: &x\n    a: *x\n"

    findings = _lint_yaml(tmp_path, registry, text)

    kinds = {finding.location: finding.kind for finding in findings}
    assert kinds["annex_xi.computational_resources"] == "missing"
    assert kinds["annex_xi.computational_resources.a"] == "unknown"


@pytest.mark.parametrize("value", [None, ""], ids=["null", "empty-string"])
def test_an_absent_text_value_is_missing_without_a_message(
    registry: Registry, value: object
) -> None:
    document = Document(values={"annex_xi": {"licence": value}})

    findings = lint(document, registry)

    assert [
        (finding.kind, finding.message)
        for finding in findings
        if finding.field_id == "XI.1.1.f"
    ] == [("missing", None)]


def test_findings_run_typed_then_completeness_then_unknown(
    registry: Registry,
) -> None:
    document = Document(
        values={"annex_xi": {"licence": False, "training_datasets": "the datasets"}}
    )

    findings = lint(document, registry)

    assert [finding.kind for finding in findings] == (
        ["malformed"] + ["missing"] * 21 + ["unknown"]
    )
    # The typed finding leads even though its field is sixth in registry order.
    assert findings[0].field_id == "XI.1.1.f"
    assert findings[-1].location == "annex_xi.training_datasets"


def test_render_cites_a_malformed_finding_with_its_reason(registry: Registry) -> None:
    document = Document(values={"annex_xi": {"energy_consumption": "1,500 MWh"}})
    finding = _malformed_for(lint(document, registry), "annex_xi.energy_consumption")

    text = render_finding(finding, registry)

    assert text.startswith(
        "[MALFORMED] XI.1.2.e - Energy consumption\n"
        "  Reason: expected an energy mapping: '1,500 MWh' is not an "
        "energy mapping\n"
        "  Key: annex_xi.energy_consumption\n"
        "  Annex XI, Section 1, point 2(e) - owed to: AI Office, NCAs\n"
    )
    assert "known or estimated energy consumption of the model." in text
    assert FOOTER not in text


def test_render_reports_a_malformed_finding_without_a_field(
    registry: Registry,
) -> None:
    finding = Finding(
        "malformed",
        "notifications",
        message="expected a list of records: {'a': 1} is not a list of records",
    )

    text = render_finding(finding, registry)

    assert text == (
        "[MALFORMED] notifications\n"
        "  Reason: expected a list of records: {'a': 1} is not a list of records"
    )


def test_render_reports_a_rule_finding_with_its_reason(registry: Registry) -> None:
    # A consistency rule's finding renders like the other blocks (headline,
    # then its message line) before the element's own citation.
    finding = Finding(
        "inconsistent",
        "annex_xi.computational_resources",
        "XI.1.2.d",
        message=(
            "training compute 2.5e+25 FLOP is greater than 10^25 and the "
            "document carries no Art. 52(1) notification record"
        ),
    )

    text = render_finding(finding, registry)

    assert text.startswith(
        "[INCONSISTENT] XI.1.2.d - Computational resources used to train the "
        "model\n"
        "  Reason: training compute 2.5e+25 FLOP is greater than 10^25 and the "
        "document carries no Art. 52(1) notification record\n"
        "  Key: annex_xi.computational_resources\n"
    )
    assert "  Basis:" not in text


def test_render_names_a_field_less_finding_by_its_label(registry: Registry) -> None:
    # The record-finding headline: a field-less finding carries a
    # rule-authored label, rendered after the location, and the --json
    # payload keeps it as an always-present key.
    finding = Finding(
        "inconsistent",
        "notifications[0]",
        label="Art. 52 notification record",
        message=(
            "the notification of 2026-08-04 follows the trigger of 2026-07-20 "
            "by 15 days, beyond the two weeks of Art. 52(1)"
        ),
    )

    text = render_finding(finding, registry)

    assert text.startswith(
        "[INCONSISTENT] notifications[0] - Art. 52 notification record\n"
        "  Reason: the notification of 2026-08-04 follows the trigger of "
        "2026-07-20 by 15 days, beyond the two weeks of Art. 52(1)"
    )
    payload = json.loads(json.dumps({"findings": [asdict(finding)]}))
    assert payload["findings"][0]["label"] == "Art. 52 notification record"


def test_render_keeps_the_registry_label_on_a_field_bearing_finding(
    registry: Registry,
) -> None:
    # A label names a finding the registry has no element to cite; on an
    # element-scoped finding the registry's own label is what renders.
    finding = Finding(
        "inconsistent",
        "annex_xi.computational_resources",
        "XI.1.2.d",
        message="training compute is reported without an estimation method",
        label="Rule-made name",
    )

    text = render_finding(finding, registry)

    assert text.startswith(
        "[INCONSISTENT] XI.1.2.d - Computational resources used to train the model\n"
    )
    assert "Rule-made name" not in text


def test_render_prints_the_bases_after_the_element_citation(registry: Registry) -> None:
    # A finding may carry bases beyond the element's own source: the
    # cited sources render as the element citation does, located and quoted
    # verbatim, under one ``Basis:`` line, and Form bases render by row id and
    # label, all after the element's own block.
    finding = Finding(
        "missing",
        "annex_xi.energy_consumption",
        "XI.1.2.e",
        citations=["reg-2024-1689-annex-xi-1-2-e-note"],
        basis_forms=[
            (
                "energy-consumption/measurement-methodology-energy",
                "Measurement methodology",
            )
        ],
    )

    text = render_finding(finding, registry)

    assert text == (
        "[MISSING] XI.1.2.e - Energy consumption\n"
        "  Key: annex_xi.energy_consumption\n"
        "  Annex XI, Section 1, point 2(e) - owed to: AI Office, NCAs\n"
        "  Form rows: energy-consumption/amount-of-energy-used-for-training, "
        "energy-consumption/measurement-methodology-energy, "
        "energy-consumption/benchmarked-amount-of-computation-used-for-inference, "
        "energy-consumption/measurement-methodology-inference\n"
        "  Form audience flags: ai_office, nca\n"
        '  "known or estimated energy consumption of the model."\n'
        "  Guidance: If the energy consumption is unknown, an estimate based on "
        "the training compute is acceptable; state the basis.\n"
        "  Basis:\n"
        "  Annex XI, Section 1, note following point 2(e)\n"
        '  "With regard to point (e), where the energy consumption of the model '
        "is unknown, the energy consumption may be based on information about "
        'computational resources used."\n'
        "  Form: energy-consumption/measurement-methodology-energy - "
        "Measurement methodology"
    )
    # The --json payload (the mapping the CLI dumps) carries the same bases.
    payload = asdict(finding)
    assert payload["citations"] == ["reg-2024-1689-annex-xi-1-2-e-note"]
    assert payload["basis_forms"] == [
        ("energy-consumption/measurement-methodology-energy", "Measurement methodology")
    ]


def test_render_prints_a_citation_only_basis(registry: Registry) -> None:
    # A finding may rest on a cited source alone: one ``Basis:``
    # line over the located, verbatim text, and no Form line.
    finding = Finding(
        "missing",
        "annex_xi.energy_consumption",
        "XI.1.2.e",
        citations=["reg-2024-1689-annex-xi-1-2-e-note"],
    )

    text = render_finding(finding, registry)

    assert text.endswith(
        "  Basis:\n"
        "  Annex XI, Section 1, note following point 2(e)\n"
        '  "With regard to point (e), where the energy consumption of the model '
        "is unknown, the energy consumption may be based on information about "
        'computational resources used."'
    )
    assert "Form:" not in text


def test_render_heads_a_form_only_basis_too(registry: Registry) -> None:
    # A finding whose only basis is a Form row heads its line as well
    # (the bases follow under one ``Basis:`` line), and the label
    # rendered is ``form.yaml``'s for that row, verbatim.
    row = "energy-consumption/measurement-methodology-energy"
    label = next(entry.label for entry in registry.form.rows if entry.row == row)

    finding = Finding(
        "missing",
        "annex_xi.energy_consumption",
        "XI.1.2.e",
        basis_forms=[(row, label)],
    )

    text = render_finding(finding, registry)

    assert label == "Measurement methodology"
    assert text.endswith(f"  Basis:\n  Form: {row} - {label}")


def test_an_unresolved_citation_names_the_finding_and_the_source(
    registry: Registry,
) -> None:
    # A citation that does not resolve is a data defect, never something the
    # render skips: the raise names the missing source id together with the
    # finding's own kind and location, so the defect is localisable.
    finding = Finding(
        "missing",
        "annex_xi.energy_consumption",
        "XI.1.2.e",
        citations=["reg-2024-1689-ghost"],
    )

    with pytest.raises(KeyError) as excinfo:
        render_finding(finding, registry)

    assert excinfo.value.args[0] == (
        "unknown source id 'reg-2024-1689-ghost' cited by the missing finding "
        "at 'annex_xi.energy_consumption'"
    )


@pytest.mark.parametrize(
    ("annotation", "word"),
    [
        (TextValue, "text"),
        (TextListValue, "a list of text"),
        (NumberValue, "a number"),
        (DateValue, "a date"),
        (UrlValue, "an http or https URL"),
        (BooleanValue, "a boolean"),
        (bool, "a boolean"),
        (NotificationRecord, "a mapping"),
        (ModificationRecord, "a mapping"),
        (list[NotificationRecord], "a list of records"),
        (list[int], "a list"),
        (None, None),
    ],
    ids=[
        "text",
        "text-list",
        "number",
        "date",
        "url",
        "boolean",
        "bare-boolean",
        "record",
        "modification",
        "record-list",
        "plain-list",
        "unresolvable",
    ],
)
def test_the_shape_word_table_is_pinned(annotation: object, word: str | None) -> None:
    # The leaf vocabulary's reading, one word per leaf type: the
    # message layer names the declared shape of a slot below an element.
    assert _shape_word(annotation) == word


def test_an_element_without_a_type_tag_falls_back_to_its_model_shape(
    registry: Registry,
) -> None:
    # Completeness alone is legal in the data grammar; a tagless field's
    # message reads the model annotation (the element's root model) rather
    # than failing the run.
    tagless = registry.by_id["XI.1.1.a"].model_copy(update={"rules": ["completeness"]})
    without_tag = replace(
        registry,
        fields=[
            tagless if field.id == "XI.1.1.a" else field for field in registry.fields
        ],
        by_id={**registry.by_id, "XI.1.1.a": tagless},
    )

    assert (
        malformed_message(
            {
                "type": "value_error",
                "loc": ("annex_xi", "intended_tasks"),
                "msg": "Value error, not a string: 5",
                "input": 5,
            },
            without_tag,
        )
        == "expected a mapping: 5 is not a mapping"
    )


@pytest.mark.parametrize(
    "loc",
    [
        ("annex_xi", "ghost"),
        ("notifications", "ghost"),
        (0,),
        ("annex_xi", "computational_resources", "training_flop", "ghost"),
    ],
    ids=["unknown-element", "unknown-section", "root-index", "below-a-leaf"],
)
def test_an_unresolved_path_falls_back_to_a_generic_shape(
    registry: Registry, loc: tuple[int | str, ...]
) -> None:
    assert (
        malformed_message(
            {
                "type": "value_error",
                "loc": loc,
                "msg": "Value error, nope",
                "input": None,
            },
            registry,
        )
        == "expected a valid value: None is not a valid value"
    )
