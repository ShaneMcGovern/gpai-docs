"""The exchange-format projections of a native document.

The card and BOM rules, and the digest the BOM properties carry, are the
methodology's story (docs/methodology.md, "The exchange-format projections").
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from gpai_docs.documents import dump_document_yaml
from gpai_docs.extract import _refuse_unwritable
from gpai_docs.lint.completeness import _absent, _resolve

if TYPE_CHECKING:
    from gpai_docs.documents import Document
    from gpai_docs.registry import Registry

__all__ = ["cyclonedx_bom", "cyclonedx_json", "hf_card_markdown"]

# The top-level document facts the frontmatter and the component name read.
# Neither is a format field - the Form's model-name row is deliberately not
# an element - so a document carrying one draws an unknown finding; the
# exporter still projects the fact (HF's own vocabulary) and invents none.
_MODEL_NAME = "model_name"
_LIBRARY_NAME = "library_name"

# The twin element paths behind the BOM's single slots and the card's
# frontmatter licence, in registry order (Annex XI first, its Annex XII twin
# as the fallback).
_LICENCE_FIELDS = ("annex_xi.licence", "annex_xii.licence")
_TRAINING_DATA_FIELDS = ("annex_xi.training_data", "annex_xii.training_data")
_ARCHITECTURE_FIELDS = (
    "annex_xi.architecture_and_parameters",
    "annex_xii.architecture_and_parameters",
)


def hf_card_markdown(document: Document, registry: Registry) -> str:
    """Render the Hugging Face-style model card of ``document``.

    The card's rules are the methodology's (docs/methodology.md, "The
    exchange-format projections").
    """
    head = _frontmatter(document)
    facts = dict(_facts(document, registry))
    blocks: list[str] = []
    for prefix in _form_groups(registry):
        identifiers = [
            identifier
            for identifier in facts
            if prefix in _groups(registry.by_id[identifier].form.rows)
        ]
        if not identifiers:
            continue
        blocks.append(f"## {_heading(prefix)}")
        for identifier in identifiers:
            row = registry.by_id[identifier]
            blocks.append(
                f"### {row.label}\n\n"
                f"<!-- annex: {identifier} -->\n{_render(facts[identifier])}"
            )
    body = "\n\n".join(blocks)
    return head + (f"\n{body}\n" if body else "")


def cyclonedx_bom(document: Document, registry: Registry) -> dict[str, object]:
    """Project ``document`` to a CycloneDX 1.6 BOM with one modelCard component.

    The BOM's rules, the row-less fields included, are the methodology's
    (docs/methodology.md, "The exchange-format projections").
    """
    facts = _facts(document, registry, row_less=True)
    for _, value in facts:
        _refuse_unwritable(value, frozenset(), json_twin=True)
    component: dict[str, object] = {
        "type": "machine-learning-model",
        "name": _model_name(document),
    }
    licence = _text_fact(document, _LICENCE_FIELDS)
    if licence is not None:
        component["licenses"] = [{"license": {"name": licence}}]
    card: dict[str, object] = {}
    parameters: dict[str, object] = {}
    architecture = _numeric_fact(document, _ARCHITECTURE_FIELDS)
    if architecture is not None:
        # CycloneDX types every modelParameters member as text or an array,
        # so the number rides modelArchitecture spelled as text.
        parameters["modelArchitecture"] = _canonical(architecture)
    training_data = _text_fact(document, _TRAINING_DATA_FIELDS)
    if training_data is not None:
        # A description-only entry: the document's own text under the
        # schema's required structural classification, nothing fabricated.
        parameters["datasets"] = [{"type": "dataset", "description": training_data}]
    if parameters:
        card["modelParameters"] = parameters
    card["properties"] = [
        {"name": f"gpai-docs:annex:{identifier}", "value": _digest(value)}
        for identifier, value in facts
    ]
    component["modelCard"] = card
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [component],
    }


def cyclonedx_json(bom: dict[str, object]) -> str:
    """The JSON spelling of ``bom``: indent 2, one trailing newline.

    The shared refusal walk runs first, as in the extract twin, so this
    writer never spells content it could not write faithfully.
    """
    _refuse_unwritable(bom, frozenset(), json_twin=True)
    return json.dumps(bom, indent=2, allow_nan=False) + "\n"


def _facts(
    document: Document, registry: Registry, *, row_less: bool = False
) -> list[tuple[str, object]]:
    """Every present fact the projection covers, in registry order.

    Form-mapped fields always; ``row_less`` adds the fields with no Form
    rows, which the BOM carries and the card does not.
    Presence is the completeness pass's reading.
    """
    facts: list[tuple[str, object]] = []
    for field in registry.fields:
        if not field.form.rows and not row_less:
            continue
        value = _resolve(document, field.model_field)
        if _absent(value):
            continue
        facts.append((field.id, value))
    return facts


def _form_groups(registry: Registry) -> list[str]:
    """The Form's group prefixes, in the order form.yaml publishes them."""
    groups: list[str] = []
    for row in registry.form.rows:
        prefix = row.row.partition("/")[0]
        if prefix not in groups:
            groups.append(prefix)
    return groups


def _groups(rows: list[str]) -> list[str]:
    """The Form groups a field's rows live under, in first-seen order."""
    groups: list[str] = []
    for row in rows:
        prefix = row.partition("/")[0]
        if prefix not in groups:
            groups.append(prefix)
    return groups


def _heading(prefix: str) -> str:
    return prefix.replace("-", " ").capitalize()


def _render(value: object) -> str:
    """One fact as prose: text verbatim, anything else a fenced YAML block.

    A trailing newline run on text is trimmed at the block boundary, and any
    other value goes through :func:`_ordered` so a set reaches the dumper in
    a fixed order.
    """
    if isinstance(value, str):
        return value.rstrip("\n")
    return f"```yaml\n{dump_document_yaml(_ordered(value, {}))}```"


def _ordered(value: object, copied: dict[int, object]) -> object:
    """``value`` with every unordered container spelled in a fixed order.

    Python iterates a set in its hash table's order - for strings, the
    process hash seed - and the YAML spelling follows it, so a set fact (an
    explicit ``!!set`` tag) would make the card's bytes run-dependent. Every
    set is copied to a list of its members in sorted YAML spelling;
    ``copied`` remembers the containers copied on this walk, so a cycle the
    reader restored is copied once, with the cycle preserved.
    """
    if not isinstance(value, (dict, list, tuple, set, frozenset)):
        return value
    if id(value) in copied:
        return copied[id(value)]
    if isinstance(value, (set, frozenset)):
        ordered = sorted(
            (_ordered(item, copied) for item in value), key=dump_document_yaml
        )
        copied[id(value)] = ordered
        return ordered
    if isinstance(value, dict):
        mapping: dict[object, object] = {}
        copied[id(value)] = mapping
        for key, item in value.items():
            mapping[key] = _ordered(item, copied)
        return mapping
    listed: list[object] = []
    copied[id(value)] = listed
    for item in value:
        listed.append(_ordered(item, copied))
    return listed


def _frontmatter(document: Document) -> str:
    """The card's frontmatter shell: the facts the document actually carries."""
    facts: dict[str, str] = {}
    model_name = _document_fact(document, _MODEL_NAME)
    if model_name is not None:
        facts[_MODEL_NAME] = model_name
    licence = _text_fact(document, _LICENCE_FIELDS)
    if licence is not None:
        facts["license"] = licence
    library_name = _document_fact(document, _LIBRARY_NAME)
    if library_name is not None:
        facts[_LIBRARY_NAME] = library_name
    dumped = dump_document_yaml(facts) if facts else ""
    return f"---\n{dumped}---\n"


def _document_fact(document: Document, key: str) -> str | None:
    """A top-level document fact, when it is non-empty text."""
    value = document.values.get(key)
    if isinstance(value, str) and value != "":
        return value
    return None


def _numeric_fact(document: Document, paths: tuple[str, ...]) -> int | float | None:
    """The first numeric fact among ``paths`` (registry order), or ``None``.

    ``None`` covers both "no present fact" and "present but not a number".
    The typed format spells both facts as text, so this serves only the lossy
    reading of a document lint would call malformed; prose is never parsed.
    """
    for path in paths:
        value = _resolve(document, path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _text_fact(document: Document, paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = _resolve(document, path)
        if isinstance(value, str) and value != "":
            return value
    return None


def _model_name(document: Document) -> str:
    """The component's name: the document's own fact, or the placeholder.

    CycloneDX requires a name and the exporter invents no identifier, so an
    unnamed document gets a neutral structural placeholder.
    """
    name = _document_fact(document, _MODEL_NAME)
    return name if name is not None else "unnamed model"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:12]
