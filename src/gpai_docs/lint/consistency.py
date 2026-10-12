"""The consistency pass: relations between the document's own values.

A refused document runs no rule at all - the malformed or unknown finding
already tells that story - and the engine stamps each finding's field id,
citations and basis forms from the rule, so a rule authors only messages,
locations and labels.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from gpai_docs.lint.completeness import _MARKER
from gpai_docs.lint.findings import Finding
from gpai_docs.models import ModelDocument

if TYPE_CHECKING:
    from gpai_docs.documents import Document
    from gpai_docs.models.records import ModificationRecord, NotificationRecord
    from gpai_docs.registry import Registry

__all__ = ["RULES", "Rule", "RuleContext", "run_consistency"]


@dataclass
class RuleContext:
    """What one rule reads: the raw document, its typed form, the registry.

    ``values`` is the raw top-level mapping with the records sections folded
    in; ``validated`` is ``None`` when the typed pass refused the document (an
    extra key fails the same whole-document validation).
    """

    values: dict[str, object]
    validated: ModelDocument | None
    registry: Registry


@dataclass
class Rule:
    """One consistency rule: identity, its basis, and its check.

    ``scope`` is ``element`` (``field`` names the registry ``model_field`` the
    findings cite) or ``document`` (``field`` is ``None``), and ``citations``
    and ``basis_forms`` are copied onto every finding the rule emits.
    """

    id: str
    scope: Literal["element", "document"]
    field: str | None
    citations: tuple[str, ...]
    basis_forms: tuple[tuple[str, str], ...]
    check: Callable[[RuleContext], list[Finding]]


# R1 - the Art. 52(1) notification duty: its basis is Art. 51(1)(a),
# Art. 51(2) and Art. 52(1), and "within two weeks" reads as exactly 14 days,
# the last day still inside the window.
_COMPUTATIONAL_RESOURCES = "annex_xi.computational_resources"

# Art. 51(2)'s 10^25 in both the spellings the comparison needs: an int
# compares exactly against the integer, while a float compares against
# ``1e25``, the nearest double, which sits a hair above the exact integer - so
# the float spelling of the threshold reads as the threshold, not above it.
_FLOP_THRESHOLD = 10**25
_FLOP_THRESHOLD_FLOAT = 1e25

_NOTIFICATION_WINDOW_DAYS = 14
_NOTIFICATION_CITATIONS = (
    "reg-2024-1689-art-51-1-a",
    "reg-2024-1689-art-51-2",
    "reg-2024-1689-art-52-1",
)
_RECORD_LABEL = "Art. 52 notification record"


def _check_notification_due(context: RuleContext) -> list[Finding]:
    """R1: training compute above 10^25 FLOP with its Art. 52(1) duty unmet.

    Silent unless the document carries the element's compute; each late or
    reversed entry is a field-less record finding at ``notifications[i]``, and
    one missing either date is the requiredness table's, not this rule's.
    """
    document = context.validated
    if document is None:
        return []
    annex_xi = document.annex_xi
    resources = None if annex_xi is None else annex_xi.computational_resources
    if resources is None or resources.training_flop is None:
        return []
    compute = resources.training_flop
    threshold = _FLOP_THRESHOLD_FLOAT if isinstance(compute, float) else _FLOP_THRESHOLD
    if compute <= threshold:
        return []
    if not document.notifications:
        return [
            Finding(
                kind="inconsistent",
                location=_COMPUTATIONAL_RESOURCES,
                message=(
                    f"training compute {compute!r} FLOP is greater than 10^25 "
                    "and the document carries no Art. 52(1) notification record"
                ),
            )
        ]
    findings: list[Finding] = []
    for index, record in enumerate(document.notifications):
        if record.aware_on is None or record.notified_on is None:
            continue
        days = (record.notified_on - record.aware_on).days
        if days < 0:
            findings.append(
                Finding(
                    kind="inconsistent",
                    location=f"notifications[{index}]",
                    label=_RECORD_LABEL,
                    message=(
                        f"the notification date {record.notified_on} precedes "
                        f"the trigger date {record.aware_on}"
                    ),
                )
            )
        elif days > _NOTIFICATION_WINDOW_DAYS:
            findings.append(
                Finding(
                    kind="inconsistent",
                    location=f"notifications[{index}]",
                    label=_RECORD_LABEL,
                    message=(
                        f"the notification of {record.notified_on} follows the "
                        f"trigger of {record.aware_on} by {days} days, beyond "
                        "the two weeks of Art. 52(1)"
                    ),
                )
            )
    return findings


NOTIFICATION_DUE = Rule(
    id="notification.due",
    scope="element",
    field=_COMPUTATIONAL_RESOURCES,
    citations=_NOTIFICATION_CITATIONS,
    basis_forms=(),
    check=_check_notification_due,
)

# R2 - the Form's two-significant-figures and estimation-method expectations.
# The frozen Rule carries one citations tuple, so the id
# ``compute.reporting`` is two entries: the element entry cites guidelines
# para 120 plus the Form's two rows as basis forms, the record entry para 31.
# No threshold gates either: both run for every document, wherever the value
# sits.
#
# The figures check is a round trip on the value as written, so its caveat is
# double precision: ``1e25`` passes though its binary value carries
# more digits than two.
_COMPUTE_ESTIMATION_CITATION = "guidelines-c2025-7719-120-compute-estimation"
_COMPUTE_REPORTING_CITATION = "guidelines-c2025-7719-31-compute-reporting"

_COMPUTE_BASIS_FORMS = (
    (
        "computational-resources/"
        "amount-of-computation-used-for-training-two-significant-figures",
        "Amount of computation used for training",
    ),
    (
        "computational-resources/measurement-methodology",
        "Measurement methodology",
    ),
)


def _absent_text(value: object) -> bool:
    """Whether a text slot reads as absent.

    ``null``, the empty string and whitespace alike count, so a blank method
    or description is an absence; a falsey ``0`` in a number slot is not text
    and stays a value the document carries.
    """
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _beyond_two_significant_figures(value: int | float) -> bool:
    """True when the two-significant-figure round trip does not close.

    Both sides are doubles, so the exact int ``10**25`` and its spelling
    ``1e25`` read alike. An int no double holds (``10**309``) is declined
    (``False``): the rules skip what they cannot evaluate.
    """
    try:
        return float(format(value, ".2g")) != float(value)
    except OverflowError:
        return False


def _check_compute_reporting_element(context: RuleContext) -> list[Finding]:
    """R2, element side: XI.1.2.d's compute, its figures and its method.

    Silent unless the document carries the compute; the two checks are
    independent, figures first, each a field-bearing finding
    at the element's own path.
    """
    document = context.validated
    if document is None:
        return []
    annex_xi = document.annex_xi
    resources = None if annex_xi is None else annex_xi.computational_resources
    if resources is None or resources.training_flop is None:
        return []
    compute = resources.training_flop
    findings: list[Finding] = []
    if _beyond_two_significant_figures(compute):
        findings.append(
            Finding(
                kind="inconsistent",
                location=_COMPUTATIONAL_RESOURCES,
                message=(
                    f"training compute {compute!r} carries more than two "
                    "significant figures; the Form asks for two (e.g. 2.3e+25)"
                ),
            )
        )
    if _absent_text(resources.estimation_method):
        findings.append(
            Finding(
                kind="inconsistent",
                location=_COMPUTATIONAL_RESOURCES,
                message="training compute is reported without an estimation method",
            )
        )
    return findings


def _check_compute_reporting_records(context: RuleContext) -> list[Finding]:
    """R2, record side: each notification's compute, figures and method.

    An entry without a compute is passed over - that absence is the
    requiredness table's - and the rest get field-less record findings in
    document order.
    """
    document = context.validated
    if document is None:
        return []
    findings: list[Finding] = []
    for index, record in enumerate(document.notifications):
        if record.compute_flop is None:
            continue
        location = f"notifications[{index}]"
        if _beyond_two_significant_figures(record.compute_flop):
            findings.append(
                Finding(
                    kind="inconsistent",
                    location=location,
                    label=_RECORD_LABEL,
                    message=(
                        f"the notified compute {record.compute_flop!r} carries "
                        "more than two significant figures "
                        "(paragraph 31: e.g. 2.3x10^25 FLOP)"
                    ),
                )
            )
        if _absent_text(record.estimation_method):
            findings.append(
                Finding(
                    kind="inconsistent",
                    location=location,
                    label=_RECORD_LABEL,
                    message=(
                        "the notified compute is reported without an estimation method"
                    ),
                )
            )
    return findings


COMPUTE_REPORTING_ELEMENT = Rule(
    id="compute.reporting",
    scope="element",
    field=_COMPUTATIONAL_RESOURCES,
    citations=(_COMPUTE_ESTIMATION_CITATION,),
    basis_forms=_COMPUTE_BASIS_FORMS,
    check=_check_compute_reporting_element,
)

COMPUTE_REPORTING_RECORDS = Rule(
    id="compute.reporting",
    scope="document",
    field=None,
    citations=(_COMPUTE_REPORTING_CITATION,),
    basis_forms=(),
    check=_check_compute_reporting_records,
)

# R3 - the guidelines' one-third criterion. Para 60 holds it out as
# indicative: a downstream modifier whose training compute exceeds a third of
# the original model's is treated as the provider of the resulting model, so
# a document carrying such a modification without recording it as a provider
# record is inconsistent with the criterion. Document-scoped, it
# reads the modifications records against the element's compute; para 60 is
# its whole basis.
_ONE_THIRD_CITATION = "guidelines-c2025-7719-60-one-third-criterion"
_MODIFICATION_LABEL = "modification record"

# The relative slack the float branch allows: 1e-12, the double-noise scale a
# decimal third can round to (1e25 * 3 against 3e25 is about 7e-17 relative,
# far inside this).
_DOUBLE_TOLERANCE = Fraction(1, 10**12)


def _exceeds_one_third(modification: int | float, original: int | float) -> bool:
    """Whether the modification is strictly over one third of the original.

    All-int pairs compare exactly (``modification * 3 > original``), never by
    division, which would convert a huge int to a float and round at double
    precision; a pair with a double on either side reads the same inequality
    as exact rationals under the relative tolerance above.
    """
    if isinstance(modification, int) and isinstance(original, int):
        return modification * 3 > original
    slack = 1 + _DOUBLE_TOLERANCE
    return Fraction(modification) * 3 > Fraction(original) * slack


def _check_modification_one_third(context: RuleContext) -> list[Finding]:
    """R3: a modification above one third of the model's training compute.

    Silent unless the element's compute is present; an entry recorded as a
    provider record or without a compute (the requiredness table's) is quiet,
    and every entry over the third is a record finding at ``modifications[i]``.
    """
    document = context.validated
    if document is None:
        return []
    annex_xi = document.annex_xi
    resources = None if annex_xi is None else annex_xi.computational_resources
    if resources is None or resources.training_flop is None:
        return []
    original = resources.training_flop
    findings: list[Finding] = []
    for index, record in enumerate(document.modifications):
        modification = record.training_flop
        if modification is None or record.provider_record is True:
            continue
        if _exceeds_one_third(modification, original):
            findings.append(
                Finding(
                    kind="inconsistent",
                    location=f"modifications[{index}]",
                    label=_MODIFICATION_LABEL,
                    message=(
                        f"the modification's training compute {modification!r} "
                        f"FLOP exceeds one third of the model's {original!r} "
                        "FLOP; the guidelines' indicative criterion (paragraph "
                        "60) treats such a modifier as the provider of the "
                        "resulting model, and this document does not record "
                        "the modification as a provider record"
                    ),
                )
            )
    return findings


MODIFICATION_ONE_THIRD = Rule(
    id="modification.one-third",
    scope="document",
    field=None,
    citations=(_ONE_THIRD_CITATION,),
    basis_forms=(),
    check=_check_modification_one_third,
)


# The records-completeness table, beside the rules it enables: a
# notification record answers for the fields R1 and R2 read (hence its
# Art. 52(1) and para 31 citations) and a modification record for its
# description. A modification's ``training_flop`` and ``provider_record``
# stay optional: an absent ``provider_record`` is R3's trigger, and requiring
# it here would erase the rule's own reading.
#
# Two entries share the id ``record.completeness`` (the R2 precedent: one
# citations tuple per entry), each in document then table order; the id sort
# keeps them adjacent, the notifications' first.
@dataclass(frozen=True)
class _RecordRequiredness:
    """One records section's required subfields, in the order they report."""

    section: str
    noun: str
    label: str
    required: tuple[str, ...]
    entries: Callable[
        [ModelDocument], list[NotificationRecord] | list[ModificationRecord]
    ]


_NOTIFICATION_REQUIREDNESS = _RecordRequiredness(
    section="notifications",
    noun="notification",
    label=_RECORD_LABEL,
    required=("compute_flop", "aware_on", "notified_on", "estimation_method"),
    entries=lambda document: document.notifications,
)

_MODIFICATION_REQUIREDNESS = _RecordRequiredness(
    section="modifications",
    noun="modification",
    label=_MODIFICATION_LABEL,
    required=("description",),
    entries=lambda document: document.modifications,
)


def _record_findings(context: RuleContext, form: _RecordRequiredness) -> list[Finding]:
    """One section's missing findings, in document then table order."""
    document = context.validated
    if document is None:
        return []
    findings: list[Finding] = []
    for index, entry in enumerate(form.entries(document)):
        for name in form.required:
            value: object = getattr(entry, name)
            if _absent_text(value):
                findings.append(
                    Finding(
                        kind="missing",
                        location=f"{form.section}[{index}].{name}",
                        label=form.label,
                        message=f"a {form.noun} record requires {name}",
                    )
                )
    return findings


def _check_notification_record_completeness(context: RuleContext) -> list[Finding]:
    """The notifications side: one missing finding per absent subfield."""
    return _record_findings(context, _NOTIFICATION_REQUIREDNESS)


def _check_modification_record_completeness(context: RuleContext) -> list[Finding]:
    """The modifications side: one missing finding per absent description."""
    return _record_findings(context, _MODIFICATION_REQUIREDNESS)


RECORD_COMPLETENESS_NOTIFICATIONS = Rule(
    id="record.completeness",
    scope="document",
    field=None,
    citations=(
        "reg-2024-1689-art-52-1",
        "guidelines-c2025-7719-31-compute-reporting",
    ),
    basis_forms=(),
    check=_check_notification_record_completeness,
)

RECORD_COMPLETENESS_MODIFICATIONS = Rule(
    id="record.completeness",
    scope="document",
    field=None,
    citations=(_ONE_THIRD_CITATION,),
    basis_forms=(),
    check=_check_modification_record_completeness,
)

RULES: tuple[Rule, ...] = (
    NOTIFICATION_DUE,
    COMPUTE_REPORTING_ELEMENT,
    COMPUTE_REPORTING_RECORDS,
    MODIFICATION_ONE_THIRD,
    RECORD_COMPLETENESS_NOTIFICATIONS,
    RECORD_COMPLETENESS_MODIFICATIONS,
)


def run_consistency(document: Document, registry: Registry) -> list[Finding]:
    """Run every rule, sorted by rule id then each rule's own order."""
    context = _context(document, registry)
    if context.validated is None:
        return []
    tagged: list[tuple[str, Finding]] = []
    for rule in RULES:
        emitted = rule.check(context)
        if not emitted:
            continue
        field_id = _field_id(rule, registry)
        for finding in emitted:
            # A finding authoring its own label stays field-less (the record
            # form); every other takes the scope's field id.
            if finding.label is None:
                finding.field_id = field_id
            finding.citations = list(rule.citations)
            finding.basis_forms = list(rule.basis_forms)
            tagged.append((rule.id, finding))
    tagged.sort(key=lambda item: item[0])
    return [finding for _, finding in tagged]


def _context(document: Document, registry: Registry) -> RuleContext:
    """The raw values (records included) and their typed reading, if any.

    The typed pass discards its validated document on error, so the engine
    re-reads the same payload through the same model.
    """
    values = {**document.values, **document.records}
    return RuleContext(values=values, validated=_validated(values), registry=registry)


def _validated(values: dict[str, object]) -> ModelDocument | None:
    """The document through the v0.1 models, or ``None`` when they refuse it."""
    try:
        return ModelDocument.model_validate({**_MARKER, **values})
    except ValidationError:
        return None


def _field_id(rule: Rule, registry: Registry) -> str | None:
    """The registry id ``rule.field`` names; document scope has none.

    A rule drifting from the registry's paths is a data defect, named with
    the rule and the path rather than rendered as a field-less finding.
    """
    if rule.scope == "document":
        return None
    for field in registry.fields:
        if field.model_field == rule.field:
            return field.id
    raise KeyError(
        f"element-scoped rule {rule.id!r} names unknown field {rule.field!r}"
    )
