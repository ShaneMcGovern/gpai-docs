"""Pin the consistency pass and its rule engine.

``run_consistency`` hands each rule one ``RuleContext`` and returns findings
sorted by rule id, ties in emission order; stub rules keep the engine's tests
independent of which rules the catalogue holds.
"""

import math
import re
from pathlib import Path
from typing import Literal

import pytest

import gpai_docs.lint.consistency as consistency
from gpai_docs.documents import Document, load_document
from gpai_docs.lint import Finding, lint, render_finding
from gpai_docs.lint.consistency import Rule, RuleContext, run_consistency
from gpai_docs.models import ModelDocument
from gpai_docs.registry import Registry, load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "model-docs-example.yaml"

# The subject every element-scoped stub rule points at; the registry entry
# is XI.1.2.d, a valid document key.
SUBJECT = "annex_xi.computational_resources"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


@pytest.fixture(scope="module")
def example() -> Document:
    return load_document(EXAMPLE)


def _stub_rule(
    rule_id: str,
    *locations: str,
    scope: Literal["element", "document"] = "element",
    field: str | None = SUBJECT,
    citations: tuple[str, ...] = (),
    basis_forms: tuple[tuple[str, str], ...] = (),
) -> Rule:
    """A rule emitting one ``inconsistent`` finding per location, in order."""

    def check(context: RuleContext) -> list[Finding]:
        return [
            Finding(
                kind="inconsistent",
                location=location,
                message=f"{rule_id} fired at {location}",
            )
            for location in locations
        ]

    return Rule(
        id=rule_id,
        scope=scope,
        field=field,
        citations=citations,
        basis_forms=basis_forms,
        check=check,
    )


def _recording_rule(seen: list[RuleContext]) -> Rule:
    """An element-scoped rule that records calls and would emit a finding."""

    def check(context: RuleContext) -> list[Finding]:
        seen.append(context)
        return [Finding(kind="inconsistent", location=SUBJECT)]

    return Rule(
        id="stub.rule",
        scope="element",
        field=SUBJECT,
        citations=(),
        basis_forms=(),
        check=check,
    )


def test_the_demo_fixture_carries_no_consistency_finding(
    registry: Registry, example: Document
) -> None:
    # The shipped example is the clean-run demo: the consistency wiring adds
    # nothing to a clean run, and the demo must stay clean as rules land.
    assert run_consistency(example, registry) == []
    assert [
        finding for finding in lint(example, registry) if finding.kind == "inconsistent"
    ] == []


def test_the_consistency_pass_runs_last(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pass order is typed, completeness, unknown, consistency: the stub rule's
    # finding comes after all 22 completeness ones.
    monkeypatch.setattr(consistency, "RULES", (_stub_rule("stub.rule", SUBJECT),))

    findings = lint(Document(values={}), registry)

    assert [finding.kind for finding in findings] == ["missing"] * 22 + ["inconsistent"]
    assert findings[-1].location == SUBJECT


def test_a_rule_with_nothing_to_report_contributes_nothing(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A silent rule does no field lookup (the ghost field would raise if it
    # did), while the rules that fire still report.
    silent = _stub_rule("a.rule", field="annex_xi.ghost")
    firing = _stub_rule("b.rule", "loc.zero", scope="document", field=None)
    monkeypatch.setattr(consistency, "RULES", (silent, firing))

    findings = run_consistency(Document(values={}), registry)

    assert [finding.location for finding in findings] == ["loc.zero"]


def test_findings_sort_by_rule_id_with_ties_in_emission_order(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Findings sort by rule id, ties in the order their rule emitted them
    # (document order is each rule's own deterministic emission order).
    later = _stub_rule("b.rule", "loc.one", "loc.two", scope="document", field=None)
    earlier = _stub_rule("a.rule", "loc.zero", scope="document", field=None)
    monkeypatch.setattr(consistency, "RULES", (later, earlier))

    findings = run_consistency(Document(values={}), registry)

    assert [finding.location for finding in findings] == [
        "loc.zero",
        "loc.one",
        "loc.two",
    ]


def test_an_element_rule_finding_takes_the_registry_id_of_its_field(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Element-scoped findings resolve ``rule.field`` through the registry's
    # model_field paths, with the rule's citations and Form bases verbatim.
    rule = _stub_rule(
        "element.rule",
        SUBJECT,
        citations=("reg-2024-1689-art-51-2",),
        basis_forms=(
            (
                "energy-consumption/measurement-methodology-energy",
                "Measurement methodology",
            ),
        ),
    )
    monkeypatch.setattr(consistency, "RULES", (rule,))

    (finding,) = run_consistency(Document(values={}), registry)

    assert finding.field_id == "XI.1.2.d"
    assert finding.citations == ["reg-2024-1689-art-51-2"]
    assert finding.basis_forms == [
        ("energy-consumption/measurement-methodology-energy", "Measurement methodology")
    ]


def test_a_document_rule_finding_has_no_field_id(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = _stub_rule("doc.rule", "notifications[0]", scope="document", field=None)
    monkeypatch.setattr(consistency, "RULES", (rule,))

    (finding,) = run_consistency(Document(values={}), registry)

    assert finding.field_id is None


def test_an_element_rule_naming_a_field_the_registry_lacks_is_a_defect(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An element-scoped rule naming a field the registry lacks is a data
    # defect, named with its rule and field, not a field-less finding.
    rule = _stub_rule("drift.rule", SUBJECT, field="annex_xi.ghost")
    monkeypatch.setattr(consistency, "RULES", (rule,))

    with pytest.raises(KeyError, match=r"drift\.rule.*annex_xi\.ghost"):
        run_consistency(Document(values={}), registry)


def test_the_context_carries_the_values_records_and_validated_model(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A rule reads the raw top-level mapping (records included) and the
    # validated model, not a second interpretation of either.
    seen: list[RuleContext] = []
    monkeypatch.setattr(consistency, "RULES", (_recording_rule(seen),))
    document = Document(
        values={"annex_xi": {"licence": "Apache-2.0"}},
        records={"notifications": [{"compute_flop": 2.3e25}]},
    )

    run_consistency(document, registry)

    (context,) = seen
    assert context.values == {
        "annex_xi": {"licence": "Apache-2.0"},
        "notifications": [{"compute_flop": 2.3e25}],
    }
    assert context.registry is registry
    assert isinstance(context.validated, ModelDocument)
    assert context.validated.annex_xi is not None
    assert context.validated.annex_xi.licence is not None
    assert context.validated.annex_xi.licence.root == "Apache-2.0"
    assert context.validated.notifications[0].compute_flop == 2.3e25


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        ({"annex_xi": {"licence": False}}, "malformed"),
        ({"annex_xi": {"training_datasets": "the datasets"}}, "unknown"),
    ],
    ids=["malformed", "unknown"],
)
def test_a_document_the_typed_pass_refused_runs_no_rule(
    registry: Registry,
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, object],
    kind: str,
) -> None:
    # A document the typed pass refuses whole runs no rule: ``validated is
    # None`` means no check is called, and the typed finding tells the story.
    seen: list[RuleContext] = []
    document = Document(values=values)

    monkeypatch.setattr(consistency, "RULES", (_recording_rule(seen),))

    assert run_consistency(document, registry) == []
    assert seen == []
    kinds = {finding.kind for finding in lint(document, registry)}
    assert kind in kinds
    assert "inconsistent" not in kinds


# R1, ``notification.due``: the Art. 52(1) two-week window.

# R1's pinned basis: Art. 51(1)(a), Art. 51(2) and Art. 52(1).
NOTIFICATION_CITATIONS = [
    "reg-2024-1689-art-51-1-a",
    "reg-2024-1689-art-51-2",
    "reg-2024-1689-art-52-1",
]


@pytest.fixture
def r1(monkeypatch: pytest.MonkeyPatch) -> Rule:
    """R1 alone from the catalogue: its matrix, no other rule's noise."""
    rule = next(rule for rule in consistency.RULES if rule.id == "notification.due")
    monkeypatch.setattr(consistency, "RULES", (rule,))
    return rule


def _notified(
    training_flop: object, notifications: list[dict[str, object]] | None = None
) -> Document:
    """A document whose XI.1.2.d carries ``training_flop`` and the records."""
    records: dict[str, object] = {}
    if notifications is not None:
        records["notifications"] = notifications
    return Document(
        values={
            "annex_xi": {"computational_resources": {"training_flop": training_flop}}
        },
        records=records,
    )


@pytest.mark.parametrize("training_flop", [1e25, 10**25], ids=["float", "int"])
def test_r1_is_quiet_at_exactly_the_threshold(
    registry: Registry, r1: Rule, training_flop: object
) -> None:
    # Art. 51(2) says "greater than": exactly 10^25 (as the float ``1e25`` or
    # the exact int) does not trigger, so the rule stays quiet.
    assert run_consistency(_notified(training_flop), registry) == []


@pytest.mark.parametrize(
    ("training_flop", "value_text"),
    [
        (1.1e25, "1.1e+25"),
        (math.nextafter(1e25, math.inf), "1.0000000000000003e+25"),
        (10**25 + 1, "10000000000000000000000001"),
        (10**26, "100000000000000000000000000"),
    ],
    ids=["float", "nextafter", "int-just-above", "int"],
)
def test_r1_reports_above_the_threshold_without_a_record(
    registry: Registry, r1: Rule, training_flop: object, value_text: str
) -> None:
    # Above the threshold, with no record: one finding carrying the value as
    # Python writes it, the element's registry id, and the rule's three cited
    # sources.
    (finding,) = run_consistency(_notified(training_flop), registry)

    assert finding.kind == "inconsistent"
    assert finding.location == SUBJECT
    assert finding.message == (
        f"training compute {value_text} FLOP is greater than 10^25 and the "
        "document carries no Art. 52(1) notification record"
    )
    assert finding.field_id == "XI.1.2.d"
    assert finding.citations == NOTIFICATION_CITATIONS
    assert finding.basis_forms == []


def test_r1_treats_an_empty_records_section_as_no_record(
    registry: Registry, r1: Rule
) -> None:
    # A records section present but holding no entry is no record, exactly as
    # an absent section is.
    (finding,) = run_consistency(_notified(2.5e25, []), registry)

    assert finding.message == (
        "training compute 2.5e+25 FLOP is greater than 10^25 and the document "
        "carries no Art. 52(1) notification record"
    )


def test_r1_reports_a_notification_beyond_the_window(
    registry: Registry, r1: Rule
) -> None:
    document = _notified(
        2.5e25, [{"aware_on": "2026-07-20", "notified_on": "2026-08-04"}]
    )

    (finding,) = run_consistency(document, registry)

    assert finding.message == (
        "the notification of 2026-08-04 follows the trigger of 2026-07-20 "
        "by 15 days, beyond the two weeks of Art. 52(1)"
    )
    assert finding.location == "notifications[0]"
    assert finding.label == "Art. 52 notification record"
    assert finding.field_id is None
    assert finding.citations == NOTIFICATION_CITATIONS


def test_r1_is_quiet_at_exactly_two_weeks(registry: Registry, r1: Rule) -> None:
    # Exactly 14 days is inside "within two weeks", so the rule stays quiet.
    document = _notified(
        2.5e25, [{"aware_on": "2026-07-20", "notified_on": "2026-08-03"}]
    )

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize(
    "notified_on", ["2026-07-19", "2025-07-19"], ids=["one-day", "one-year"]
)
def test_r1_reports_a_notification_that_precedes_its_trigger(
    registry: Registry, r1: Rule, notified_on: str
) -> None:
    # A negative window is an inconsistency of dates, never rendered as a
    # "by {days} days" lateness.
    document = _notified(
        2.5e25, [{"aware_on": "2026-07-20", "notified_on": notified_on}]
    )

    (finding,) = run_consistency(document, registry)

    assert finding.message == (
        f"the notification date {notified_on} precedes the trigger date 2026-07-20"
    )
    assert finding.location == "notifications[0]"
    assert finding.label == "Art. 52 notification record"
    assert finding.field_id is None


@pytest.mark.parametrize(
    "entry",
    [
        {},
        {"compute_flop": 2.5e25},
        {"compute_flop": 2.5e25, "aware_on": "2026-07-20"},
        {"compute_flop": 2.5e25, "notified_on": "2026-08-04"},
    ],
    ids=["empty", "compute-only", "no-notified-on", "no-aware-on"],
)
def test_r1_stays_silent_when_a_record_lacks_its_dates(
    registry: Registry, r1: Rule, entry: dict[str, object]
) -> None:
    # An entry exists, so no-record is not the story; a window cannot be
    # computed without both dates, and the completeness table owns the
    # absence.
    assert run_consistency(_notified(2.5e25, [entry]), registry) == []


def test_r1_is_quiet_once_an_entry_is_within_the_window(
    registry: Registry, r1: Rule
) -> None:
    # Any entry is a record, whatever else it lacks; a window inside the two
    # weeks gives R1 nothing to report.
    document = _notified(
        2.5e25, [{"aware_on": "2026-04-20", "notified_on": "2026-04-30"}]
    )

    assert run_consistency(document, registry) == []


def test_r1_checks_every_record_in_document_order(registry: Registry, r1: Rule) -> None:
    # Records are one finding each, in document order.
    document = _notified(
        2.5e25,
        [
            {"aware_on": "2026-01-01", "notified_on": "2026-01-05"},
            {"aware_on": "2026-02-01", "notified_on": "2026-02-20"},
            {"aware_on": "2026-03-01", "notified_on": "2026-02-25"},
        ],
    )

    findings = run_consistency(document, registry)

    assert [finding.message for finding in findings] == [
        "the notification of 2026-02-20 follows the trigger of 2026-02-01 "
        "by 19 days, beyond the two weeks of Art. 52(1)",
        "the notification date 2026-02-25 precedes the trigger date 2026-03-01",
    ]
    assert [finding.location for finding in findings] == [
        "notifications[1]",
        "notifications[2]",
    ]


def test_r1_renders_record_findings_in_the_record_form(
    registry: Registry, r1: Rule
) -> None:
    # The record form: field-less findings at ``notifications[i]`` with
    # the rule-authored label and the cited sources' Basis quotes.
    document = _notified(
        2.5e25, [{"aware_on": "2026-07-20", "notified_on": "2026-08-04"}]
    )
    (finding,) = run_consistency(document, registry)

    text = render_finding(finding, registry)

    assert text.startswith(
        "[INCONSISTENT] notifications[0] - Art. 52 notification record\n"
        "  Reason: the notification of 2026-08-04 follows the trigger of "
        "2026-07-20 by 15 days, beyond the two weeks of Art. 52(1)\n"
    )
    assert "  Basis:\n" in text
    assert "  Article 51(1), point (a)\n" in text
    assert "  Article 51(2)\n" in text
    assert "  Article 52(1)\n" in text


def test_r1_stays_silent_without_the_element_or_its_compute(
    registry: Registry, r1: Rule
) -> None:
    # Absence is completeness' story: no section, element or
    # compute leaves the rule nothing to reason about.
    without_section = Document(values={})
    without_element = Document(values={"annex_xi": {}})
    without_compute = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": None}}}
    )

    assert run_consistency(without_section, registry) == []
    assert run_consistency(without_element, registry) == []
    assert run_consistency(without_compute, registry) == []


def test_r1_stays_silent_when_its_inputs_are_malformed(
    registry: Registry, r1: Rule
) -> None:
    # A quoted compute is text to the typed pass, which refuses the document:
    # no rule runs, and the malformed finding tells the story.
    document = _notified("2.5e25")

    assert run_consistency(document, registry) == []
    kinds = {finding.kind for finding in lint(document, registry)}
    assert "malformed" in kinds
    assert "inconsistent" not in kinds


def test_r1_stays_silent_when_called_without_a_validated_document(
    registry: Registry, r1: Rule
) -> None:
    # The engine never calls a rule with ``validated is None``; the rule keeps
    # its own guard anyway.
    context = RuleContext(values={}, validated=None, registry=registry)

    assert r1.check(context) == []


# R2, ``compute.reporting``: two significant figures and the
# estimation method, on the element's compute and on each notified compute.

# R2's pinned basis, one entry per side: the element entry cites para 120 and
# carries the Form's two rows; the record entry cites para 31 alone. Both
# labels are read verbatim from form.yaml.
COMPUTE_ESTIMATION_CITATION = "guidelines-c2025-7719-120-compute-estimation"
COMPUTE_REPORTING_CITATION = "guidelines-c2025-7719-31-compute-reporting"
COMPUTE_BASIS_FORMS = [
    (
        "computational-resources/"
        "amount-of-computation-used-for-training-two-significant-figures",
        "Amount of computation used for training",
    ),
    (
        "computational-resources/measurement-methodology",
        "Measurement methodology",
    ),
]


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> tuple[Rule, ...]:
    """R2 alone from the catalogue: both entries, no other rule's noise."""
    rules = tuple(rule for rule in consistency.RULES if rule.id == "compute.reporting")
    monkeypatch.setattr(consistency, "RULES", rules)
    return rules


def _element(training_flop: object, method: str | None = None) -> Document:
    """A document whose XI.1.2.d holds the compute, with a method when given."""
    resources: dict[str, object] = {"training_flop": training_flop}
    if method is not None:
        resources["estimation_method"] = method
    return Document(values={"annex_xi": {"computational_resources": resources}})


def _recorded(entries: list[dict[str, object]]) -> Document:
    """A document carrying only its notifications records."""
    return Document(values={}, records={"notifications": entries})


def test_r2_registers_two_entries_sharing_its_id() -> None:
    # The frozen Rule carries one citations tuple, so R2 is two entries
    # sharing one id: the element entry (para 120, the Form rows as basis) and
    # the record entry (para 31, no Form basis); the id sort keeps their
    # findings adjacent, element first.
    element, records = [
        rule for rule in consistency.RULES if rule.id == "compute.reporting"
    ]

    assert element.scope == "element"
    assert element.field == SUBJECT
    assert element.citations == (COMPUTE_ESTIMATION_CITATION,)
    assert element.basis_forms == tuple(COMPUTE_BASIS_FORMS)
    assert records.scope == "document"
    assert records.field is None
    assert records.citations == (COMPUTE_REPORTING_CITATION,)
    assert records.basis_forms == ()


@pytest.mark.parametrize(
    "training_flop",
    [2.3e25, 1e25, 10**25, 23000000000000000000000000.0],
    ids=["2.3e25", "1e25", "int-10-25", "trailing-zeros"],
)
def test_r2_accepts_element_compute_at_two_significant_figures(
    registry: Registry, r2: tuple[Rule, ...], training_flop: int | float
) -> None:
    # The comparison floats both sides, so an int spelling and the double it
    # converts to read alike: ``10**25`` and ``1e25`` both pass. It is a
    # double-precision round trip, never exact-decimal; ``1e25`` is a hair
    # above 10^25 (10000000000000000905969664) yet passes as written.
    document = _element(training_flop, "hardware counters")

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize(
    ("training_flop", "value_text"),
    [(2.35e25, "2.35e+25"), (2.345e25, "2.345e+25")],
    ids=["2.35e25", "2.345e25"],
)
def test_r2_reports_element_compute_beyond_two_significant_figures(
    registry: Registry, r2: tuple[Rule, ...], training_flop: float, value_text: str
) -> None:
    # One finding per violating value: the value as Python writes it, the
    # registry id, para 120 cited and both Form rows as basis.
    document = _element(training_flop, "hardware counters")

    (finding,) = run_consistency(document, registry)

    assert finding.kind == "inconsistent"
    assert finding.location == SUBJECT
    assert finding.message == (
        f"training compute {value_text} carries more than two significant "
        "figures; the Form asks for two (e.g. 2.3e+25)"
    )
    assert finding.field_id == "XI.1.2.d"
    assert finding.citations == [COMPUTE_ESTIMATION_CITATION]
    assert finding.basis_forms == COMPUTE_BASIS_FORMS


def test_r2_accepts_element_compute_with_an_estimation_method(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The method leaf present is all the check asks; its text is the typed
    # pass's business.
    document = _element(2.3e25, "estimated from training time")

    assert run_consistency(document, registry) == []


def test_r2_reports_element_compute_without_an_estimation_method(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # Absent, null and blank (empty or whitespace-only) read alike: the
    # format's absence semantics count the empty string as missing, so
    # the Form's measurement-methodology expectation is unmet.
    absent = _element(2.3e25)
    null = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": 2.3e25,
                    "estimation_method": None,
                }
            }
        }
    )
    blank = _element(2.3e25, "")
    whitespace = _element(2.3e25, "   ")

    for document in (absent, null, blank, whitespace):
        (finding,) = run_consistency(document, registry)

        assert finding.kind == "inconsistent"
        assert finding.location == SUBJECT
        assert finding.message == (
            "training compute is reported without an estimation method"
        )
        assert finding.field_id == "XI.1.2.d"
        assert finding.citations == [COMPUTE_ESTIMATION_CITATION]
        assert finding.basis_forms == COMPUTE_BASIS_FORMS


def test_r2_reports_both_element_violations_in_check_order(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The checks are independent: a value beyond two significant figures
    # without a method yields both findings, the figures one first.
    document = _element(2.345e25)

    findings = run_consistency(document, registry)

    assert [finding.message for finding in findings] == [
        "training compute 2.345e+25 carries more than two significant figures; "
        "the Form asks for two (e.g. 2.3e+25)",
        "training compute is reported without an estimation method",
    ]


@pytest.mark.parametrize(
    "compute_flop",
    [2.3e25, 1e25, 10**25, 23000000000000000000000000.0],
    ids=["2.3e25", "1e25", "int-10-25", "trailing-zeros"],
)
def test_r2_accepts_notified_compute_at_two_significant_figures(
    registry: Registry, r2: tuple[Rule, ...], compute_flop: int | float
) -> None:
    # The same double-precision round trip on the record side, with the method
    # present.
    document = _recorded(
        [{"compute_flop": compute_flop, "estimation_method": "extrapolated"}]
    )

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize(
    ("compute_flop", "value_text"),
    [(2.35e25, "2.35e+25"), (2.345e25, "2.345e+25")],
    ids=["2.35e25", "2.345e25"],
)
def test_r2_reports_notified_compute_beyond_two_significant_figures(
    registry: Registry,
    r2: tuple[Rule, ...],
    compute_flop: float,
    value_text: str,
) -> None:
    # A record finding: ``notifications[0]`` with the record label,
    # field-less, citing para 31 alone.
    document = _recorded(
        [{"compute_flop": compute_flop, "estimation_method": "extrapolated"}]
    )

    (finding,) = run_consistency(document, registry)

    assert finding.kind == "inconsistent"
    assert finding.location == "notifications[0]"
    assert finding.label == "Art. 52 notification record"
    assert finding.field_id is None
    assert finding.message == (
        f"the notified compute {value_text} carries more than two significant "
        "figures (paragraph 31: e.g. 2.3x10^25 FLOP)"
    )
    assert finding.citations == [COMPUTE_REPORTING_CITATION]
    assert finding.basis_forms == []


def test_r2_reports_notified_compute_without_an_estimation_method(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The record side reads the same absence semantics: absent, null and
    # blank methods alike leave the notified compute without its estimation
    # approach.
    methodless: list[dict[str, object]] = [
        {"compute_flop": 2.3e25},
        {"compute_flop": 2.3e25, "estimation_method": None},
        {"compute_flop": 2.3e25, "estimation_method": ""},
        {"compute_flop": 2.3e25, "estimation_method": "   "},
    ]
    for entry in methodless:
        (finding,) = run_consistency(_recorded([entry]), registry)

        assert finding.message == (
            "the notified compute is reported without an estimation method"
        )
        assert finding.location == "notifications[0]"
        assert finding.label == "Art. 52 notification record"
        assert finding.field_id is None
        assert finding.citations == [COMPUTE_REPORTING_CITATION]


def test_r2_skips_a_notification_entry_without_compute(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # No compute value: neither check has anything to read, and the entry's
    # absent fields are the completeness table's story.
    document = _recorded([{}, {"estimation_method": "extrapolated"}])

    assert run_consistency(document, registry) == []


def test_r2_checks_every_record_in_document_order(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # One finding per violating check per entry, in document order.
    document = _recorded(
        [
            {"compute_flop": 2.3e25, "estimation_method": "extrapolated"},
            {"compute_flop": 2.345e25, "estimation_method": "extrapolated"},
            {"compute_flop": 2.3e25},
        ]
    )

    findings = run_consistency(document, registry)

    assert [finding.location for finding in findings] == [
        "notifications[1]",
        "notifications[2]",
    ]
    assert [finding.message for finding in findings] == [
        "the notified compute 2.345e+25 carries more than two significant "
        "figures (paragraph 31: e.g. 2.3x10^25 FLOP)",
        "the notified compute is reported without an estimation method",
    ]


def test_r2_element_findings_precede_its_record_findings(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The two entries share the rule id, so the id sort keeps the element
    # findings before the record's.
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": 2.35e25}}},
        records={
            "notifications": [
                {"compute_flop": 2.345e25, "estimation_method": "extrapolated"}
            ]
        },
    )

    findings = run_consistency(document, registry)

    assert [finding.location for finding in findings] == [
        SUBJECT,
        SUBJECT,
        "notifications[0]",
    ]


def test_r2_stays_silent_without_the_element_or_its_compute(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # Absence is completeness' story: no section, element or compute
    # leaves either check a value to read.
    without_section = Document(values={})
    without_element = Document(values={"annex_xi": {}})
    without_compute = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": None}}}
    )

    assert run_consistency(without_section, registry) == []
    assert run_consistency(without_element, registry) == []
    assert run_consistency(without_compute, registry) == []


def test_r2_stays_silent_when_its_inputs_are_malformed(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # A quoted compute is text to the typed pass, which refuses the document:
    # no rule runs, and the malformed finding tells the story.
    document = _element("2.3e25")

    assert run_consistency(document, registry) == []
    kinds = {finding.kind for finding in lint(document, registry)}
    assert "malformed" in kinds
    assert "inconsistent" not in kinds


def test_r2_stays_silent_when_called_without_a_validated_document(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The engine never calls a rule with ``validated is None``; both entries
    # keep their own guard anyway.
    context = RuleContext(values={}, validated=None, registry=registry)

    assert [rule.check(context) for rule in r2] == [[], []]


def test_r2_stays_silent_on_a_compute_the_double_cannot_hold(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # ``10**309`` is schema-valid (NumberValue carries unbounded ints) but
    # has no double, so the figures check declines: no finding, no traceback,
    # the same skip-what-you-cannot-evaluate silence the rules keep
    # elsewhere.
    huge = 10**309
    element = _element(huge, "hardware counters")
    record = _recorded([{"compute_flop": huge, "estimation_method": "extrapolated"}])
    combined = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": huge,
                    "estimation_method": "hardware counters",
                }
            }
        },
        records={
            "notifications": [
                {"compute_flop": huge, "estimation_method": "extrapolated"}
            ]
        },
    )

    assert run_consistency(element, registry) == []
    assert run_consistency(record, registry) == []
    assert run_consistency(combined, registry) == []


def test_r2_renders_element_findings_in_the_element_form(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The element-side finding renders the element form: registry id and
    # label, the Reason line, then the Basis block (para 120 and the two Form
    # rows).
    document = _element(2.345e25)

    findings = run_consistency(document, registry)
    text = render_finding(findings[0], registry)

    assert text.startswith(
        "[INCONSISTENT] XI.1.2.d - Computational resources used to train the model\n"
        "  Reason: training compute 2.345e+25 carries more than two significant "
        "figures; the Form asks for two (e.g. 2.3e+25)\n"
    )
    assert "  Basis:\n" in text
    assert "  GPAI Guidelines C(2025) 7719, Annex A.2, paragraph 120\n" in text
    assert (
        "  Form: computational-resources/"
        "amount-of-computation-used-for-training-two-significant-figures"
        " - Amount of computation used for training\n"
    ) in text
    assert text.endswith(
        "  Form: computational-resources/measurement-methodology"
        " - Measurement methodology"
    )


def test_r2_renders_record_findings_in_the_record_form(
    registry: Registry, r2: tuple[Rule, ...]
) -> None:
    # The record-side finding renders the record form: its Reason,
    # then para 31's stored text under the Basis header.
    document = _recorded([{"compute_flop": 2.3e25}])

    (finding,) = run_consistency(document, registry)
    text = render_finding(finding, registry)

    assert text.startswith(
        "[INCONSISTENT] notifications[0] - Art. 52 notification record\n"
        "  Reason: the notified compute is reported without an estimation method\n"
    )
    assert (
        "  GPAI Guidelines C(2025) 7719, paragraph 31, compute reporting requirements\n"
    ) in text
    assert '"the amount of compute estimated by the provider' in text


# R3, ``modification.one-third``: para 60's criterion, under which a
# downstream modifier whose training compute exceeds a third of the original
# model's is treated, indicatively, as the provider of the resulting model.
# The comparison is exact integer arithmetic (``mod * 3 > original``), never a
# division, so a 10^400 modification neither overflows nor misrounds; a float
# pair compares with a relative double-noise tolerance instead.

# R3's pinned basis: para 60 alone (para 115 is not machine-extractable).
ONE_THIRD_CITATION = "guidelines-c2025-7719-60-one-third-criterion"


@pytest.fixture
def r3(monkeypatch: pytest.MonkeyPatch) -> Rule:
    """R3 alone from the catalogue: its matrix, no other rule's noise."""
    rule = next(
        rule for rule in consistency.RULES if rule.id == "modification.one-third"
    )
    monkeypatch.setattr(consistency, "RULES", (rule,))
    return rule


def _modified(original: object, modifications: list[dict[str, object]]) -> Document:
    """A document whose XI.1.2.d carries the model's own compute and the records."""
    return Document(
        values={"annex_xi": {"computational_resources": {"training_flop": original}}},
        records={"modifications": modifications},
    )


def test_r3_registers_the_document_rule() -> None:
    # R3 is document-scoped: it compares a records entry against the
    # element's compute, so no registry field names it; para 60 is its whole
    # basis.
    rule = next(
        rule for rule in consistency.RULES if rule.id == "modification.one-third"
    )

    assert rule.scope == "document"
    assert rule.field is None
    assert rule.citations == (ONE_THIRD_CITATION,)
    assert rule.basis_forms == ()


@pytest.mark.parametrize(
    ("original", "modification"),
    [
        (3, 1),
        (9, 3),
        (6.0, 2.0),
        (3.0, 1),
        (3 * 10**400, 10**400),
    ],
    ids=["int", "int-step", "float", "mixed-int-float", "huge-int"],
)
def test_r3_is_quiet_at_exactly_one_third(
    registry: Registry, r3: Rule, original: object, modification: object
) -> None:
    # Para 60 says "greater than a third", so exactly a third is inside and
    # quiet: the integer spellings compare exactly (the 10^400 pair included,
    # where the boundary holds without division or overflow), and a mixed
    # spelling reads as the magnitude it writes (1 against 3.0), with no int
    # converted to a float.
    document = _modified(original, [{"training_flop": modification}])

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize(
    ("original", "modification"),
    [
        (3, 2),
        (9, 4),
        (6.0, 2.000000001),
        (10**400, 10**400 // 3 + 1),
        (2.5e25, 10**400),
    ],
    ids=["int", "int-step", "float", "huge-int", "ten-to-400"],
)
def test_r3_fires_just_above_one_third(
    registry: Registry, r3: Rule, original: object, modification: object
) -> None:
    # The smallest step over the third fires, whatever the magnitude: the
    # integer step, a float margin past the noise tolerance, and values with
    # no double at all.
    document = _modified(original, [{"training_flop": modification}])

    (finding,) = run_consistency(document, registry)

    assert finding.kind == "inconsistent"
    assert finding.location == "modifications[0]"
    assert finding.label == "modification record"
    assert finding.field_id is None


def test_r3_pins_the_over_one_third_message(registry: Registry, r3: Rule) -> None:
    # The message reads both magnitudes as Python writes them, attributes the
    # criterion to the guidelines as indicative, and issues no verdict.
    document = _modified(2.5e25, [{"training_flop": 1e25}])

    (finding,) = run_consistency(document, registry)

    assert finding.message == (
        "the modification's training compute 1e+25 FLOP exceeds one third of "
        "the model's 2.5e+25 FLOP; the guidelines' indicative criterion "
        "(paragraph 60) treats such a modifier as the provider of the "
        "resulting model, and this document does not record the modification "
        "as a provider record"
    )
    assert finding.citations == [ONE_THIRD_CITATION]
    assert finding.basis_forms == []


def test_r3_compares_a_huge_int_modification_without_overflowing(
    registry: Registry, r3: Rule
) -> None:
    # A modification larger than any double is still a magnitude the
    # comparison reads exactly: no OverflowError, no misrounding.
    document = _modified(2.5e25, [{"training_flop": 10**400}])

    (finding,) = run_consistency(document, registry)

    assert finding.message == (
        f"the modification's training compute {10**400!r} FLOP exceeds one "
        f"third of the model's {2.5e25!r} FLOP; the guidelines' indicative "
        "criterion (paragraph 60) treats such a modifier as the provider of "
        "the resulting model, and this document does not record the "
        "modification as a provider record"
    )


def test_r3_tolerates_double_noise_at_the_third(registry: Registry, r3: Rule) -> None:
    # A float pair written as an exact third reads as one: the doubles for
    # 1e25 and 3e25 put three of the former a hair above the latter, inside
    # the relative tolerance.
    nominally_a_third = _modified(3e25, [{"training_flop": 1e25}])
    over_the_third = _modified(2e25, [{"training_flop": 1e25}])

    assert run_consistency(nominally_a_third, registry) == []
    (finding,) = run_consistency(over_the_third, registry)
    assert finding.location == "modifications[0]"


def test_r3_reads_a_float_modification_against_a_huge_original(
    registry: Registry, r3: Rule
) -> None:
    # The float branch never converts an int to a float: a float modification
    # against a 10^400 original compares without OverflowError and sits far
    # below the third, so the entry is quiet.
    document = _modified(10**400, [{"training_flop": 5e307}])

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize("provider_record", [None, False], ids=["absent", "false"])
def test_r3_fires_without_a_provider_record(
    registry: Registry, r3: Rule, provider_record: bool | None
) -> None:
    # The trigger is ``provider_record is not True``: absent and explicit
    # false both mean the document does not record the modification as a
    # provider record.
    entry: dict[str, object] = {"training_flop": 1e25}
    if provider_record is not None:
        entry["provider_record"] = provider_record

    (finding,) = run_consistency(_modified(2.5e25, [entry]), registry)

    assert finding.location == "modifications[0]"


def test_r3_is_quiet_when_the_modification_is_recorded_as_a_provider_record(
    registry: Registry, r3: Rule
) -> None:
    # The document's own recording answers the indicative criterion, and R3
    # steps aside.
    document = _modified(2.5e25, [{"training_flop": 1e25, "provider_record": True}])

    assert run_consistency(document, registry) == []


def test_r3_skips_a_modification_without_its_compute(
    registry: Registry, r3: Rule
) -> None:
    # training_flop stays optional: an entry without one has nothing
    # to compare, and the completeness table owns its absent fields.
    document = _modified(2.5e25, [{}, {"description": "a fine-tune"}])

    assert run_consistency(document, registry) == []


def test_r3_checks_every_modification_in_document_order(
    registry: Registry, r3: Rule
) -> None:
    # One finding per violating entry, in document order.
    document = _modified(
        9.0e24,
        [
            {"training_flop": 1.0e24},
            {"training_flop": 3.0e24},
            {"training_flop": 4.0e24, "provider_record": True},
            {"training_flop": 4.0e24},
        ],
    )

    (finding,) = run_consistency(document, registry)

    assert finding.location == "modifications[3]"


def test_r3_is_silent_without_the_element_or_its_compute(
    registry: Registry, r3: Rule
) -> None:
    # Absence is completeness' story: without the model's own
    # compute there is nothing for para 60's criterion to compare against.
    without_section = Document(
        values={}, records={"modifications": [{"training_flop": 1e25}]}
    )
    without_element = Document(
        values={"annex_xi": {}},
        records={"modifications": [{"training_flop": 1e25}]},
    )
    without_compute = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": None}}},
        records={"modifications": [{"training_flop": 1e25}]},
    )

    assert run_consistency(without_section, registry) == []
    assert run_consistency(without_element, registry) == []
    assert run_consistency(without_compute, registry) == []


def test_r3_is_silent_without_modifications(registry: Registry, r3: Rule) -> None:
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": 2.5e25}}}
    )

    assert run_consistency(document, registry) == []


def test_r3_stays_silent_when_its_inputs_are_malformed(
    registry: Registry, r3: Rule
) -> None:
    # A quoted compute is text to the typed pass, which refuses the document:
    # no rule runs, and the malformed finding tells the story.
    document = _modified("2.5e25", [{"training_flop": 1e25}])

    assert run_consistency(document, registry) == []
    kinds = {finding.kind for finding in lint(document, registry)}
    assert "malformed" in kinds
    assert "inconsistent" not in kinds


def test_r3_stays_silent_when_called_without_a_validated_document(
    registry: Registry, r3: Rule
) -> None:
    # The engine never calls a rule with ``validated is None``; the rule keeps
    # its own guard anyway.
    context = RuleContext(values={}, validated=None, registry=registry)

    assert r3.check(context) == []


def test_r3_renders_the_record_finding(registry: Registry, r3: Rule) -> None:
    # The record form: a field-less headline with the rule-authored
    # label, the Reason line, then para 60's stored text under Basis.
    document = _modified(2.5e25, [{"training_flop": 1e25}])
    (finding,) = run_consistency(document, registry)

    text = render_finding(finding, registry)
    source = registry.sources[ONE_THIRD_CITATION]

    assert text.startswith(
        "[INCONSISTENT] modifications[0] - modification record\n"
        "  Reason: the modification's training compute 1e+25 FLOP exceeds one "
        "third of the model's 2.5e+25 FLOP; the guidelines' indicative "
        "criterion (paragraph 60) treats such a modifier as the provider of "
        "the resulting model, and this document does not record the "
        "modification as a provider record\n"
    )
    assert "  Basis:\n" in text
    assert f"  {source.location}\n" in text
    assert f'  "{source.text}"' in text


# Records completeness: what each records entry must carry for
# R1/R2/R3 to be evaluable. A notification record needs its compute, both
# dates and its estimation method; a modification record needs only its
# description, since an absent provider_record is R3's trigger.

# The notification record's required subfields, in the table's order.
NOTIFICATION_REQUIRED = (
    "compute_flop",
    "aware_on",
    "notified_on",
    "estimation_method",
)

# A notification record answering every required field.
COMPLETE_NOTIFICATION: dict[str, object] = {
    "compute_flop": 2.3e25,
    "estimation_method": "extrapolated from the training report",
    "aware_on": "2026-07-20",
    "notified_on": "2026-07-30",
}

# The two entries' pinned bases: the notifications side cites the Art. 52(1)
# duty and para 31; the modifications side cites the one-third criterion
# whose record it implies.
RECORD_NOTIFICATION_CITATIONS = [
    "reg-2024-1689-art-52-1",
    "guidelines-c2025-7719-31-compute-reporting",
]


@pytest.fixture
def record_completeness(monkeypatch: pytest.MonkeyPatch) -> tuple[Rule, ...]:
    """The records-completeness entries alone: both sides, no other rule's noise."""
    rules = tuple(
        rule for rule in consistency.RULES if rule.id == "record.completeness"
    )
    monkeypatch.setattr(consistency, "RULES", rules)
    return rules


def _records(
    notifications: list[dict[str, object]] | None = None,
    modifications: list[dict[str, object]] | None = None,
) -> Document:
    """A document carrying only the records sections it is given."""
    records: dict[str, object] = {}
    if notifications is not None:
        records["notifications"] = notifications
    if modifications is not None:
        records["modifications"] = modifications
    return Document(values={}, records=records)


def test_record_completeness_registers_two_entries_sharing_its_id() -> None:
    # One id, two entries, both document-scoped with no Form rows; the id
    # sort keeps the notification records' findings first.
    notifications, modifications = [
        rule for rule in consistency.RULES if rule.id == "record.completeness"
    ]

    assert notifications.scope == "document"
    assert notifications.field is None
    assert notifications.citations == tuple(RECORD_NOTIFICATION_CITATIONS)
    assert notifications.basis_forms == ()
    assert modifications.scope == "document"
    assert modifications.field is None
    assert modifications.citations == (ONE_THIRD_CITATION,)
    assert modifications.basis_forms == ()


def test_a_complete_notification_record_is_quiet(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    document = _records(notifications=[COMPLETE_NOTIFICATION])

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize("field", NOTIFICATION_REQUIRED)
def test_a_notification_record_missing_a_field_is_reported(
    registry: Registry, record_completeness: tuple[Rule, ...], field: str
) -> None:
    # A missing finding at the subfield path, field-less (no registry element
    # describes it), carrying the record's label and the entry's basis.
    entry = {
        name: value for name, value in COMPLETE_NOTIFICATION.items() if name != field
    }

    (finding,) = run_consistency(_records(notifications=[entry]), registry)

    assert finding.kind == "missing"
    assert finding.location == f"notifications[0].{field}"
    assert finding.message == f"a notification record requires {field}"
    assert finding.label == "Art. 52 notification record"
    assert finding.field_id is None
    assert finding.citations == RECORD_NOTIFICATION_CITATIONS
    assert finding.basis_forms == []


def test_an_empty_notification_record_reports_every_required_field(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # An empty entry lacks every required subfield: one finding each, in the
    # table's order.
    findings = run_consistency(_records(notifications=[{}]), registry)

    assert [finding.location for finding in findings] == [
        f"notifications[0].{field}" for field in NOTIFICATION_REQUIRED
    ]
    assert [finding.message for finding in findings] == [
        f"a notification record requires {field}" for field in NOTIFICATION_REQUIRED
    ]
    assert {finding.kind for finding in findings} == {"missing"}
    assert {finding.label for finding in findings} == {"Art. 52 notification record"}
    assert {tuple(finding.citations) for finding in findings} == {
        tuple(RECORD_NOTIFICATION_CITATIONS)
    }


@pytest.mark.parametrize(
    "field", NOTIFICATION_REQUIRED, ids=[f"null-{f}" for f in NOTIFICATION_REQUIRED]
)
def test_a_null_notification_field_is_missing_too(
    registry: Registry, record_completeness: tuple[Rule, ...], field: str
) -> None:
    # An explicit null is an absence under the format's semantics,
    # exactly as an absent key is.
    entry = {**COMPLETE_NOTIFICATION, field: None}

    (finding,) = run_consistency(_records(notifications=[entry]), registry)

    assert finding.location == f"notifications[0].{field}"


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
def test_a_blank_notification_text_is_missing_too(
    registry: Registry, record_completeness: tuple[Rule, ...], blank: str
) -> None:
    # The same absence semantics cover the blank string, so a blank
    # estimation method is a field the record lacks.
    entry = {**COMPLETE_NOTIFICATION, "estimation_method": blank}

    (finding,) = run_consistency(_records(notifications=[entry]), registry)

    assert finding.location == "notifications[0].estimation_method"


def test_a_zero_notification_compute_is_present(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # A falsey 0 is a value the document carries, not an absence; only the
    # other required fields are checked.
    entry = {**COMPLETE_NOTIFICATION, "compute_flop": 0}

    assert run_consistency(_records(notifications=[entry]), registry) == []


def test_notification_records_report_in_document_order(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # Entries are walked in document order, their fields in the table's
    # order.
    second = {**COMPLETE_NOTIFICATION, "aware_on": None, "notified_on": None}
    fourth = {**COMPLETE_NOTIFICATION, "compute_flop": None}
    document = _records(
        notifications=[COMPLETE_NOTIFICATION, second, COMPLETE_NOTIFICATION, fourth]
    )

    findings = run_consistency(document, registry)

    assert [finding.location for finding in findings] == [
        "notifications[1].aware_on",
        "notifications[1].notified_on",
        "notifications[3].compute_flop",
    ]


def test_a_modification_record_requires_its_description(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # One finding per entry without a description, at the subfield path, with
    # the record's label and the one-third criterion as basis.
    document = _records(
        modifications=[{}, {"training_flop": 9.0e24}, {"description": "a fine-tune"}]
    )

    findings = run_consistency(document, registry)

    assert [finding.location for finding in findings] == [
        "modifications[0].description",
        "modifications[1].description",
    ]
    assert [finding.message for finding in findings] == [
        "a modification record requires description"
    ] * 2
    assert [finding.label for finding in findings] == ["modification record"] * 2
    assert {tuple(finding.citations) for finding in findings} == {(ONE_THIRD_CITATION,)}


def test_modification_compute_and_provider_record_stay_optional(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # Only the description is required: compute and the provider
    # assertion, true or false, stay optional.
    document = _records(
        modifications=[
            {"description": "a fine-tune"},
            {"description": "a sparse fine-tune", "training_flop": 9.0e24},
            {"description": "a recorded one", "provider_record": True},
            {"description": "an explicit false", "provider_record": False},
        ]
    )

    assert run_consistency(document, registry) == []


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
def test_a_blank_modification_description_is_missing(
    registry: Registry, record_completeness: tuple[Rule, ...], blank: str
) -> None:
    document = _records(modifications=[{"description": blank}])

    (finding,) = run_consistency(document, registry)

    assert finding.location == "modifications[0].description"


def test_both_sections_report_in_table_then_document_order(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # The table walks notifications before modifications, each section's
    # entries in document order.
    document = _records(
        notifications=[
            COMPLETE_NOTIFICATION,
            {**COMPLETE_NOTIFICATION, "aware_on": None},
        ],
        modifications=[{"description": "a fine-tune"}, {}],
    )

    findings = run_consistency(document, registry)

    assert [finding.location for finding in findings] == [
        "notifications[1].aware_on",
        "modifications[1].description",
    ]


def test_record_completeness_is_silent_without_records(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # No records section means no entries to check; the absent sections are
    # the format's business.
    assert run_consistency(Document(values={}), registry) == []


def test_record_completeness_stays_silent_when_the_typed_pass_refused(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # A quoted compute refuses the whole document through the typed pass: the
    # entry runs no check, and the malformed finding tells the story.
    document = _records(
        notifications=[{**COMPLETE_NOTIFICATION, "compute_flop": "2.3e25"}]
    )

    assert run_consistency(document, registry) == []
    findings = lint(document, registry)
    assert "malformed" in {finding.kind for finding in findings}
    assert not any(
        finding.kind == "missing" and finding.location.startswith("notifications[")
        for finding in findings
    )


def test_record_completeness_stays_silent_when_called_without_a_validated_document(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # The engine never calls a rule with ``validated is None``; both entries
    # keep their own guard anyway.
    context = RuleContext(values={}, validated=None, registry=registry)

    assert [rule.check(context) for rule in record_completeness] == [[], []]


def test_record_completeness_renders_a_missing_field(
    registry: Registry, record_completeness: tuple[Rule, ...]
) -> None:
    # The missing finding renders the headline (no Reason line) and
    # the entry's basis under Basis: Art. 52(1) and para 31 as stored.
    document = _records(notifications=[{**COMPLETE_NOTIFICATION, "notified_on": None}])
    (finding,) = run_consistency(document, registry)

    text = render_finding(finding, registry)

    assert text.startswith(
        "[MISSING] notifications[0].notified_on - Art. 52 notification record\n"
        "  Basis:\n"
    )
    assert "  Reason:" not in text
    for source_id in RECORD_NOTIFICATION_CITATIONS:
        source = registry.sources[source_id]
        assert f"  {source.location}\n" in text
        assert f'  "{source.text}"' in text


def test_r3_and_record_completeness_speak_to_the_same_modification(
    registry: Registry,
) -> None:
    # The full catalogue on one entry: the one-third finding names the
    # modification, the missing description is the table's finding, and the
    # id sort keeps the rule's first.
    document = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": 9.0e24,
                    "estimation_method": "extrapolated",
                }
            }
        },
        records={"modifications": [{"training_flop": 4.0e24}]},
    )

    findings = run_consistency(document, registry)

    assert [(finding.kind, finding.location) for finding in findings] == [
        ("inconsistent", "modifications[0]"),
        ("missing", "modifications[0].description"),
    ]


# The verdict-vocabulary sweep: no rendered finding may read as a
# judgement on the model, the provider or the document.

# The banned vocabulary: compliance verdicts and grading words a finding
# could use to judge rather than report. Matched case-folded and as whole
# words, so "passed", "passage" and "failure" stay quiet; the hyphen in
# "non-compliant" is a word boundary, so "compliant" covers it.
VERDICT_WORDS = re.compile(
    r"\b(?:compliant|non-compliant|compliance|pass|fail|score|grade|certified)\b",
    re.IGNORECASE,
)

# One firing document per catalogue entry, in catalogue order, labelled
# ``<rule id> <scope>``. The alignment test below ties the table to RULES, so
# a new entry without a firing document fails there instead of leaving the
# sweep vacuously green.
VERDICT_TRIGGERS: tuple[tuple[str, Document], ...] = (
    ("notification.due element", _notified(2.5e25)),
    ("compute.reporting element", _element(2.345e25)),
    ("compute.reporting document", _recorded([{"compute_flop": 2.345e25}])),
    ("modification.one-third document", _modified(2.5e25, [{"training_flop": 1e25}])),
    ("record.completeness document", _records(notifications=[{}])),
    ("record.completeness document", _records(modifications=[{}])),
)


def test_the_verdict_sweep_covers_every_catalogue_entry_in_order() -> None:
    # The table is the catalogue's own order, entry for entry: six entries
    # today, and every future entry has to bring its firing document.
    assert [label for label, _ in VERDICT_TRIGGERS] == [
        f"{rule.id} {rule.scope}" for rule in consistency.RULES
    ]


def test_the_verdict_pattern_sees_the_vocabulary_and_not_its_substrings() -> None:
    # The sweep is only as good as its pattern: each listed word fires
    # case-folded, while innocent carriers of the same letters stay quiet.
    for word in (
        "compliant",
        "non-compliant",
        "compliance",
        "pass",
        "fail",
        "score",
        "grade",
        "certified",
    ):
        assert VERDICT_WORDS.search(f"the document is {word.upper()}"), word
    for innocent in ("passed", "passage", "failure", "upgraded", "scorers"):
        assert not VERDICT_WORDS.search(innocent), innocent


@pytest.mark.parametrize(
    "index",
    range(len(VERDICT_TRIGGERS)),
    ids=[label for label, _ in VERDICT_TRIGGERS],
)
def test_no_rendered_rule_finding_uses_verdict_vocabulary(
    registry: Registry, monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    # Every catalogue entry alone over a document it fires on, every rendered
    # block swept (headline, Reason line, citations and Basis quotes), because
    # that whole block is what a user reads. The documents validate, so no
    # typed refusal echoes a raw value into a message; the run's closing line
    # is not a finding and carries its mandated negation.
    rule = consistency.RULES[index]
    _, document = VERDICT_TRIGGERS[index]
    monkeypatch.setattr(consistency, "RULES", (rule,))

    findings = run_consistency(document, registry)

    assert findings, rule.id
    for finding in findings:
        text = render_finding(finding, registry)
        assert not VERDICT_WORDS.search(text), text


def test_the_demo_renders_no_finding_to_sweep(
    registry: Registry, example: Document
) -> None:
    # The shipped example is the clean demo: the full catalogue renders
    # nothing on it, so the sweep has nothing to flag and the exit contract
    # stays 0.
    assert lint(example, registry) == []
