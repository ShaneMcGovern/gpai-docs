"""The fetch pipeline, driven through a fake ``Fetcher``.

Canned responses come from the committed EUR-Lex excerpt, so the suite never
touches the network; tests that exercise ``--write`` copy
``tests/fixtures/registry_mini`` into ``tmp_path`` first.
"""

import dataclasses
import datetime
import email.message
import io
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from gpai_docs.registry import Registry, RegistryError, load
from gpai_docs.registry import fetch as fetch_module
from gpai_docs.registry.extract import ExtractionError, sha256_of
from gpai_docs.registry.fetch import (
    FetchResult,
    UrllibFetcher,
    extract_from_locator,
    run_fetch,
    sources_path,
)
from gpai_docs.registry.models import ExtractionLocator, Source

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "registry_mini"
ANNEX_EXCERPT = FIXTURES / "eurlex_annex_excerpt.html"
ARTICLES_EXCERPT = FIXTURES / "eurlex_articles_excerpt.html"

REGULATION_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727"
)

# The Annex XI inventory, pinned independently in tests/test_extract.py: the
# eleven lettered Section 1 points, then Section 2's three letter-less items.
XI_INVENTORY = [
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
    "XI.2.1",
    "XI.2.2",
    "XI.2.3",
]
XI_1_1_A = (
    "the tasks that the model is intended to perform and the type and nature of "
    "AI systems in which it can be integrated;"
)
XI_2_E = "known or estimated energy consumption of the model."
XI_CHAPEAU = (
    "The technical documentation referred to in Article 53(1), point (a) shall "
    "contain at least the following information as appropriate to the size and "
    "risk profile of the model:"
)
XI_2_E_NOTE = (
    "With regard to point (e), where the energy consumption of the model is "
    "unknown, the energy consumption may be based on information about "
    "computational resources used."
)
# Article 52(1), pinned independently in tests/test_extract.py.
A52_1 = (
    "Where a general-purpose AI model meets the condition referred to in "
    "Article 51(1), point (a), the relevant provider shall notify the "
    "Commission without delay and in any event within two weeks after that "
    "requirement is met or it becomes known that it will be met. That "
    "notification shall include the information necessary to demonstrate that "
    "the relevant requirement has been met. If the Commission becomes aware of "
    "a general-purpose AI model presenting systemic risks of which it has not "
    "been notified, it may decide to designate it as a model with systemic "
    "risk."
)


class FakeFetcher:
    """Canned responses by URL; records what was asked for."""

    def __init__(self, responses: dict[str, FetchResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def fetch(self, url: str, timeout: float) -> FetchResult:
        self.calls.append((url, timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _mini_registry() -> Registry:
    return load(MINI)


def _registry_copy(tmp_path: Path) -> Path:
    directory = tmp_path / "registry"
    shutil.copytree(MINI, directory)
    return directory


def _extract_source(**overrides: object) -> Source:
    """The fixture's extract-mode source with fields overridden."""
    data = _mini_registry().sources["xi-1-1-a"].model_dump()
    data.update(overrides)
    return Source.model_validate(data)


def _registry_with(sources: list[Source]) -> Registry:
    return dataclasses.replace(
        _mini_registry(), sources={source.id: source for source in sources}
    )


def _response(body: bytes, url: str = REGULATION_URL, status: int = 200) -> FetchResult:
    return FetchResult(body=body, final_url=url, status=status)


@pytest.fixture
def excerpt() -> bytes:
    return ANNEX_EXCERPT.read_bytes()


@pytest.fixture
def fetched(excerpt: bytes) -> FetchResult:
    return _response(excerpt)


@pytest.fixture
def write_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A writable copy of the mini registry, with ``sources_path`` in it."""
    directory = _registry_copy(tmp_path)
    monkeypatch.setattr(
        fetch_module, "sources_path", lambda: directory / "sources.yaml"
    )
    return directory


def test_a_dry_run_reports_changes_and_writes_nothing(
    write_dir: Path, fetched: FetchResult, capsys: pytest.CaptureFixture[str]
) -> None:
    fetcher = FakeFetcher({REGULATION_URL: fetched})
    before = (write_dir / "sources.yaml").read_bytes()

    report = run_fetch(load(write_dir), fetcher, celex=None, write=False, timeout=30.0)

    # The stored fixture text is an abridgement of the provision, so the
    # re-extraction differs and the report says so.
    assert report.changed == ["xi-1-1-a"]
    assert report.failed == []
    assert report.written is False
    assert (write_dir / "sources.yaml").read_bytes() == before
    # The artifact-mode source is never fetched: only one URL was asked for.
    assert fetcher.calls == [(REGULATION_URL, 30.0)]
    assert "xi-1-1-a: changed" in capsys.readouterr().err


def test_write_persists_the_regenerated_catalogue(
    write_dir: Path, fetched: FetchResult
) -> None:
    before = load(write_dir)
    report = run_fetch(
        load(write_dir),
        FakeFetcher({REGULATION_URL: fetched}),
        celex=None,
        write=True,
        timeout=30.0,
    )

    assert report.written is True
    assert report.changed == ["xi-1-1-a"]
    written = load(write_dir)
    assert written.sources["xi-1-1-a"].text == XI_1_1_A
    # The stored text and its hash move together, and retrieved moves with them.
    assert written.sources["xi-1-1-a"].sha256 == sha256_of(XI_1_1_A)
    assert written.sources["xi-1-1-a"].retrieved == datetime.date.today()
    assert all(
        source.sha256 == sha256_of(source.text) for source in written.sources.values()
    )
    # The artifact-mode source is untouched, retrieved date included.
    artifact = written.sources["guidelines-energy-estimate"]
    assert artifact.text == before.sources["guidelines-energy-estimate"].text
    assert artifact.retrieved == before.sources["guidelines-energy-estimate"].retrieved


def test_a_refetch_whose_text_is_unchanged_reports_nothing(
    write_dir: Path, fetched: FetchResult, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = load(write_dir)
    registry.sources["xi-1-1-a"] = _extract_source(
        text=XI_1_1_A, sha256=sha256_of(XI_1_1_A)
    )
    before = (write_dir / "sources.yaml").read_bytes()

    report = run_fetch(
        registry,
        FakeFetcher({REGULATION_URL: fetched}),
        celex=None,
        write=True,
        timeout=30.0,
    )

    assert report.changed == []
    assert report.failed == []
    assert report.written is False
    assert (write_dir / "sources.yaml").read_bytes() == before
    assert "xi-1-1-a: unchanged" in capsys.readouterr().err


def test_the_inventory_diff_reports_ids_that_appear_and_vanish(
    fetched: FetchResult,
) -> None:
    registry = _registry_with([_extract_source()])
    # Register a phantom field the document does not carry: it has vanished.
    phantom = registry.fields[0].model_copy(update={"id": "XI.1.1.g", "point": "1(g)"})
    registry = dataclasses.replace(
        registry,
        fields=[*registry.fields, phantom],
        by_id={**registry.by_id, phantom.id: phantom},
    )

    report = run_fetch(
        registry,
        FakeFetcher({REGULATION_URL: fetched}),
        celex=None,
        write=False,
        timeout=30.0,
    )
    assert report.inventory_added == [i for i in XI_INVENTORY if i != "XI.1.1.a"]
    assert report.inventory_removed == ["XI.1.1.g"]

    # Add a point to the document that no registered field covers: it has
    # appeared.
    anchor = b'<p class="norm">the licence.</p>'
    addition = (
        b'<div class="grid-container grid-list">'
        b'<div class="list grid-list-column-1"><span>(g)\xc2\xa0</span></div>'
        b'<div class="grid-list-column-2">'
        b'<p class="norm">a newly added provision.</p></div>'
        b"</div>"
    )
    assert fetched.body.count(anchor) == 1
    grown = _response(fetched.body.replace(anchor, anchor + addition))

    grown_report = run_fetch(
        _registry_with([_extract_source()]),
        FakeFetcher({REGULATION_URL: grown}),
        celex=None,
        write=False,
        timeout=30.0,
    )
    assert "XI.1.1.g" in grown_report.inventory_added
    assert len(grown_report.inventory_added) == len(XI_INVENTORY)
    assert grown_report.inventory_removed == []


def test_the_inventory_is_diffed_once_per_annex(excerpt: bytes) -> None:
    registry = _registry_with(
        [
            _extract_source(text=XI_1_1_A, sha256=sha256_of(XI_1_1_A)),
            _extract_source(
                id="xi-2-e",
                text=XI_2_E,
                sha256=sha256_of(XI_2_E),
                extraction=ExtractionLocator(
                    kind="element", annex="XI", section=1, item=2, letter="e"
                ),
            ),
        ]
    )

    report = run_fetch(
        registry,
        FakeFetcher({REGULATION_URL: _response(excerpt)}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.changed == []
    assert len(report.inventory_added) == len(set(report.inventory_added))


def test_a_non_200_response_is_a_failure_not_a_change(
    write_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # What EUR-Lex sometimes serves: a WAF challenge arrives as
    # HTTP 202 with an empty body, never as a document.
    fetcher = FakeFetcher({REGULATION_URL: _response(b"", status=202)})
    before = (write_dir / "sources.yaml").read_bytes()

    report = run_fetch(load(write_dir), fetcher, celex=None, write=True, timeout=30.0)

    assert report.failed == ["xi-1-1-a"]
    assert report.changed == []
    assert report.written is False
    assert (write_dir / "sources.yaml").read_bytes() == before
    assert "xi-1-1-a: failed: HTTP 202" in capsys.readouterr().err


def test_a_waf_challenge_page_is_a_failure_even_with_status_200(
    write_dir: Path,
) -> None:
    challenge = b'<html><body><script src="/aws-waf-token.js"></script></body></html>'
    report = run_fetch(
        load(write_dir),
        FakeFetcher({REGULATION_URL: _response(challenge)}),
        celex=None,
        write=True,
        timeout=30.0,
    )

    assert report.failed == ["xi-1-1-a"]
    assert report.changed == []
    assert report.written is False


def test_an_unreachable_source_is_a_failure(
    write_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fetcher = FakeFetcher({REGULATION_URL: OSError("connection refused")})

    report = run_fetch(load(write_dir), fetcher, celex=None, write=False, timeout=1.0)

    assert report.failed == ["xi-1-1-a"]
    assert report.changed == []
    assert "connection refused" in capsys.readouterr().err


def test_a_document_without_the_annex_is_a_failure(write_dir: Path) -> None:
    other = b"<html><body><p>A different page entirely.</p></body></html>"

    report = run_fetch(
        load(write_dir),
        FakeFetcher({REGULATION_URL: _response(other)}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.failed == ["xi-1-1-a"]
    assert report.changed == []


def test_a_point_the_document_no_longer_carries_is_a_failure(
    fetched: FetchResult,
) -> None:
    source = _extract_source(
        id="xi-1-1-g",
        location="Annex XI, Section 1, point 1(g)",
        extraction=ExtractionLocator(
            kind="element", annex="XI", section=1, item=1, letter="g"
        ),
    )

    report = run_fetch(
        _registry_with([source]),
        FakeFetcher({REGULATION_URL: fetched}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.failed == ["xi-1-1-g"]
    assert report.changed == []


def test_a_body_that_is_not_utf8_text_is_a_failure(write_dir: Path) -> None:
    body = b"\xff\xfe\x00\x01 not html"

    report = run_fetch(
        load(write_dir),
        FakeFetcher({REGULATION_URL: _response(body)}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.failed == ["xi-1-1-a"]
    assert report.changed == []


def test_a_failure_prevents_the_write(
    write_dir: Path, fetched: FetchResult, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_url = "https://example.invalid/unreachable"
    registry = _registry_with(
        [
            _extract_source(),
            _extract_source(
                id="xi-1-1-b",
                url=bad_url,
                location="Annex XI, Section 1, point 1(b)",
                extraction=ExtractionLocator(
                    kind="element", annex="XI", section=1, item=1, letter="b"
                ),
            ),
        ]
    )
    before = (write_dir / "sources.yaml").read_bytes()

    report = run_fetch(
        registry,
        FakeFetcher({REGULATION_URL: fetched, bad_url: OSError("boom")}),
        celex=None,
        write=True,
        timeout=30.0,
    )

    # The changed source is reported, but nothing is written while any source
    # could not be re-fetched: the catalogue never mixes fresh and stale text.
    assert report.changed == ["xi-1-1-a"]
    assert report.failed == ["xi-1-1-b"]
    assert report.written is False
    assert (write_dir / "sources.yaml").read_bytes() == before
    assert "not written" in capsys.readouterr().err


def test_a_chapeau_and_a_following_note_use_their_own_extractors(
    write_dir: Path, fetched: FetchResult
) -> None:
    placeholders = {
        "xi-chapeau": "PLACEHOLDER chapeau",
        "xi-2-e-note": "PLACEHOLDER note",
    }
    registry = _registry_with(
        [
            _extract_source(
                id="xi-chapeau",
                location="Annex XI, chapeau",
                extraction=ExtractionLocator(kind="chapeau", annex="XI"),
                text=placeholders["xi-chapeau"],
                sha256=sha256_of(placeholders["xi-chapeau"]),
            ),
            _extract_source(
                id="xi-2-e-note",
                location="Annex XI, Section 1, point 2(e), note",
                extraction=ExtractionLocator(
                    kind="following_note", annex="XI", section=1, item=2, letter="e"
                ),
                text=placeholders["xi-2-e-note"],
                sha256=sha256_of(placeholders["xi-2-e-note"]),
            ),
        ]
    )

    report = run_fetch(
        registry,
        FakeFetcher({REGULATION_URL: fetched}),
        celex=None,
        write=True,
        timeout=30.0,
    )

    assert report.changed == ["xi-chapeau", "xi-2-e-note"]
    written = load(write_dir)
    assert written.sources["xi-chapeau"].text == XI_CHAPEAU
    assert written.sources["xi-2-e-note"].text == XI_2_E_NOTE


def test_a_fetch_url_is_preferred_over_the_canonical_url(
    fetched: FetchResult,
) -> None:
    # The canonical URL stays the human-facing citation; the pipeline fetches
    # the machine endpoint the source pins for the same text.
    cellar_url = "https://publications.europa.eu/resource/celex/02024R1689-20260727"
    source = _extract_source(fetch_url=cellar_url)

    report = run_fetch(
        _registry_with([source]),
        FakeFetcher({cellar_url: _response(fetched.body, cellar_url)}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.changed == ["xi-1-1-a"]
    assert report.failed == []


def test_an_article_source_re_extracts_through_the_locator_dispatcher() -> None:
    articles = ARTICLES_EXCERPT.read_bytes()
    source = _extract_source(
        id="art-52-1",
        location="Article 52(1)",
        extraction=ExtractionLocator(kind="article", article=52, paragraph=1),
        text=A52_1,
        sha256=sha256_of(A52_1),
    )

    report = run_fetch(
        _registry_with([source]),
        FakeFetcher({REGULATION_URL: _response(articles)}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.changed == []
    assert report.failed == []
    # Article locators carry no annex, so no element inventory is attempted
    # against a document that has none.
    assert report.inventory_added == []
    assert report.inventory_removed == []


def test_an_article_source_whose_text_drifted_is_a_change() -> None:
    stored = "a stored abridgement"
    source = _extract_source(
        id="art-52-1",
        location="Article 52(1)",
        extraction=ExtractionLocator(kind="article", article=52, paragraph=1),
        text=stored,
        sha256=sha256_of(stored),
    )

    report = run_fetch(
        _registry_with([source]),
        FakeFetcher({REGULATION_URL: _response(ARTICLES_EXCERPT.read_bytes())}),
        celex=None,
        write=False,
        timeout=30.0,
    )

    assert report.changed == ["art-52-1"]
    assert report.failed == []


def test_an_unknown_locator_kind_raises_instead_of_falling_through() -> None:
    # A kind added to the schema without a dispatcher arm must fail loudly,
    # never silently route to another kind's extractor.
    locator = ExtractionLocator(
        kind="element", annex="XI", section=1, item=1, letter="a"
    )
    bogus = locator.model_copy(update={"kind": "bogus"})

    with pytest.raises(ExtractionError, match="unknown extraction kind"):
        extract_from_locator(bogus, b"<html></html>")


def test_a_locator_missing_a_required_field_raises_instead_of_extracting() -> None:
    locator = ExtractionLocator(
        kind="element", annex="XI", section=1, item=1, letter="a"
    )
    incomplete = locator.model_copy(update={"item": None})

    with pytest.raises(ExtractionError, match="missing item"):
        extract_from_locator(incomplete, b"<html></html>")


def test_the_celex_filter_narrows_the_run(
    excerpt: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    other_url = "https://example.invalid/other"
    registry = _registry_with(
        [
            _extract_source(),
            _extract_source(
                id="xi-1-1-b",
                celex="02024R1689-20250101",
                url=other_url,
                location="Annex XI, Section 1, point 1(b)",
                extraction=ExtractionLocator(
                    kind="element", annex="XI", section=1, item=1, letter="b"
                ),
            ),
        ]
    )
    fetcher = FakeFetcher(
        {REGULATION_URL: _response(excerpt), other_url: _response(excerpt, other_url)}
    )

    report = run_fetch(
        registry,
        fetcher,
        celex="02024R1689-20260727",
        write=False,
        timeout=30.0,
    )

    assert [url for url, _ in fetcher.calls] == [REGULATION_URL]
    assert report.failed == []
    assert "xi-1-1-b: untouched" in capsys.readouterr().err


def test_write_refuses_a_regenerated_file_that_fails_validation(
    write_dir: Path, fetched: FetchResult
) -> None:
    target = write_dir / "sources.yaml"
    # An unknown top-level key is a defect anywhere in the registry data
    # (``extra="forbid"``); the run must refuse rather than persist it.
    doctored = target.read_text(encoding="utf-8") + "unknown_key: true\n"
    target.write_text(doctored, encoding="utf-8")

    with pytest.raises(RegistryError, match="refusing to write"):
        run_fetch(
            _mini_registry(),
            FakeFetcher({REGULATION_URL: fetched}),
            celex=None,
            write=True,
            timeout=30.0,
        )

    assert target.read_text(encoding="utf-8") == doctored


class _CannedResponse:
    """The bits of an ``http.client.HTTPResponse`` the fetcher uses."""

    def __init__(self, body: bytes, url: str, status: int) -> None:
        self._body = body
        self._url = url
        self._status = status

    @property
    def status(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "_CannedResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    outcome: _CannedResponse | Exception,
) -> list[tuple[urllib.request.Request, float | None]]:
    captured: list[tuple[urllib.request.Request, float | None]] = []

    def fake_urlopen(
        request: urllib.request.Request, timeout: float | None = None
    ) -> _CannedResponse:
        captured.append((request, timeout))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


def test_urllib_fetcher_records_the_final_url_and_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _CannedResponse(b"<html/>", "https://final.invalid/page", 200)
    captured = _patch_urlopen(monkeypatch, response)

    result = UrllibFetcher().fetch("https://start.invalid/page", 12.5)

    assert result == FetchResult(
        body=b"<html/>", final_url="https://final.invalid/page", status=200
    )
    assert captured[0][1] == 12.5
    assert captured[0][0].full_url == "https://start.invalid/page"


def test_urllib_fetcher_defaults_to_a_thirty_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_urlopen(
        monkeypatch, _CannedResponse(b"<html/>", "https://x.invalid", 200)
    )

    UrllibFetcher().fetch("https://x.invalid")

    assert captured[0][1] == 30.0


def test_urllib_fetcher_returns_http_errors_in_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = urllib.error.HTTPError(
        "https://x.invalid/page",
        503,
        "Service Unavailable",
        email.message.Message(),
        io.BytesIO(b"down"),
    )
    _patch_urlopen(monkeypatch, error)

    result = UrllibFetcher().fetch("https://x.invalid/page", 30.0)

    assert result == FetchResult(
        body=b"down", final_url="https://x.invalid/page", status=503
    )


def test_urllib_fetcher_lets_connection_failures_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_urlopen(monkeypatch, urllib.error.URLError("no route to host"))

    with pytest.raises(OSError, match="no route to host"):
        UrllibFetcher().fetch("https://x.invalid/page", 30.0)


def test_sources_path_is_the_package_data_file() -> None:
    package = Path(fetch_module.__file__).resolve().parent
    assert sources_path() == package / "sources.yaml"
