"""Fetch and re-extract the catalogue: the authoring half of the pipeline.

Writes only when every selected source re-fetched and re-extracted and the
regenerated file still validates; a failure - an anti-bot challenge served
as HTTP 202, say - is never a text change.
"""

import datetime
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError

from gpai_docs.registry import Registry, RegistryError, load_yaml_mapping
from gpai_docs.registry.extract import (
    ExtractionError,
    element_inventory,
    extract_article,
    extract_chapeau,
    extract_element,
    extract_following_note,
    sha256_of,
)
from gpai_docs.registry.models import ExtractionLocator, Source, SourcesFile

# Markers of the AWS WAF challenge page: a page, not the document, so reading
# it as HTML would turn it into a text change.
_WAF_CHALLENGE_MARKERS = (
    b"x-amzn-waf-action",
    b"aws-waf-token",
    b"challenge-container",
    b"AwsWafIntegration",
)

_USER_AGENT = "gpai-docs"


@dataclass
class FetchResult:
    """One fetched response, whatever the outcome: status, body, final URL."""

    body: bytes
    final_url: str
    status: int


class Fetcher(Protocol):
    """The injection seam that keeps the suite off the network."""

    def fetch(self, url: str, timeout: float) -> FetchResult:
        """Fetch ``url``, following redirects, within ``timeout`` seconds."""
        ...


class UrllibFetcher:
    """The default fetcher: stdlib urllib, no HTTP dependency."""

    def fetch(self, url: str, timeout: float = 30.0) -> FetchResult:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return FetchResult(
                    body=response.read(),
                    final_url=response.geturl(),
                    status=response.status,
                )
        except urllib.error.HTTPError as error:
            # An HTTP error is still a response: return its status in band.
            return FetchResult(
                body=error.read(), final_url=error.geturl(), status=error.code
            )


@dataclass
class FetchReport:
    """What one pass over the catalogue found, and whether it wrote."""

    changed: list[str]
    inventory_added: list[str]
    inventory_removed: list[str]
    written: bool
    # Sources that could not be re-fetched or re-extracted; never changes.
    failed: list[str] = field(default_factory=list)


def sources_path() -> Path:
    """The package-data ``sources.yaml`` that ``write`` regenerates."""
    return Path(__file__).resolve().parent / "sources.yaml"


def download_url(source: Source) -> str:
    return source.fetch_url or source.url


def run_fetch(
    registry: Registry,
    fetcher: Fetcher,
    *,
    celex: str | None,
    write: bool,
    timeout: float,
) -> FetchReport:
    """Re-fetch every selected source, diff it, and - with ``write`` - persist.

    The per-source diff goes to stderr, leaving stdout for the CLI's ``--json``
    payload.
    """
    changed: list[str] = []
    failed: list[str] = []
    inventories: dict[str, list[str]] = {}
    updated: list[Source] = []
    for source in registry.sources.values():
        if not _selected(source, celex):
            print(f"{source.id}: untouched", file=sys.stderr)
            updated.append(source)
            continue
        locator = source.extraction
        assert locator is not None  # the model requires it for extract sources
        try:
            result = fetcher.fetch(download_url(source), timeout)
        except OSError as error:
            failed.append(source.id)
            print(f"{source.id}: failed: {error}", file=sys.stderr)
            updated.append(source)
            continue
        if result.status != 200:
            failed.append(source.id)
            print(f"{source.id}: failed: HTTP {result.status}", file=sys.stderr)
            updated.append(source)
            continue
        if is_waf_challenge(result.body):
            failed.append(source.id)
            print(f"{source.id}: failed: WAF challenge", file=sys.stderr)
            updated.append(source)
            continue
        try:
            text = _extract_again(locator, result.body, inventories)
        except (ExtractionError, UnicodeDecodeError) as error:
            failed.append(source.id)
            print(f"{source.id}: failed: {error}", file=sys.stderr)
            updated.append(source)
            continue
        digest = sha256_of(text)
        if digest == source.sha256:
            print(f"{source.id}: unchanged", file=sys.stderr)
        else:
            changed.append(source.id)
            print(f"{source.id}: changed", file=sys.stderr)
            print(f"  old: {source.text}", file=sys.stderr)
            print(f"  new: {text}", file=sys.stderr)
            source = source.model_copy(
                update={
                    "text": text,
                    "sha256": digest,
                    "retrieved": datetime.date.today(),
                }
            )
        updated.append(source)

    added: list[str] = []
    removed: list[str] = []
    for annex, inventory in inventories.items():
        registered = [field.id for field in registry.fields if field.annex == annex]
        added.extend(
            identifier for identifier in inventory if identifier not in registered
        )
        removed.extend(
            identifier for identifier in registered if identifier not in inventory
        )

    written = False
    if write:
        if failed:
            print(
                "sources.yaml not written: not every selected source could be "
                "re-fetched",
                file=sys.stderr,
            )
        elif not changed:
            print("sources.yaml not written: nothing changed", file=sys.stderr)
        else:
            _write_sources(updated)
            written = True
    return FetchReport(
        changed=changed,
        inventory_added=added,
        inventory_removed=removed,
        written=written,
        failed=failed,
    )


def _selected(source: Source, celex: str | None) -> bool:
    if source.verification != "extract":
        return False
    return celex is None or source.celex == celex


def is_waf_challenge(body: bytes) -> bool:
    return any(marker in body for marker in _WAF_CHALLENGE_MARKERS)


def _extract_again(
    locator: ExtractionLocator, html: bytes, inventories: dict[str, list[str]]
) -> str:
    """Extract one source's text, recording its annex's inventory once."""
    if locator.annex is not None and locator.annex not in inventories:
        inventories[locator.annex] = element_inventory(html, locator.annex)
    return extract_from_locator(locator, html)


def extract_from_locator(locator: ExtractionLocator, html: bytes) -> str:
    """Extract a locator's provision text; every kind has an explicit arm.

    An unknown kind raises rather than falling through (the ``str`` widening
    keeps that arm reachable), so a schema addition can never silently hash
    the wrong provision.
    """
    kind = str(locator.kind)
    if kind == "chapeau":
        return extract_chapeau(html, _required(locator.annex, "annex"))
    if kind == "article":
        article = _required(locator.article, "article")
        return extract_article(html, article, locator.paragraph, locator.point)
    if kind == "element":
        return extract_element(
            html,
            _required(locator.annex, "annex"),
            _required(locator.item, "item"),
            # ``None`` is Section 2's letter-less shape; the locator model
            # rejects it everywhere else.
            locator.letter,
            locator.section,
        )
    if kind == "following_note":
        return extract_following_note(
            html,
            _required(locator.annex, "annex"),
            _required(locator.item, "item"),
            _required(locator.letter, "letter"),
            locator.section,
        )
    raise ExtractionError(f"unknown extraction kind {kind!r}")


def _required[ValueT](value: ValueT | None, what: str) -> ValueT:
    if value is None:
        raise ExtractionError(f"extraction locator is missing {what}")
    return value


def _write_sources(sources: list[Source]) -> None:
    """Regenerate ``sources.yaml`` without persisting an invalid file.

    The pack identity keys (``schema``, ``pack``) are kept; only ``sources``
    is rewritten.
    """
    path = sources_path()
    data = load_yaml_mapping(path)
    data["sources"] = [source.model_dump(exclude_none=True) for source in sources]
    try:
        SourcesFile.model_validate(data)
    except ValidationError as error:
        raise RegistryError(f"refusing to write {path}: {error}") from error
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
