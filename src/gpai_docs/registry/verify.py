"""Verification: the stored registry against its hashes, and against the source.

``--online`` re-fetches every source and the Form and watches the pins;
nothing raises for a remote failure, so each failure maps to one finding kind
and a challenged page never reads as drift.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from gpai_docs.registry.extract import ExtractionError, sha256_of
from gpai_docs.registry.fetch import (
    Fetcher,
    FetchResult,
    UrllibFetcher,
    download_url,
    extract_from_locator,
    is_waf_challenge,
)
from gpai_docs.registry.models import DATED_CELEX, FormFile, Source

if TYPE_CHECKING:
    from gpai_docs.registry import Registry

__all__ = [
    "FindingKind",
    "VerifyFinding",
    "VerifyReport",
    "exit_code",
    "verify",
]


class FindingKind(StrEnum):
    """The six finding kinds, never conflated."""

    INTEGRITY = "integrity"
    TEXT_CHANGED = "text_changed"
    ARTIFACT_CHANGED = "artifact_changed"
    NEW_CONSOLIDATION = "new_consolidation"
    COULD_NOT_VERIFY = "could_not_verify"
    EXTRACTION_FAILED = "extraction_failed"


@dataclass
class VerifyFinding:
    kind: FindingKind
    target: str
    message: str


@dataclass
class VerifyReport:
    """What one verification pass found; ``ok`` is the clean-run answer."""

    findings: list[VerifyFinding]

    @property
    def ok(self) -> bool:
        return not self.findings


def exit_code(report: VerifyReport) -> int:
    """The shared exit contract: 0 with no findings, 1 with any."""
    return 0 if report.ok else 1


# The Form artefact's finding target: form.yaml pins one artefact that carries
# no catalogue id of its own, so findings name it by its place in the pack.
_FORM_TARGET = "form"


class _UnavailableError(Exception):
    """A fetch could not be verified: unreachable, challenged, or off-host."""


def verify(
    registry: Registry,
    *,
    online: bool = False,
    fetcher: Fetcher | None = None,
    timeout: float = 30.0,
) -> VerifyReport:
    """Verify the registry offline; with ``online``, also its live sources.

    ``fetcher`` is the injection seam that keeps the suite off the network;
    ``None`` means the default :class:`UrllibFetcher`, for an online pass only.
    """
    findings = _integrity_findings(registry)
    if online:
        client = fetcher if fetcher is not None else UrllibFetcher()
        findings.extend(_online_findings(registry, client, timeout))
    return VerifyReport(findings=findings)


def _integrity_findings(registry: Registry) -> list[VerifyFinding]:
    """Stored-text hashes and field-to-source references (kind 1)."""
    findings: list[VerifyFinding] = []
    for source in registry.sources.values():
        digest = sha256_of(source.text)
        if digest != source.sha256:
            findings.append(
                VerifyFinding(
                    FindingKind.INTEGRITY,
                    source.id,
                    f"stored text hashes to {digest}, not the registered "
                    f"{source.sha256}",
                )
            )
    for field in registry.fields:
        for reference in (field.source, *field.context):
            if reference not in registry.sources:
                findings.append(
                    VerifyFinding(
                        FindingKind.INTEGRITY,
                        field.id,
                        f"references unknown source {reference!r}",
                    )
                )
    return findings


def _online_findings(
    registry: Registry, fetcher: Fetcher, timeout: float
) -> list[VerifyFinding]:
    findings: list[VerifyFinding] = []
    for source in registry.sources.values():
        finding = _source_finding(source, fetcher, timeout)
        if finding is not None:
            findings.append(finding)
    form_finding = _form_finding(registry.form, fetcher, timeout)
    if form_finding is not None:
        findings.append(form_finding)
    findings.extend(_consolidation_findings(registry, fetcher, timeout))
    return findings


def _source_finding(
    source: Source, fetcher: Fetcher, timeout: float
) -> VerifyFinding | None:
    """Re-fetch and compare one source, or say why that could not happen."""
    if source.verification == "artifact":
        url = source.artifact_url
        if url is None:
            return VerifyFinding(
                FindingKind.COULD_NOT_VERIFY,
                source.id,
                "artifact source carries no artifact_url",
            )
        try:
            result = _fetch_checked(fetcher, url, timeout)
        except _UnavailableError as error:
            return VerifyFinding(FindingKind.COULD_NOT_VERIFY, source.id, str(error))
        digest = hashlib.sha256(result.body).hexdigest()
        if digest != source.artifact_sha256:
            return VerifyFinding(
                FindingKind.ARTIFACT_CHANGED,
                source.id,
                f"artifact bytes hash to {digest}, not the registered "
                f"{source.artifact_sha256}",
            )
        return None

    locator = source.extraction
    if locator is None:
        return VerifyFinding(
            FindingKind.COULD_NOT_VERIFY,
            source.id,
            "extract source carries no extraction locator",
        )
    url = download_url(source)
    try:
        result = _fetch_checked(fetcher, url, timeout)
    except _UnavailableError as error:
        return VerifyFinding(FindingKind.COULD_NOT_VERIFY, source.id, str(error))
    try:
        text = extract_from_locator(locator, result.body)
    except (ExtractionError, UnicodeDecodeError) as error:
        return VerifyFinding(
            FindingKind.EXTRACTION_FAILED,
            source.id,
            f"re-extraction from {url} failed: {error}",
        )
    digest = sha256_of(text)
    if digest != source.sha256:
        return VerifyFinding(
            FindingKind.TEXT_CHANGED,
            source.id,
            f"re-extracted text hashes to {digest}, not the registered {source.sha256}",
        )
    return None


def _form_finding(
    form_file: FormFile, fetcher: Fetcher, timeout: float
) -> VerifyFinding | None:
    """Re-download the pinned Form DOCX and compare its bytes."""
    form = form_file.form
    try:
        result = _fetch_checked(fetcher, form.source_url, timeout)
    except _UnavailableError as error:
        return VerifyFinding(FindingKind.COULD_NOT_VERIFY, _FORM_TARGET, str(error))
    digest = hashlib.sha256(result.body).hexdigest()
    if digest != form.artifact_sha256:
        return VerifyFinding(
            FindingKind.ARTIFACT_CHANGED,
            _FORM_TARGET,
            f"form bytes hash to {digest}, not the registered {form.artifact_sha256}",
        )
    return None


def _fetch_checked(fetcher: Fetcher, url: str, timeout: float) -> FetchResult:
    """Fetch ``url``, or raise :class:`_UnavailableError` with the reason.

    Anything that is not the document (a non-200, a WAF challenge, an
    off-host landing) is stopped here, so it can never read as content drift.
    """
    try:
        result = fetcher.fetch(url, timeout)
    except OSError as error:
        raise _UnavailableError(f"could not fetch {url}: {error}") from error
    if result.status != 200:
        raise _UnavailableError(f"{url} answered HTTP {result.status}")
    if is_waf_challenge(result.body):
        raise _UnavailableError(f"{url} served a WAF challenge page, not the document")
    if _host(result.final_url) != _host(url):
        raise _UnavailableError(
            f"{url} redirected off {_host(url)} to {result.final_url}"
        )
    return result


def _consolidation_findings(
    registry: Registry, fetcher: Fetcher, timeout: float
) -> list[VerifyFinding]:
    """Watch each pinned consolidation CELEX for a newer consolidated version."""
    findings: list[VerifyFinding] = []
    for pin, candidates in _consolidations(registry).items():
        undated = pin.split("-")[0]
        latest, attempts = _latest_consolidation(candidates, undated, fetcher, timeout)
        if latest is None:
            findings.append(
                VerifyFinding(
                    FindingKind.COULD_NOT_VERIFY,
                    undated,
                    f"could not resolve the latest consolidation of {pin}: "
                    + "; ".join(attempts),
                )
            )
        elif latest > _date_of(pin):
            findings.append(
                VerifyFinding(
                    FindingKind.NEW_CONSOLIDATION,
                    undated,
                    f"the latest consolidation is {latest.isoformat()}, newer "
                    f"than the pinned {pin}",
                )
            )
    return findings


def _latest_consolidation(
    candidates: list[str], undated: str, fetcher: Fetcher, timeout: float
) -> tuple[datetime.date | None, list[str]]:
    """The newest date the first answering candidate names, plus the attempts.

    ``None`` means none resolved; the attempts then carry one reason each, for
    the could-not-verify message.
    """
    attempts: list[str] = []
    for url in candidates:
        try:
            result = _fetch_checked(fetcher, url, timeout)
        except _UnavailableError as error:
            attempts.append(str(error))
            continue
        latest = _newest_dated_date(result.final_url, undated) or _newest_dated_date(
            result.body.decode("utf-8", errors="replace"), undated
        )
        if latest is not None:
            return latest, attempts
        attempts.append(f"{url} named no dated consolidation")
    return None, attempts


def _consolidations(registry: Registry) -> dict[str, list[str]]:
    """Each dated consolidation CELEX mapped to its candidate resolver URLs.

    Derived from the source's own ``celex``, never the fetch URL, which may be
    a CELEX-less Cellar item URL from which no resolver can be derived.
    """
    consolidations: dict[str, list[str]] = {}
    for source in registry.sources.values():
        celex = source.celex
        if celex is None or not DATED_CELEX.fullmatch(celex):
            continue
        if celex not in consolidations:
            consolidations[celex] = _consolidation_candidates(celex.split("-")[0])
    return consolidations


def _consolidation_candidates(undated: str) -> list[str]:
    """The resolver forms for an undated consolidation CELEX; the act's own
    identifier swaps its sector digit to 3, consolidations sitting in sector
    0. The probe record is in docs/methodology.md, "The change process".
    """
    act = "3" + undated[1:]
    return [
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{undated}",
        f"https://publications.europa.eu/resource/celex/{undated}",
        f"https://publications.europa.eu/resource/celex/{act}",
    ]


def _newest_dated_date(text: str, undated: str) -> datetime.date | None:
    """The newest ``<undated>-YYYYMMDD`` token in ``text`` that is a date.

    A body may name the whole chain (oldest first), so the newest wins; a
    shape-matching non-date is skipped, never raised, and the digit boundaries
    keep an embedded stem from reading as a pin.
    """
    dates: list[datetime.date] = []
    for match in re.finditer(
        r"(?<!\d)" + re.escape(undated) + r"-(\d{4})(\d{2})(\d{2})(?!\d)", text
    ):
        try:
            dates.append(
                datetime.date(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                )
            )
        except ValueError:
            continue
    return max(dates) if dates else None


def _date_of(pin: str) -> datetime.date:
    """The date encoded in a dated CELEX, e.g. 02024R1689-20260727."""
    stamp = pin[-8:]
    return datetime.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""
