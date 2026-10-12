"""The Annex XII subset projection.

The projection is total: a document without the section projects empty, and
the command refuses that, exit 1. Both renderers refuse content the reader
would read back differently, so a subset always reloads as what it is.
"""

from __future__ import annotations

import datetime
import json
import math
from typing import TYPE_CHECKING

from gpai_docs.documents import dump_document_yaml

if TYPE_CHECKING:
    from gpai_docs.documents import Document

__all__ = ["annex_xii_subset", "subset_json", "subset_yaml"]


def annex_xii_subset(document: Document) -> dict[str, object]:
    """Project ``document`` to ``{"schema": 1, "annex_xii": {...}}``.

    The section rides through verbatim in the document's own key order, as a
    copy, so a caller can never write back into the document; a document
    without one projects to an empty mapping.
    """
    section = document.values.get("annex_xii")
    mapping: dict[str, object] = dict(section) if isinstance(section, dict) else {}
    return {"schema": 1, "annex_xii": mapping}


def subset_yaml(subset: dict[str, object]) -> str:
    """The YAML spelling of ``subset``: block style, insertion order kept.

    The shared dumper quotes anything the reader's grammar would construct as
    a number, and a non-finite float or a date is refused because the reader
    would read its spelling back as text.
    """
    _refuse_unwritable(subset, frozenset(), json_twin=False)
    return dump_document_yaml(subset)


def subset_json(subset: dict[str, object]) -> str:
    """The JSON twin of ``subset``: indent 2, one trailing newline.

    The walk refuses what JSON cannot write natively - a non-string key, a
    cycle - and the YAML twin's refusals; ``json.dumps`` keeps its own guards
    behind it.
    """
    _refuse_unwritable(subset, frozenset(), json_twin=True)
    return json.dumps(subset, indent=2, allow_nan=False) + "\n"


def _refuse_unwritable(
    value: object, visiting: frozenset[int], *, json_twin: bool
) -> None:
    """Refuse content the requested twin cannot write faithfully, and walk on.

    Both twins refuse a non-finite float (JSON has no spelling for one; the
    YAML ``.inf``/``.nan`` reads back as a *string*). The YAML twin refuses a
    date the same way; the JSON twin refuses a non-string key and a cycle,
    and walks tuples and sets an explicit tag built. ``visiting`` holds the
    containers on this path, so a container shared between two keys is no
    cycle.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite float {value!r} does not round-trip")
    if not json_twin and isinstance(value, datetime.date):
        raise ValueError(f"date {value.isoformat()} does not round-trip")
    if not isinstance(value, (dict, list, tuple, set, frozenset)):
        return
    if id(value) in visiting:
        if json_twin:
            raise TypeError("circular reference cannot be written as JSON")
        return
    nested = visiting | {id(value)}
    if isinstance(value, dict):
        for key, item in value.items():
            if json_twin and not isinstance(key, str):
                raise TypeError(f"non-string key {key!r} cannot be written as JSON")
            _refuse_unwritable(key, nested, json_twin=json_twin)
            _refuse_unwritable(item, nested, json_twin=json_twin)
    else:
        for item in value:
            _refuse_unwritable(item, nested, json_twin=json_twin)
