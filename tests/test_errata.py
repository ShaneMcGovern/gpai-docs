"""Shape pins for the public errata log, ``docs/errata.md``.

The log is Markdown, not data, so this file carries the parser the pins walk:
the shipped log must satisfy it, and the ways an entry can rot (a missing
field, an impossible date, wrong order, an unknown registry id) are rejected.
"""

from __future__ import annotations

import datetime
import itertools
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from gpai_docs.registry import load
from gpai_docs.registry.models import _FIELD_ID

ROOT = Path(__file__).resolve().parents[1]
ERRATA = ROOT / "docs" / "errata.md"

# The entry heading the log's format pins: ``## YYYY-MM-DD``, a spaced
# hyphen, then the title.
_HEADING = re.compile(r"^## (?P<date>\d{4}-\d{2}-\d{2}) - (?P<title>.+)$")
# The bold fields every entry carries, in their pinned order.
_FIELDS = ("What changed", "Why", "Verify")
# A commit the Verify field cites; seven hex digits is git's shortest form.
_COMMIT = re.compile(r"\b[0-9a-f]{7,40}\b")


class ErrataFormatError(ValueError):
    """The log's pinned entry shape is violated."""


@dataclass(frozen=True)
class Entry:
    """One dated correction."""

    date: datetime.date
    title: str
    fields: dict[str, str]


def parse_entries(text: str) -> list[Entry]:
    """Parse the log into entries, rejecting anything off the pinned shape."""
    blocks: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []

    def close() -> None:
        nonlocal heading, body
        if heading is not None:
            blocks.append((heading, "\n".join(body)))
        heading, body = None, []

    for line in text.splitlines():
        if line.startswith("## "):
            close()
            heading = line
        elif heading is not None:
            body.append(line)
    close()
    if not blocks:
        raise ErrataFormatError("the log carries no entries")
    entries = [_parse_entry(heading, body) for heading, body in blocks]
    _check_order(entries)
    return entries


def _parse_entry(heading: str, body: str) -> Entry:
    """One entry from its heading and body lines."""
    match = _HEADING.match(heading)
    if match is None:
        raise ErrataFormatError(f"malformed entry heading: {heading!r}")
    try:
        date = datetime.date.fromisoformat(match.group("date"))
    except ValueError as error:
        raise ErrataFormatError(f"unparseable entry date: {heading!r}") from error
    return Entry(
        date=date,
        title=match.group("title").strip(),
        fields=_fields(body),
    )


def _fields(body: str) -> dict[str, str]:
    """The three bold fields, once each, in their pinned order, non-empty."""
    starts: list[int] = []
    for name in _FIELDS:
        marker = f"**{name}**"
        if body.count(marker) != 1:
            raise ErrataFormatError(f"entry field {marker} is missing or repeated")
        starts.append(body.index(marker))
    if starts != sorted(starts):
        raise ErrataFormatError("entry fields are out of their pinned order")
    fields: dict[str, str] = {}
    for index, name in enumerate(_FIELDS):
        start = starts[index] + len(f"**{name}**")
        end = starts[index + 1] if index + 1 < len(_FIELDS) else len(body)
        value = body[start:end].strip()
        value = value[1:].strip() if value[:1] in ":." else value
        if not value:
            raise ErrataFormatError(f"entry field **{name}** is empty")
        fields[name] = value
    return fields


def _check_order(entries: list[Entry]) -> None:
    """Entries are reverse-chronological: dates never increase downward."""
    dates = [entry.date for entry in entries]
    for before, after in itertools.pairwise(dates):
        if after > before:
            raise ErrataFormatError("entries are not in reverse-chronological order")


def _check_ids(entries: list[Entry], known: set[str]) -> None:
    """Every registry-id-shaped token a Verify cites names a registry field."""
    for entry in entries:
        for field_id in sorted(set(_FIELD_ID.findall(entry.fields["Verify"]))):
            if field_id not in known:
                raise ErrataFormatError(
                    f"entry {entry.date} cites unknown registry id {field_id!r}"
                )


def _entry(date: str, verify: str = "commit 0123456") -> str:
    return (
        f"## {date} - A fixture entry\n\n"
        "**What changed**: The thing.\n\n"
        "**Why**: It was wrong.\n\n"
        f"**Verify**: {verify}\n"
    )


_MISSING_FIELD = (
    "## 2026-10-09 - A fixture entry\n\n"
    "**What changed**: The thing.\n\n"
    "**Verify**: commit 0123456\n"
)
_BAD_DATE = (
    "## 2026-02-30 - A fixture entry\n\n"
    "**What changed**: The thing.\n\n"
    "**Why**: It was wrong.\n\n"
    "**Verify**: commit 0123456\n"
)
_WRONG_ORDER = _entry("2026-10-09") + "\n" + _entry("2026-10-10")
_UNKNOWN_ID = _entry("2026-10-09", verify="the registry id XI.2.9")
_UNORDERED_FIELDS = (
    "## 2026-10-09 - A fixture entry\n\n"
    "**Why**: It was wrong.\n\n"
    "**What changed**: The thing.\n\n"
    "**Verify**: commit 0123456\n"
)
# The commits the log was seeded with; the pin below keeps them cited.
_SEEDED = ("2d7ddd7", "c64bd43", "692530a")


def test_a_missing_field_is_rejected() -> None:
    with pytest.raises(ErrataFormatError):
        parse_entries(_MISSING_FIELD)


def test_an_impossible_date_is_rejected() -> None:
    with pytest.raises(ErrataFormatError):
        parse_entries(_BAD_DATE)


def test_entries_in_the_wrong_order_are_rejected() -> None:
    with pytest.raises(ErrataFormatError):
        parse_entries(_WRONG_ORDER)


def test_fields_out_of_their_pinned_order_are_rejected() -> None:
    with pytest.raises(ErrataFormatError):
        parse_entries(_UNORDERED_FIELDS)


def test_an_unknown_registry_id_in_verify_is_rejected() -> None:
    known = {field.id for field in load().fields}
    with pytest.raises(ErrataFormatError):
        _check_ids(parse_entries(_UNKNOWN_ID), known)


@pytest.fixture(scope="module")
def entries() -> list[Entry]:
    return parse_entries(ERRATA.read_text(encoding="utf-8"))


def test_the_log_carries_the_backfilled_corrections(entries: list[Entry]) -> None:
    assert len(entries) >= 3


def test_the_seeded_corrections_stay_cited(entries: list[Entry]) -> None:
    cited = " ".join(entry.fields["Verify"] for entry in entries)
    for commit in _SEEDED:
        assert commit in cited


def test_the_readme_links_the_log() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "](docs/errata.md)" in readme


def test_the_process_is_stated_before_the_entries() -> None:
    process = ERRATA.read_text(encoding="utf-8").split("## ", 1)[0]
    assert "append-only" in process
    assert "fix(registry):" in process
    assert "fix(format):" in process


def test_entries_are_newest_first(entries: list[Entry]) -> None:
    dates = [entry.date for entry in entries]
    assert dates == sorted(dates, reverse=True)


def test_every_entry_carries_its_three_fields(entries: list[Entry]) -> None:
    for entry in entries:
        assert entry.title
        for name in _FIELDS:
            assert entry.fields[name], (entry.date, name)


def test_every_verify_names_a_commit(entries: list[Entry]) -> None:
    for entry in entries:
        assert _COMMIT.search(entry.fields["Verify"]), entry.date


def test_verify_ids_resolve_against_the_registry(entries: list[Entry]) -> None:
    _check_ids(entries, {field.id for field in load().fields})
