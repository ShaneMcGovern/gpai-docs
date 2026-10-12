"""Offline integrity and online drift verification.

The ``tests/fixtures/registry_mini`` registry carries an abridgement of the
pinned provision, a placeholder artifact hash and a Form pin over the canned
body below; every fetch goes through ``FakeFetcher``, never the network.
"""

import dataclasses
import hashlib
from pathlib import Path

import pytest

from gpai_docs.registry import (
    FindingKind,
    Registry,
    VerifyFinding,
    VerifyReport,
    exit_code,
    load,
    verify,
)
from gpai_docs.registry.extract import sha256_of
from gpai_docs.registry.fetch import FetchResult
from gpai_docs.registry.models import Source

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "registry_mini"
ANNEX_EXCERPT = FIXTURES / "eurlex_annex_excerpt.html"

REGULATION_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727"
)
# The first resolver candidate: the undated EUR-Lex legal-content CELEX URL.
RESOLVER_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689"
# The second resolver candidate: the undated Cellar CELEX resource URI.
CELLAR_RESOLVER_URL = "https://publications.europa.eu/resource/celex/02024R1689"
# The third resolver candidate: the enacted act's own Cellar RDF (CELEX sector
# 3), which names every consolidation layer of the act.
BASE_ACT_URL = "https://publications.europa.eu/resource/celex/32024R1689"
# Where the resolver lands for the pinned and for a newer consolidation.
LATEST_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727"
)
NEWER_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20270101"
)
# A dated Cellar CELEX URL, as the second candidate would land after a
# redirect (the scheme is http because Cellar redirects to http).
CELLAR_PIN_URL = "http://publications.europa.eu/resource/celex/02024R1689-20260727"
CELLAR_NEWER_URL = "http://publications.europa.eu/resource/celex/02024R1689-20270101"
ARTIFACT_URL = "https://example.invalid/guidelines.pdf"
# The Form DOCX pin from the fixture's form.yaml, and the bytes the fixture
# hash covers (see registry_mini/form.yaml).
FORM_URL = "https://ec.europa.eu/newsroom/dae/redirection/document/118118"
FORM_BODY = b"the form docx bytes"

# Annex XI point 1(a), pinned independently in tests/test_extract.py.
XI_1_1_A = (
    "the tasks that the model is intended to perform and the type and nature of "
    "AI systems in which it can be integrated;"
)
TAMPERED = "an abridged rewrite"


class FakeFetcher:
    """Canned responses by URL; records what was asked for."""

    def __init__(self, responses: dict[str, FetchResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def fetch(self, url: str, timeout: float) -> FetchResult:
        self.calls.append((url, timeout))
        response = self.responses.get(url)
        if response is None:
            raise AssertionError(f"unexpected fetch: {url}")
        if isinstance(response, Exception):
            raise response
        return response


def _mini() -> Registry:
    return load(MINI)


def _source(source_id: str, **overrides: object) -> Source:
    """A fixture source with fields overridden (through the model)."""
    source = load(MINI).sources[source_id]
    data: dict[str, object] = dict(source.model_dump())
    data.update(overrides)
    return Source.model_validate(data)


def _registry_with(sources: list[Source]) -> Registry:
    """The fixture registry with this catalogue, and only resolving fields."""
    registry = _mini()
    known = {source.id for source in sources}
    fields = [
        field
        for field in registry.fields
        if field.source in known and all(ref in known for ref in field.context)
    ]
    return dataclasses.replace(
        registry,
        fields=fields,
        by_id={field.id: field for field in fields},
        sources={source.id: source for source in sources},
    )


def _extract_registry(**overrides: object) -> Registry:
    return _registry_with([_source("xi-1-1-a", **overrides)])


def _artifact_registry(**overrides: object) -> Registry:
    return _registry_with([_source("guidelines-energy-estimate", **overrides)])


def _response(
    body: bytes = b"", url: str = REGULATION_URL, status: int = 200
) -> FetchResult:
    return FetchResult(body=body, final_url=url, status=status)


def _online(**overrides: FetchResult | Exception) -> dict[str, FetchResult | Exception]:
    """A clean online pass: the document, the Form, and the resolver on the pin."""
    responses: dict[str, FetchResult | Exception] = {
        REGULATION_URL: _response(ANNEX_EXCERPT.read_bytes()),
        FORM_URL: _response(FORM_BODY, url=FORM_URL),
        RESOLVER_URL: _response(url=LATEST_URL),
    }
    responses.update(overrides)
    return responses


def _verified_extract_registry(**overrides: object) -> Registry:
    """The extract source as the excerpt re-extracts it: online-clean."""
    return _extract_registry(text=XI_1_1_A, sha256=sha256_of(XI_1_1_A), **overrides)


def _kinds(report: VerifyReport) -> list[FindingKind]:
    return [finding.kind for finding in report.findings]


# Offline integrity.


def test_a_clean_registry_has_no_findings() -> None:
    report = verify(_mini())

    assert report.ok
    assert report.findings == []


def test_offline_verification_never_fetches() -> None:
    fetcher = FakeFetcher({})

    report = verify(_mini(), fetcher=fetcher)

    assert report.ok
    assert fetcher.calls == []


def test_a_tampered_stored_text_is_an_integrity_finding() -> None:
    report = verify(_extract_registry(text=TAMPERED))

    (finding,) = report.findings
    assert finding.kind is FindingKind.INTEGRITY
    assert finding.target == "xi-1-1-a"
    assert "hash" in finding.message


def test_an_unknown_source_reference_is_an_integrity_finding() -> None:
    registry = _mini()
    field = registry.fields[0].model_copy(update={"source": "no-such-source"})
    registry = dataclasses.replace(registry, fields=[field], by_id={field.id: field})

    (finding,) = verify(registry).findings

    assert finding.kind is FindingKind.INTEGRITY
    assert finding.target == field.id
    assert "no-such-source" in finding.message


def test_an_unknown_context_reference_is_an_integrity_finding() -> None:
    registry = _mini()
    field = registry.fields[0].model_copy(update={"context": ["xi-chapeau"]})
    registry = dataclasses.replace(registry, fields=[field], by_id={field.id: field})

    (finding,) = verify(registry).findings

    assert finding.kind is FindingKind.INTEGRITY
    assert finding.target == field.id
    assert "xi-chapeau" in finding.message


def test_online_verification_also_runs_the_integrity_checks() -> None:
    registry = _extract_registry(text=TAMPERED)
    fetcher = FakeFetcher(
        _online(**{REGULATION_URL: _response(ANNEX_EXCERPT.read_bytes())})
    )

    report = verify(registry, online=True, fetcher=fetcher)

    assert _kinds(report) == [FindingKind.INTEGRITY, FindingKind.TEXT_CHANGED]


# Online extract-mode sources.


def test_a_changed_provision_is_a_text_change() -> None:
    fetcher = FakeFetcher(_online())

    report = verify(_extract_registry(), online=True, fetcher=fetcher, timeout=5.0)

    (finding,) = report.findings
    assert finding.kind is FindingKind.TEXT_CHANGED
    assert finding.target == "xi-1-1-a"
    assert fetcher.calls == [
        (REGULATION_URL, 5.0),
        (FORM_URL, 5.0),
        (RESOLVER_URL, 5.0),
    ]


def test_an_unchanged_provision_has_no_finding() -> None:
    fetcher = FakeFetcher(_online())

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    assert report.ok


def test_an_unreachable_source_is_could_not_verify() -> None:
    fetcher = FakeFetcher(_online(**{REGULATION_URL: OSError("connection refused")}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "xi-1-1-a"
    assert "connection refused" in finding.message


def test_a_non_200_response_is_could_not_verify_not_a_change() -> None:
    # What EUR-Lex sometimes serves: a WAF challenge as HTTP 202 with
    # an empty body.
    fetcher = FakeFetcher(_online(**{REGULATION_URL: _response(b"", status=202)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert "202" in finding.message


def test_a_waf_challenge_page_is_could_not_verify_not_a_change() -> None:
    challenge = b'<html><script src="/aws-waf-token.js"></script></html>'
    fetcher = FakeFetcher(_online(**{REGULATION_URL: _response(challenge)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY


def test_a_200_response_that_is_not_the_document_is_an_extraction_failure() -> None:
    # A consent or maintenance page must never become a junk hash or a false
    # text change.
    other = b"<html><body><p>A different page entirely.</p></body></html>"
    fetcher = FakeFetcher(_online(**{REGULATION_URL: _response(other)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.EXTRACTION_FAILED
    assert finding.target == "xi-1-1-a"


def test_a_body_that_is_not_utf8_text_is_an_extraction_failure() -> None:
    body = b"\xff\xfe\x00\x01 not html"
    fetcher = FakeFetcher(_online(**{REGULATION_URL: _response(body)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    assert _kinds(report) == [FindingKind.EXTRACTION_FAILED]


def test_an_off_host_redirect_is_could_not_verify() -> None:
    # A captive portal or an expired domain is not drift.
    fetcher = FakeFetcher(
        _online(
            **{
                REGULATION_URL: _response(
                    ANNEX_EXCERPT.read_bytes(), url="https://captive.invalid/portal"
                )
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert "captive.invalid" in finding.message


def test_a_same_host_redirect_is_followed() -> None:
    elsewhere = REGULATION_URL.replace("TXT/?", "TXT/HTML/?")
    fetcher = FakeFetcher(
        _online(
            **{REGULATION_URL: _response(ANNEX_EXCERPT.read_bytes(), url=elsewhere)}
        )
    )

    report = verify(_extract_registry(), online=True, fetcher=fetcher)

    assert _kinds(report) == [FindingKind.TEXT_CHANGED]


def test_a_fetch_url_is_preferred_for_the_source_refetch() -> None:
    # The source re-fetch prefers ``fetch_url`` over the canonical ``url``;
    # the watch derives its candidates from the ``celex`` field instead (see
    # the watch tests below).
    cellar_url = "https://publications.europa.eu/resource/celex/02024R1689-20260727"
    registry = _extract_registry(fetch_url=cellar_url)
    fetcher = FakeFetcher(
        _online(**{cellar_url: _response(ANNEX_EXCERPT.read_bytes(), url=cellar_url)})
    )

    report = verify(registry, online=True, fetcher=fetcher, timeout=5.0)

    assert _kinds(report) == [FindingKind.TEXT_CHANGED]
    assert fetcher.calls == [
        (cellar_url, 5.0),
        (FORM_URL, 5.0),
        (RESOLVER_URL, 5.0),
    ]


def test_the_watch_derives_from_the_celex_not_the_fetch_url() -> None:
    # The registry's ``fetch_url`` is a CELEX-less Cellar item URL, so the
    # watch derives from the source's own ``celex`` field instead.
    cellar_url = (
        "https://publications.europa.eu/resource/cellar/"
        "b1730fb2-8f1c-11f1-9262-01aa75ed71a1.0001.03/DOC_1"
    )
    registry = _verified_extract_registry(fetch_url=cellar_url)
    fetcher = FakeFetcher(
        _online(
            **{
                cellar_url: _response(ANNEX_EXCERPT.read_bytes(), url=cellar_url),
                RESOLVER_URL: _response(url=NEWER_URL),
            }
        )
    )

    report = verify(registry, online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert "2027-01-01" in finding.message
    assert fetcher.calls == [
        (cellar_url, 30.0),
        (FORM_URL, 30.0),
        (RESOLVER_URL, 30.0),
    ]


def test_an_extract_source_without_a_locator_is_could_not_verify() -> None:
    source = _source("xi-1-1-a").model_copy(update={"extraction": None})
    fetcher = FakeFetcher(_online())

    report = verify(_registry_with([source]), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert fetcher.calls == [(FORM_URL, 30.0), (RESOLVER_URL, 30.0)]


# Online artifact-mode sources.


def test_changed_artifact_bytes_are_an_artifact_change() -> None:
    fetcher = FakeFetcher(
        {
            ARTIFACT_URL: _response(b"the guidelines pdf bytes", url=ARTIFACT_URL),
            FORM_URL: _response(FORM_BODY, url=FORM_URL),
        }
    )

    report = verify(_artifact_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.ARTIFACT_CHANGED
    assert finding.target == "guidelines-energy-estimate"
    assert fetcher.calls == [(ARTIFACT_URL, 30.0), (FORM_URL, 30.0)]


def test_matching_artifact_bytes_are_clean() -> None:
    body = b"the guidelines pdf bytes"
    registry = _artifact_registry(artifact_sha256=hashlib.sha256(body).hexdigest())
    fetcher = FakeFetcher(
        {
            ARTIFACT_URL: _response(body, url=ARTIFACT_URL),
            FORM_URL: _response(FORM_BODY, url=FORM_URL),
        }
    )

    report = verify(registry, online=True, fetcher=fetcher)

    assert report.ok


def test_an_unreachable_artifact_is_could_not_verify() -> None:
    fetcher = FakeFetcher(
        {
            ARTIFACT_URL: OSError("no route to host"),
            FORM_URL: _response(FORM_BODY, url=FORM_URL),
        }
    )

    report = verify(_artifact_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "guidelines-energy-estimate"


def test_an_artifact_source_without_an_artifact_url_is_could_not_verify() -> None:
    source = _source("guidelines-energy-estimate").model_copy(
        update={"artifact_url": None}
    )

    fetcher = FakeFetcher(_online())

    report = verify(_registry_with([source]), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "guidelines-energy-estimate"


# The consolidation watch.


def test_a_newer_consolidation_is_a_new_consolidation_finding() -> None:
    fetcher = FakeFetcher(_online(**{RESOLVER_URL: _response(url=NEWER_URL)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert finding.target == "02024R1689"
    assert "2027-01-01" in finding.message
    assert "02024R1689-20260727" in finding.message


def test_the_pinned_consolidation_is_not_a_finding() -> None:
    # The resolver lands on the pin itself; there is nothing newer.
    report = verify(
        _verified_extract_registry(), online=True, fetcher=FakeFetcher(_online())
    )

    assert report.ok


def test_the_watch_reads_the_date_from_the_served_page_too() -> None:
    # A resolver that stops redirecting and serves a page instead: the dated
    # CELEX in the body is the fallback.
    page = b'<a href="/legal-content/EN/TXT/?uri=CELEX:02024R1689-20270401">x</a>'
    fetcher = FakeFetcher(_online(**{RESOLVER_URL: _response(page, url=RESOLVER_URL)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert "2027-04-01" in finding.message


def test_a_resolver_page_naming_an_impossible_date_is_could_not_verify() -> None:
    # "02024R1689-20269999" matches the dated-CELEX shape but is no calendar
    # date, so the watch reads no date at all: could-not-verify, never a
    # ValueError out of verify (nothing raises for a remote
    # failure).
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(b"CELEX:02024R1689-20269999", url=RESOLVER_URL),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(b"", status=404),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "02024R1689"
    assert "named no dated consolidation" in finding.message


def test_a_resolver_landing_on_an_impossible_date_is_could_not_verify() -> None:
    bad_url = REGULATION_URL.replace("20260727", "20269999")
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(url=bad_url),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(b"", status=404),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "02024R1689"


def test_an_unreachable_resolver_is_could_not_verify() -> None:
    responses: dict[str, FetchResult | Exception] = {
        RESOLVER_URL: OSError("connection refused"),
        # The watch still tries the next candidates.
        CELLAR_RESOLVER_URL: _response(b"", status=404),
        BASE_ACT_URL: _response(b"", status=404),
    }
    fetcher = FakeFetcher(_online(**responses))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "02024R1689"
    assert "connection refused" in finding.message
    assert "404" in finding.message


def test_a_resolver_response_without_a_date_is_could_not_verify() -> None:
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(
                    b"no consolidation links here", url=RESOLVER_URL
                ),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(b"", status=404),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "02024R1689"


def test_all_candidates_failing_is_could_not_verify() -> None:
    # A run where every candidate fails (challenged, unpublished, unreachable)
    # is could-not-verify, and every attempt names its reason.
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(b"", status=202),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(b"", status=404),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "02024R1689"
    assert "202" in finding.message
    assert "404" in finding.message
    assert fetcher.calls == [
        (REGULATION_URL, 30.0),
        (FORM_URL, 30.0),
        (RESOLVER_URL, 30.0),
        (CELLAR_RESOLVER_URL, 30.0),
        (BASE_ACT_URL, 30.0),
    ]


def test_a_dateless_candidate_falls_through_to_the_next() -> None:
    # A 200 that names no dated CELEX does not resolve the watch; the second
    # candidate gets its turn.
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(
                    b"no consolidation links here", url=RESOLVER_URL
                ),
                CELLAR_RESOLVER_URL: _response(b"", url=CELLAR_NEWER_URL),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert "2027-01-01" in finding.message


def test_the_second_candidate_can_resolve_the_pin_without_a_finding() -> None:
    responses: dict[str, FetchResult | Exception] = {
        RESOLVER_URL: OSError("connection refused"),
        CELLAR_RESOLVER_URL: _response(b"", url=CELLAR_PIN_URL),
    }
    fetcher = FakeFetcher(_online(**responses))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    assert report.ok


def test_the_base_act_rdf_resolves_the_pin_without_a_finding() -> None:
    # What the endpoint served when this fixture was captured: the candidate is
    # challenged,
    # the undated Cellar resource is not published, and the act's own RDF
    # (which answers without an Accept header) names every consolidation layer.
    layers = (
        b'<rdf:Description rdf:about=".../celex/02024R1689-20240712_0000010">'
        b'<rdf:Description rdf:about=".../celex/02024R1689-20260727_0000010">'
    )
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(b"", status=202),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(layers, url=BASE_ACT_URL),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    assert report.ok


def test_the_base_act_rdf_naming_a_newer_consolidation_is_a_finding() -> None:
    layers = (
        b'<rdf:Description rdf:about=".../celex/02024R1689-20260727_0000010">'
        b'<rdf:Description rdf:about=".../celex/02024R1689-20260901_0000010">'
    )
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(b"", status=202),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(layers, url=BASE_ACT_URL),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert finding.target == "02024R1689"
    assert "2026-09-01" in finding.message


def test_the_newest_dated_celex_in_a_body_wins() -> None:
    # A body naming several dated consolidations resolves to the newest, not
    # the first: the act's RDF lists every layer, oldest first.
    page = (
        b'<a href="/legal-content/EN/TXT/?uri=CELEX:02024R1689-20270101">x</a>'
        b'<a href="/legal-content/EN/TXT/?uri=CELEX:02024R1689-20270501">y</a>'
    )
    fetcher = FakeFetcher(_online(**{RESOLVER_URL: _response(page, url=RESOLVER_URL)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert "2027-05-01" in finding.message


def test_an_impossible_date_does_not_shadow_a_later_valid_one() -> None:
    # A body naming both a shape-matching non-date and a real date resolves
    # the real date: skipping is per token, not per body.
    page = b"CELEX:02024R1689-20269999 and CELEX:02024R1689-20270401"
    fetcher = FakeFetcher(_online(**{RESOLVER_URL: _response(page, url=RESOLVER_URL)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.NEW_CONSOLIDATION
    assert "2027-04-01" in finding.message


def test_the_response_url_date_takes_precedence_over_the_body() -> None:
    # The documented precedence, pinned: the date in the URL a resolver lands
    # on is read first; a body naming a different date is the fallback only.
    page = b'<a href="/legal-content/EN/TXT/?uri=CELEX:02024R1689-20270101">x</a>'
    fetcher = FakeFetcher(_online(**{RESOLVER_URL: _response(page, url=LATEST_URL)}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    assert report.ok


def test_a_dated_celex_inside_a_longer_digit_run_is_no_date() -> None:
    # Digit boundaries: a stem embedded in a longer digit run is not this
    # act's dated CELEX, and a ninth digit after the date is not a date.
    page = b"X102024R1689-20270101 02024R1689-202701011"
    fetcher = FakeFetcher(
        _online(
            **{
                RESOLVER_URL: _response(page, url=RESOLVER_URL),
                CELLAR_RESOLVER_URL: _response(b"", status=404),
                BASE_ACT_URL: _response(b"", status=404),
            }
        )
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY


@pytest.mark.parametrize("celex", [None, "32024R1689"])
def test_a_source_without_a_dated_celex_pin_is_not_watched(celex: str | None) -> None:
    # The watch derives from the ``celex`` field alone: no dated pin, no
    # watch, whatever the source's URL says.
    registry = _extract_registry(
        url="https://example.invalid/regulation",
        celex=celex,
        text=XI_1_1_A,
        sha256=sha256_of(XI_1_1_A),
    )
    fetcher = FakeFetcher(
        {
            "https://example.invalid/regulation": _response(
                ANNEX_EXCERPT.read_bytes(), url="https://example.invalid/regulation"
            ),
            FORM_URL: _response(FORM_BODY, url=FORM_URL),
        }
    )

    report = verify(registry, online=True, fetcher=fetcher)

    assert report.ok
    assert fetcher.calls == [
        ("https://example.invalid/regulation", 30.0),
        (FORM_URL, 30.0),
    ]


def test_two_sources_sharing_a_pin_resolve_it_once() -> None:
    first = _source("xi-1-1-a", text=XI_1_1_A, sha256=sha256_of(XI_1_1_A))
    second = first.model_copy(update={"id": "xi-1-1-b"})
    fetcher = FakeFetcher(
        _online(**{REGULATION_URL: _response(ANNEX_EXCERPT.read_bytes())})
    )

    report = verify(_registry_with([first, second]), online=True, fetcher=fetcher)

    assert report.ok
    assert [url for url, _ in fetcher.calls] == [
        REGULATION_URL,
        REGULATION_URL,
        FORM_URL,
        RESOLVER_URL,
    ]


def test_a_registry_without_a_consolidation_pin_is_not_watched() -> None:
    body = b"the guidelines pdf bytes"
    registry = _artifact_registry(artifact_sha256=hashlib.sha256(body).hexdigest())
    fetcher = FakeFetcher(
        {
            ARTIFACT_URL: _response(body, url=ARTIFACT_URL),
            FORM_URL: _response(FORM_BODY, url=FORM_URL),
        }
    )

    report = verify(registry, online=True, fetcher=fetcher)

    assert report.ok
    assert fetcher.calls == [(ARTIFACT_URL, 30.0), (FORM_URL, 30.0)]


# The Form DOCX.


def test_changed_form_bytes_are_an_artifact_change() -> None:
    fetcher = FakeFetcher(
        _online(**{FORM_URL: _response(b"different form bytes", url=FORM_URL)})
    )

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.ARTIFACT_CHANGED
    assert finding.target == "form"
    assert "hash" in finding.message


def test_matching_form_bytes_are_clean() -> None:
    fetcher = FakeFetcher(_online())

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    assert report.ok
    assert (FORM_URL, 30.0) in fetcher.calls


def test_an_unreachable_form_is_could_not_verify() -> None:
    fetcher = FakeFetcher(_online(**{FORM_URL: OSError("no route to host")}))

    report = verify(_verified_extract_registry(), online=True, fetcher=fetcher)

    (finding,) = report.findings
    assert finding.kind is FindingKind.COULD_NOT_VERIFY
    assert finding.target == "form"
    assert "no route to host" in finding.message


def test_the_form_is_checked_after_the_sources_and_before_the_watch() -> None:
    fetcher = FakeFetcher(
        _online(**{FORM_URL: _response(b"different form bytes", url=FORM_URL)})
    )

    report = verify(_extract_registry(), online=True, fetcher=fetcher)

    assert _kinds(report) == [FindingKind.TEXT_CHANGED, FindingKind.ARTIFACT_CHANGED]
    assert [url for url, _ in fetcher.calls] == [
        REGULATION_URL,
        FORM_URL,
        RESOLVER_URL,
    ]


def test_exit_code_is_zero_only_without_findings() -> None:
    assert exit_code(VerifyReport(findings=[])) == 0
    finding = VerifyFinding(
        kind=FindingKind.COULD_NOT_VERIFY, target="xi-1-1-a", message="unreachable"
    )
    assert exit_code(VerifyReport(findings=[finding])) == 1


@pytest.mark.parametrize(
    "kind",
    [
        FindingKind.INTEGRITY,
        FindingKind.TEXT_CHANGED,
        FindingKind.ARTIFACT_CHANGED,
        FindingKind.NEW_CONSOLIDATION,
        FindingKind.COULD_NOT_VERIFY,
        FindingKind.EXTRACTION_FAILED,
    ],
)
def test_finding_kinds_serialise_as_lower_snake_values(kind: FindingKind) -> None:
    assert kind.value == kind.name.lower()
