"""The Markdown findings report.

``findings_markdown`` renders one ``###`` section per finding: the headline,
the message as prose, the element's citation, the rule's cited sources under
``**Basis:**``, its Form bullets, and the shared footer as the closer.
"""

import re
import sys
from pathlib import Path

import pytest

from gpai_docs import cli
from gpai_docs.lint import FOOTER, Finding, render_finding
from gpai_docs.registry import Registry, load
from gpai_docs.report import findings_markdown

# The element-bearing fixtures read the shipped registry, so the pinned
# renders quote the same stored text a user's run prints.
_MISSING = Finding("missing", "annex_xi.energy_consumption", "XI.1.2.e")

_MALFORMED = Finding(
    "malformed",
    "annex_xi.licence",
    "XI.1.1.f",
    message="expected text: ['apache', 'mit'] is not text",
)

_UNKNOWN = Finding(
    "unknown",
    "annex_xi.training_datasets",
    message="no registry entry for this key",
)

# The consistency engine's element form with its whole basis: para 120 cited
# verbatim, then the two Form rows (R2's own catalogue entry).
_INCONSISTENT = Finding(
    "inconsistent",
    "annex_xi.computational_resources",
    "XI.1.2.d",
    message=(
        "training compute 2.345e+25 carries more than two significant "
        "figures; the Form asks for two (e.g. 2.3e+25)"
    ),
    citations=["guidelines-c2025-7719-120-compute-estimation"],
    basis_forms=[
        (
            "computational-resources/"
            "amount-of-computation-used-for-training-two-significant-figures",
            "Amount of computation used for training",
        ),
        (
            "computational-resources/measurement-methodology",
            "Measurement methodology",
        ),
    ],
)

# The field-less record form: a rule-authored label in the headline, the
# rule's three cited Articles under ``**Basis:**`` and no element citation.
_RECORD = Finding(
    "inconsistent",
    "notifications[0]",
    label="Art. 52 notification record",
    message=(
        "the notification of 2026-08-04 follows the trigger of 2026-07-20 "
        "by 15 days, beyond the two weeks of Art. 52(1)"
    ),
    citations=[
        "reg-2024-1689-art-51-1-a",
        "reg-2024-1689-art-51-2",
        "reg-2024-1689-art-52-1",
    ],
)

# One of every form the report distinguishes, for the sweeps and determinism.
_ALL = [_MISSING, _MALFORMED, _UNKNOWN, _INCONSISTENT, _RECORD]

# The banned vocabulary (the consistency sweep's own): a report may
# report what a document's values show, never judge the document. The
# closer's mandated negation is the one exception, held out by its own pin.
_VERDICT_WORDS = re.compile(
    r"\b(?:compliant|non-compliant|compliance|pass|fail|score|grade|certified)\b",
    re.IGNORECASE,
)

# HTML markup the report must never grow (no HTML, no badges).
_HTML_TAG = re.compile(r"<[a-zA-Z/][^>]*>")


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


def test_a_missing_finding_renders_its_headline_and_element_citation(
    registry: Registry,
) -> None:
    # The headline is the text renderer's own ``id - label`` form; the
    # element's source follows as the blockquote pair the Basis citations use
    # (its registry location, then its verbatim text), and a finding carrying
    # no message gets no message line.
    assert findings_markdown([_MISSING], registry) == (
        "### [MISSING] XI.1.2.e - Energy consumption\n"
        "> Annex XI, Section 1, point 2(e)\n"
        '> "known or estimated energy consumption of the model."\n'
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_a_malformed_finding_renders_its_message_as_prose(
    registry: Registry,
) -> None:
    # The registry's label rides in the headline and the message is the
    # section's prose line, before the element citation.
    assert findings_markdown([_MALFORMED], registry) == (
        "### [MALFORMED] XI.1.1.f - Licence\n"
        "expected text: ['apache', 'mit'] is not text\n"
        "> Annex XI, Section 1, point 1(f)\n"
        '> "the licence."\n'
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_an_unknown_finding_names_itself_with_the_message(
    registry: Registry,
) -> None:
    # A field-less finding with no label names its subject with the typed
    # pass's message (the text renderer's own field-less form) and carries no
    # citation to quote.
    assert findings_markdown([_UNKNOWN], registry) == (
        "### [UNKNOWN] annex_xi.training_datasets - no registry entry for this key\n"
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_an_inconsistent_finding_renders_its_citations_and_form_bases(
    registry: Registry,
) -> None:
    # The full block: headline, message, the element's citation, then the
    # rule's basis (the cited source located and quoted in the rule's order,
    # and the Form rows as bullets after the quotes). The citation bytes are
    # pinned literally, so an edit to the stored registry text fails here
    # rather than silently re-baselining the pin. The stored two typographic
    # apostrophes ride as their own ``\N{RIGHT SINGLE QUOTATION MARK}``
    # fragments, spelled without the ambiguous character ruff flags.
    assert findings_markdown([_INCONSISTENT], registry) == (
        "### [INCONSISTENT] XI.1.2.d - "
        "Computational resources used to train the model\n"
        "training compute 2.345e+25 carries more than two significant "
        "figures; the Form asks for two (e.g. 2.3e+25)\n"
        "> Annex XI, Section 1, point 2(d)\n"
        '> "the computational resources used to train the model (e.g. number '
        "of floating point operations), training time, and other relevant "
        'details related to the training;"\n'
        "\n"
        "**Basis:**\n"
        "> GPAI Guidelines C(2025) 7719, Annex A.2, paragraph 120\n"
        '> "Providers may choose any method to estimate the relevant amount of '
        "training compute, so long as the estimated amount is, in the providers"
        "\N{RIGHT SINGLE QUOTATION MARK}"
        " best judgement, accurate within an overall error margin of 30% of the "
        "reported estimate. This is to account for the difficulties providers may "
        "face in obtaining precise estimates of their model"
        "\N{RIGHT SINGLE QUOTATION MARK}"
        "s cumulative training compute, for example, when estimates are made "
        "before training of the model is completed. Providers are nevertheless "
        "expected to document the assumptions made in making their estimations, "
        'including the method of estimation, and the associated uncertainties."\n'
        "- Form: computational-resources/"
        "amount-of-computation-used-for-training-two-significant-figures"
        " - Amount of computation used for training\n"
        "- Form: computational-resources/measurement-methodology"
        " - Measurement methodology\n"
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_a_record_finding_renders_its_label_headline_and_basis(
    registry: Registry,
) -> None:
    # A record finding is field-less: the rule-authored label rides in the
    # headline (the text renderer's record form), there is no element
    # citation, and the rule's sources quote under ``**Basis:**`` in order.
    # The three cited Articles' bytes are pinned literally.
    assert findings_markdown([_RECORD], registry) == (
        "### [INCONSISTENT] notifications[0] - Art. 52 notification record\n"
        "the notification of 2026-08-04 follows the trigger of 2026-07-20 "
        "by 15 days, beyond the two weeks of Art. 52(1)\n"
        "\n"
        "**Basis:**\n"
        "> Article 51(1), point (a)\n"
        '> "it has high impact capabilities evaluated on the basis of appropriate '
        'technical tools and methodologies, including indicators and benchmarks;"\n'
        "> Article 51(2)\n"
        '> "A general-purpose AI model shall be presumed to have high impact '
        "capabilities pursuant to paragraph 1, point (a), when the cumulative amount "
        "of computation used for its training measured in floating point operations is "
        'greater than 10^25."\n'
        "> Article 52(1)\n"
        '> "Where a general-purpose AI model meets the condition referred to in '
        "Article 51(1), point (a), the relevant provider shall notify the Commission "
        "without delay and in any event within two weeks after that requirement is met "
        "or it becomes known that it will be met. That notification shall include the "
        "information necessary to demonstrate that the relevant requirement has been "
        "met. If the Commission becomes aware of a general-purpose AI model presenting "
        "systemic risks of which it has not been notified, it may decide to designate "
        'it as a model with systemic risk."\n'
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_a_form_only_basis_heads_its_bullets_too(registry: Registry) -> None:
    # A finding whose only basis is a Form row still heads the list with the
    # ``**Basis:**`` line (the bases follow under one header).
    finding = Finding(
        "inconsistent",
        "annex_xi.computational_resources",
        "XI.1.2.d",
        message="training compute is reported without an estimation method",
        basis_forms=[("computational-resources/measurement-methodology", "Method")],
    )

    assert findings_markdown([finding], registry).endswith(
        "**Basis:**\n- Form: computational-resources/measurement-methodology"
        " - Method\n"
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_a_missing_finding_without_a_field_renders_no_citation(
    registry: Registry,
) -> None:
    # The records-completeness form: label in the headline, the message as
    # prose, no element to cite. The Basis header opens the block directly,
    # over the cited Article's pinned bytes.
    finding = Finding(
        "missing",
        "notifications[0].notified_on",
        label="Art. 52 notification record",
        message="a notification record requires notified_on",
        citations=["reg-2024-1689-art-52-1"],
    )

    assert findings_markdown([finding], registry) == (
        "### [MISSING] notifications[0].notified_on - "
        "Art. 52 notification record\n"
        "a notification record requires notified_on\n"
        "\n"
        "**Basis:**\n"
        "> Article 52(1)\n"
        '> "Where a general-purpose AI model meets the condition referred to in '
        "Article 51(1), point (a), the relevant provider shall notify the Commission "
        "without delay and in any event within two weeks after that requirement is met "
        "or it becomes known that it will be met. That notification shall include the "
        "information necessary to demonstrate that the relevant requirement has been "
        "met. If the Commission becomes aware of a general-purpose AI model presenting "
        "systemic risks of which it has not been notified, it may decide to designate "
        'it as a model with systemic risk."\n'
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_a_label_ending_with_the_message_does_not_swallow_it(
    registry: Registry,
) -> None:
    # The prose line is suppressed for exactly one headline form, the
    # field-less unknown key, which embeds the message itself. A label that
    # happens to end with the message's words is still a label: the message
    # renders below it rather than being mistaken for a repeat.
    finding = Finding(
        "malformed",
        "notifications[0]",
        label="a notification record requires notified_on",
        message="a notification record requires notified_on",
    )

    assert findings_markdown([finding], registry) == (
        "### [MALFORMED] notifications[0] - "
        "a notification record requires notified_on\n"
        "a notification record requires notified_on\n"
        "\n"
        f"*1 findings - {FOOTER}*"
    )


def test_the_closer_closes_a_clean_run_alone(registry: Registry) -> None:
    # "no findings" is the text renderer's own count wording and the footer
    # the shared constant; a clean run is the italic closer and nothing else.
    assert findings_markdown([], registry) == f"*no findings - {FOOTER}*"


def test_findings_are_separated_by_a_blank_line(registry: Registry) -> None:
    # Two findings render as two sections parted by one blank line, with the
    # closer last and no run of blank lines anywhere.
    report = findings_markdown([_MISSING, _UNKNOWN], registry)

    assert report == (
        "### [MISSING] XI.1.2.e - Energy consumption\n"
        "> Annex XI, Section 1, point 2(e)\n"
        '> "known or estimated energy consumption of the model."\n'
        "\n"
        "### [UNKNOWN] annex_xi.training_datasets - "
        "no registry entry for this key\n"
        "\n"
        f"*2 findings - {FOOTER}*"
    )
    assert "\n\n\n" not in report


def test_the_report_is_deterministic(registry: Registry) -> None:
    # A pure function of the findings and the registry: two runs, and a
    # second registry load, produce byte-identical reports.
    first = findings_markdown(_ALL, registry)

    assert first == findings_markdown(_ALL, registry)
    assert first == findings_markdown(_ALL, load())


def test_an_unknown_citation_id_raises(registry: Registry) -> None:
    # A citation id the registry does not carry is a data defect, never
    # something to skip (the text renderer's own rule): the raise names the
    # missing source with the finding's kind and location.
    finding = Finding(
        "missing",
        "annex_xi.energy_consumption",
        "XI.1.2.e",
        citations=["reg-2024-1689-ghost"],
    )

    with pytest.raises(KeyError) as excinfo:
        findings_markdown([finding], registry)

    assert "unknown source id 'reg-2024-1689-ghost'" in str(excinfo.value)
    assert "annex_xi.energy_consumption" in str(excinfo.value)


def test_the_report_body_carries_no_verdict_vocabulary(registry: Registry) -> None:
    # The closer is the one mandated exception (it carries the footer's
    # negation "not a compliance verdict"), so the sweep reads every other
    # line of a report that quotes legal text, a Form row and a record label.
    report = findings_markdown(_ALL, registry)
    body, _, closer = report.rpartition("\n\n")

    assert body
    assert not _VERDICT_WORDS.search(body), body
    assert closer == f"*{len(_ALL)} findings - {FOOTER}*"


def test_the_report_emits_no_html(registry: Registry) -> None:
    # No HTML, no badges, no scores; the report is Markdown prose
    # and quotes, with no tag anywhere.
    assert not _HTML_TAG.search(findings_markdown(_ALL, registry))


def test_a_line_break_in_a_key_cannot_inject_markdown_structure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # A document key is author-controlled text, and the field-less unknown-key
    # headline embeds it: a key holding a line break could otherwise split the
    # ``###`` line and inject Markdown structure (a stray ``#`` heading) into
    # the report. Every run of line breaks (newlines and carriage returns
    # alike) collapses to one space, so each headline stays one line.
    document = tmp_path / "injected.yaml"
    document.write_text(
        "schema: 1\n"
        '"annex_xi.bad\\n# injected": "x"\n'
        '"annex_xi.bad\\r\\n# injected": "y"\n'
        "annex_xi: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["gpai-docs", "lint", str(document), "--markdown"])

    code = cli.main()
    out = capsys.readouterr().out

    assert code == 1
    assert "\n# " not in out
    assert "\r" not in out
    assert (
        out.count(
            "### [UNKNOWN] annex_xi.bad # injected - no registry entry for this key\n"
        )
        == 2
    )


@pytest.mark.parametrize("flags", [["--json", "--markdown"], ["--markdown", "--json"]])
def test_lint_refuses_json_and_markdown_together(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
) -> None:
    # The two report forms are one another's negation: refused as
    # bad input in the shared error style, before any read. The path below
    # need not even exist.
    monkeypatch.setattr(sys, "argv", ["gpai-docs", "lint", "absent.yaml", *flags])

    code = cli.main()
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err == (
        "gpai-docs: error: --json and --markdown are mutually exclusive\n"
    )


def test_report_output_is_plain_ascii(registry: Registry) -> None:
    # The text renderer and the Markdown report draw their own punctuation
    # from a plain alphabet: the headline, the annex-point line, the Form
    # line and the closer are ASCII by construction, so a document may
    # quote a transcript verbatim. Quoted provision text is the one
    # exception, and it reprints the source (pinned below); this sample's
    # citation is ASCII.
    text = render_finding(_MISSING, registry)
    markdown = findings_markdown([_MISSING], registry)

    assert text.isascii()
    assert markdown.isascii()


def test_quoted_source_text_reprints_the_source_characters(
    registry: Registry,
) -> None:
    # Para 120's stored text carries the guidelines' own curly apostrophe
    # (U+2019) and it is reprinted exactly: the plain rule governs the
    # renderer's punctuation, never the record's quoted text.
    text = render_finding(_INCONSISTENT, registry)

    assert "’" in text  # noqa: RUF001 - the character is the test data
