"""The native document format, its loader and its YAML writer.

What the format does not shape rides through raw, so a typo'd section name
is a finding, not a silent drop; the writer spells strings through the
reader's grammar, so what it writes reloads as the document it says it is.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gpai_docs.registry import (
    RegistryError,
    _UniqueKeyLoader,
    load_yaml_mapping,
)

__all__ = ["Document", "DocumentError", "dump_document_yaml", "load_document"]

SECTIONS = ("annex_xi", "annex_xii")
# The loader checks their shape only.
RECORDS = ("notifications", "modifications")
_MARKER = "schema"
_VERSION = 1


class DocumentError(Exception):
    """A document file is unreadable or does not have the document shape."""


@dataclass
class Document:
    """One loaded document.

    ``values`` holds the unreserved top-level keys raw and in file order;
    ``records`` holds the records sections unread, for the typed pass.
    """

    values: dict[str, object]
    records: dict[str, object] = field(default_factory=dict)


def load_document(path: Path) -> Document:
    """Load one document, refusing duplicate keys and unreadable shapes.

    Blank content reads as an empty mapping, so an empty file fails the marker
    rule like any other file without one. A ``.json`` file parses
    under JSON's own number grammar; the rest go through
    the shared registry reader, which re-reads the file.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DocumentError(f"cannot read {path}: {error}") from error
    if raw.strip():
        try:
            data = (
                _load_json_mapping(raw, path)
                if path.suffix.lower() == ".json"
                else load_yaml_mapping(path)
            )
        except RegistryError as error:
            raise DocumentError(str(error)) from error
    else:
        data = {}
    _check_marker(data, path)
    return _split(data, path)


def _load_json_mapping(raw: str, path: Path) -> dict[str, Any]:
    """Parse a ``.json`` file under JSON's own grammar, duplicates refused.

    The reader cannot delegate to YAML here: ``json.dumps(9.0e24)`` writes
    ``9e+24``, a valid JSON number that YAML 1.1 would resolve as text;
    a nesting overflow is a file-naming refusal.
    """

    def pairs_to_mapping(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key, value in pairs:
            if key in mapping:
                raise RegistryError(
                    f"invalid JSON in {path}: found duplicate key {key!r}"
                )
            mapping[key] = value
        return mapping

    try:
        data = json.loads(raw, object_pairs_hook=pairs_to_mapping)
    except json.JSONDecodeError as error:
        raise RegistryError(f"invalid JSON in {path}: {error}") from error
    except RecursionError:
        raise RegistryError(
            f"invalid JSON in {path}: too deeply nested to parse"
        ) from None
    if not isinstance(data, dict):
        raise RegistryError(f"{path} must contain a JSON mapping")
    return data


def _check_marker(data: dict[str, object], path: Path) -> None:
    """Require the v0.1 marker: the integer ``1``, never a bool or a string.

    ``True`` is an ``int`` in Python, so the type check is exact.
    """
    marker = data.get(_MARKER)
    if marker is None:
        raise DocumentError(
            f"{path}: the schema marker is missing; the supported version is {_VERSION}"
        )
    if type(marker) is not int or marker != _VERSION:
        raise DocumentError(
            f"{path}: unsupported schema {marker!r}; "
            f"the supported version is {_VERSION}"
        )


def _split(data: dict[str, object], path: Path) -> Document:
    values: dict[str, object] = {}
    records: dict[str, object] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise DocumentError(f"{path}: the document has a non-string key {key!r}")
        if key == _MARKER:
            continue
        if key in RECORDS:
            _check_records(key, value, path)
            records[key] = value
            continue
        if key in SECTIONS:
            _check_section(key, value, path)
        values[key] = value
    return Document(values=values, records=records)


def _check_section(section: str, value: object, path: Path) -> None:
    """Reject an annex section the checks could not read."""
    if not isinstance(value, dict):
        raise DocumentError(f"{path}: {section} must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise DocumentError(f"{path}: {section} has a non-string key {key!r}")


def _check_records(section: str, value: object, path: Path) -> None:
    """Reject a records section the checks could not read."""
    if not isinstance(value, list):
        raise DocumentError(f"{path}: {section} must be a list of mappings")
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise DocumentError(f"{path}: {section}[{index}] must be a mapping")
        for key in entry:
            if not isinstance(key, str):
                raise DocumentError(
                    f"{path}: {section}[{index}] has a non-string key {key!r}"
                )


# The reader's own number tags (registry's ``_UniqueKeyLoader``): the writer
# quotes a string exactly when one of these constructs it as a number.
_NUMBER_TAGS = frozenset({"tag:yaml.org,2002:int", "tag:yaml.org,2002:float"})


def _reader_reads_as_number(text: str) -> bool:
    """Whether the reader's own resolvers construct ``text`` as a number.

    Single-sourced from the reader's live resolver table, so the writer's
    quoting and the reader's construction can never drift apart. Only the int
    and float tags are consulted: every bool and null spelling the reader
    still reads as one is already quoted by PyYAML's own dumper.
    """
    table = _UniqueKeyLoader.yaml_implicit_resolvers
    entries: list[tuple[str, re.Pattern[str]]] = [
        *table.get(text[:1], []),
        *table.get(None, []),
    ]
    return any(
        tag in _NUMBER_TAGS and pattern.match(text) is not None
        for tag, pattern in entries
    )


class _DocumentDumper(yaml.SafeDumper):
    """A SafeDumper whose strings survive the document reader unchanged.

    PyYAML's SafeDumper resolves under YAML 1.1, the document reader under the
    1.2 core set: a string like ``2.3e25``, ``1e400`` or ``0o17`` is a plain
    string to the dumper and a number to the reader, so without this override
    it would dump unquoted and silently re-type itself on the next load.
    """

    def represent_str(self, data: str) -> yaml.nodes.ScalarNode:
        node = self.represent_scalar("tag:yaml.org,2002:str", data)
        if _reader_reads_as_number(data):
            node.style = "'"
        return node


# PyYAML's representer lookup goes through the class's own mapping;
# overriding the method alone would leave it pointing at SafeRepresenter's.
_DocumentDumper.add_representer(str, _DocumentDumper.represent_str)


def dump_document_yaml(data: object) -> str:
    """Spell ``data`` as YAML a document file carries: block style, own order.

    ``sort_keys=False`` keeps the caller's key order and the dump ends with
    the trailing newline a file wants. A non-finite float raises
    :class:`ValueError` (the class ``extract`` and ``import-docx`` map to
    exit 2), so the written document is exactly the next load's document.
    """
    _refuse_non_finite(data, frozenset())
    return yaml.dump(data, Dumper=_DocumentDumper, sort_keys=False, allow_unicode=True)


def _refuse_non_finite(value: object, visiting: frozenset[int]) -> None:
    """Refuse a non-finite float anywhere in ``value``, and walk on.

    The reader constructs no float from ``.inf``/``.nan``, so the dumper's
    spelling of one would read back as the *string*: the written document
    would not be the document the load returns. ``visiting`` holds the
    containers on this path, so a cycle (which YAML writes as anchors and the
    reader restores) is walked once, never to a recursion overflow.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite float {value!r} does not round-trip")
    if not isinstance(value, (dict, list, tuple, set, frozenset)):
        return
    if id(value) in visiting:
        return
    nested = visiting | {id(value)}
    if isinstance(value, dict):
        for key, item in value.items():
            _refuse_non_finite(key, nested)
            _refuse_non_finite(item, nested)
    else:
        for item in value:
            _refuse_non_finite(item, nested)
