"""The ``export`` commands and their projections.

Pins the card's bytes, the BOM's shape and digests, both deterministic, and
the exit contract (0 written, 2 bad input with nothing written). The card
mirrors the Form's groupings, the BOM carries every fact.
"""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from gpai_docs import cli
from gpai_docs.documents import Document, load_document
from gpai_docs.export import cyclonedx_bom, cyclonedx_json, hf_card_markdown
from gpai_docs.registry import load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "model-docs-example.yaml"

# The registry ids whose rows span two Form groups: the card quotes such a
# fact under both (Annex XI 1(c) and 2(b), Annex XII 1(c)).
SPANNING_IDS = ("XI.1.1.c", "XI.1.2.b", "XII.1.c")


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["gpai-docs", *argv])
    return cli.main()


# Typer renders its help through rich, which under forced colour styles the
# text into spans; assertions on captured text read it unstyled so they hold
# either way (the same helper test_cli.py carries).
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Captured CLI text without ANSI styling, so assertions read the words."""
    return _ANSI_ESCAPE.sub("", text)


def _digest(value: object) -> str:
    """The documented digest: sha256 of the fact's canonical JSON spelling."""
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _section(document: Document, name: str) -> dict[str, Any]:
    section = document.values[name]
    assert isinstance(section, dict)
    return cast("dict[str, Any]", section)


def _component(bom: dict[str, object]) -> dict[str, Any]:
    (component,) = cast("list[dict[str, Any]]", bom["components"])
    return component


def _card(bom: dict[str, object]) -> dict[str, Any]:
    card = _component(bom)["modelCard"]
    assert isinstance(card, dict)
    return cast("dict[str, Any]", card)


def _properties(bom: dict[str, object]) -> list[dict[str, Any]]:
    properties = _card(bom)["properties"]
    assert isinstance(properties, list)
    return cast("list[dict[str, Any]]", properties)


def _annex_comments(text: str) -> list[str]:
    """The annex ids the card quotes, in order, duplicates kept."""
    return re.findall(r"<!-- annex: ([^ ]+) -->", text)


# --- the Hugging Face card ---


def test_hf_card_of_an_empty_document_is_the_frontmatter_shell() -> None:
    # The projection is total: a document answering nothing produces the
    # frontmatter delimiters alone, never a fabricated title or empty group.
    assert hf_card_markdown(Document(values={}), load()) == "---\n---\n"


def test_hf_card_quotes_the_annex_id_before_the_value_under_its_form_group() -> None:
    # The card's exact bytes for one fact: the Form-group heading, the
    # registry label as the section heading, the `<!-- annex: ... -->`
    # comment immediately before the value, and the value verbatim.
    document = Document(values={"annex_xi": {"intended_tasks": "serve coffee"}})

    assert hf_card_markdown(document, load()) == (
        "---\n"
        "---\n"
        "\n"
        "## Use\n"
        "\n"
        "### Tasks the model is intended to perform\n"
        "\n"
        "<!-- annex: XI.1.1.a -->\n"
        "serve coffee\n"
    )


def test_hf_card_frontmatter_carries_the_document_facts() -> None:
    # The three facts the frontmatter projects: the licence element's text
    # as HF's ``license`` (also a registry fact, so its section rides in the
    # body), and the top-level ``model_name``/``library_name`` keys, which
    # the format's models do not define and the card still projects.
    document = Document(
        values={
            "model_name": "Example Model",
            "library_name": "transformers",
            "annex_xi": {"licence": "MIT"},
        }
    )

    assert hf_card_markdown(document, load()) == (
        "---\n"
        "model_name: Example Model\n"
        "license: MIT\n"
        "library_name: transformers\n"
        "---\n"
        "\n"
        "## Distribution and licenses\n"
        "\n"
        "### Licence\n"
        "\n"
        "<!-- annex: XI.1.1.f -->\n"
        "MIT\n"
    )


def test_hf_card_leaves_out_each_frontmatter_fact_it_does_not_carry() -> None:
    # A fact the card cannot carry as a frontmatter line is left out rather
    # than guessed at: an empty model_name, a non-text library_name and an
    # absent licence all leave the frontmatter empty.
    document = Document(
        values={
            "model_name": "",
            "library_name": 5,
            "annex_xi": {"intended_tasks": "serve coffee"},
        }
    )

    text = hf_card_markdown(document, load())

    assert text.startswith("---\n---\n")
    assert text.splitlines()[:2] == ["---", "---"]
    assert "model_name" not in text
    assert "library_name" not in text
    assert "licence" not in text


def test_hf_card_renders_a_non_text_value_as_a_yaml_block() -> None:
    # A structured element is not prose: it rides as the shared dumper's YAML
    # spelling in a fenced block, in the document's own key order, so the
    # card stays readable and the bytes stay deterministic.
    document = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": 2.5e25,
                    "estimation_method": "extrapolated",
                }
            }
        }
    )

    assert hf_card_markdown(document, load()) == (
        "---\n"
        "---\n"
        "\n"
        "## Computational resources\n"
        "\n"
        "### Computational resources used to train the model\n"
        "\n"
        "<!-- annex: XI.1.2.d -->\n"
        "```yaml\n"
        "training_flop: 2.5e+25\n"
        "estimation_method: extrapolated\n"
        "```\n"
    )


def test_hf_card_spells_a_set_in_its_members_own_sorted_order() -> None:
    # A set fact (reachable through an explicit ``!!set`` tag) must not render
    # in Python's hash-seed-dependent iteration order: {8, 1} iterates 8 before
    # 1 (integer hashing is not randomised), so raw order would fail here.
    members = {8, 1}
    assert list(members) == [8, 1]
    document = Document(values={"annex_xi": {"intended_tasks": members}})

    text = hf_card_markdown(document, load())

    assert text.endswith("<!-- annex: XI.1.1.a -->\n```yaml\n- 1\n- 8\n```\n")


def test_hf_card_orders_nested_sets_and_copies_shared_containers_once() -> None:
    # The ordering reaches nested sets too, and the ordered copy preserves a
    # cycle and a shared container as the dumper's anchors and aliases, so a
    # cyclic fact renders rather than overflowing the walk.
    shared = [1, 2]
    cyclic: dict[str, object] = {"members": {8, 1}, "left": shared, "right": shared}
    cyclic["back"] = cyclic
    document = Document(values={"annex_xi": {"intended_tasks": cyclic}})

    text = hf_card_markdown(document, load())
    block = text.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    restored = yaml.safe_load(block)

    assert "- 1\n- 8\n" in text
    assert restored["members"] == [1, 8]
    assert restored["left"] is restored["right"]
    assert restored["back"] is restored


def test_hf_card_mirrors_the_forms_own_group_order_for_the_example() -> None:
    # Everything the example carries appears under the Form's own grouping
    # order (every one of the eight groups carries at least one fact), and a
    # fact whose rows span two groups is quoted in both.
    registry = load()
    text = hf_card_markdown(load_document(EXAMPLE), registry)
    headings = [line for line in text.splitlines() if line.startswith("## ")]

    assert headings == [
        "## General information",
        "## Model properties",
        "## Distribution and licenses",
        "## Use",
        "## Training process",
        "## Data used for training testing and validation",
        "## Computational resources",
        "## Energy consumption",
    ]
    mapped = [field for field in registry.fields if field.form.rows]
    comments = _annex_comments(text)
    expected: list[str] = []
    for field in mapped:
        groups = {row.partition("/")[0] for row in field.form.rows}
        expected.extend([field.id] * len(groups))
    assert Counter(comments) == Counter(expected)
    assert len(mapped) == 22
    assert len(comments) == 25
    for field_id in SPANNING_IDS:
        assert comments.count(field_id) == 2


def test_hf_card_carries_the_example_values_verbatim() -> None:
    # The card quotes the document, it does not re-type it: the plain text
    # values ride byte for byte, and the structured elements' leaves ride in
    # the fenced YAML block.
    source = load_document(EXAMPLE)
    text = hf_card_markdown(source, load())
    annex_xi = _section(source, "annex_xi")

    for key in (
        "intended_tasks",
        "licence",
        "training_data",
        "evaluation_strategies",
    ):
        value = annex_xi[key]
        if key == "evaluation_strategies":
            # A row-less Section 2 fact is omitted, never quoted.
            assert value not in text
        else:
            assert value in text
    assert "training_flop: 2.5e+25" in text


def test_hf_card_omits_the_row_less_section_2_fields_even_when_carried() -> None:
    # The card mirrors the Form's groupings alone, so the
    # row-less Section 2 conditional fields and the systemic-risk marker
    # itself produce no section and no comment.
    document = Document(
        values={
            "systemic_risk": True,
            "annex_xi": {
                "evaluation_strategies": "criteria and metrics",
                "adversarial_testing": "an internal red team",
                "system_architecture": "an inference gateway",
            },
        }
    )

    text = hf_card_markdown(document, load())

    assert text == "---\n---\n"
    assert "XI.2." not in text


def test_hf_card_refuses_a_non_finite_float() -> None:
    # The shared dumper refuses a non-finite float (its spelling reads back
    # as a string), and the card inherits that refusal rather than writing
    # an unfaithful value.
    document = Document(
        values={
            "annex_xi": {"computational_resources": {"training_flop": float("nan")}}
        }
    )

    with pytest.raises(ValueError, match="does not round-trip"):
        hf_card_markdown(document, load())


def test_hf_card_frontmatter_dumps_through_the_document_dumper() -> None:
    # Frontmatter text is the shared dumper's spelling: a number-like string
    # is quoted so the frontmatter reads back as the string it was written as.
    document = Document(values={"model_name": "2.3e25"})

    assert hf_card_markdown(document, load()).startswith(
        "---\nmodel_name: '2.3e25'\n---\n"
    )


# --- the CycloneDX BOM ---


def test_cyclonedx_bom_of_an_empty_document_is_the_skeleton() -> None:
    # The minimal projection: the BOM header, one machine-learning-model
    # component with the neutral name placeholder, and a modelCard whose only
    # key is the empty properties list.
    assert cyclonedx_bom(Document(values={}), load()) == {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [
            {
                "type": "machine-learning-model",
                "name": "unnamed model",
                "modelCard": {"properties": []},
            }
        ],
    }


def test_cyclonedx_bom_carries_the_annex_id_and_its_short_digest_property() -> None:
    # Traceability, not prose: one property per present fact, its name the
    # `gpai-docs:annex:<id>` namespace and its value the sha256-first-12
    # digest of the fact's canonical JSON spelling, pinned literally for
    # "serve coffee" so a canonicalisation change cannot slip through.
    document = Document(values={"annex_xi": {"intended_tasks": "serve coffee"}})

    assert _component(cyclonedx_bom(document, load())) == {
        "type": "machine-learning-model",
        "name": "unnamed model",
        "modelCard": {
            "properties": [
                {"name": "gpai-docs:annex:XI.1.1.a", "value": "e7663a81cfe5"}
            ]
        },
    }
    assert _digest("serve coffee") == "e7663a81cfe5"


def test_cyclonedx_bom_digests_a_structured_value_canonically() -> None:
    # A mapping digests through the same canonical spelling: compact JSON,
    # sorted keys, so equal facts digest equally whatever their key order.
    document = Document(
        values={"annex_xi": {"computational_resources": {"training_flop": 2.5e25}}}
    )

    assert _properties(cyclonedx_bom(document, load())) == [
        {"name": "gpai-docs:annex:XI.1.2.d", "value": "35c905d83f61"}
    ]
    assert _digest({"training_flop": 2.5e25}) == "35c905d83f61"


def test_cyclonedx_bom_projects_the_numeric_facts_and_the_stated_licence() -> None:
    # The component carries the model's own name, the stated licence as a
    # named licence, and inside modelParameters (CycloneDX 1.6's own home for
    # both) the numeric architecture fact and the training-data text as a
    # description-only dataset, with the digest properties in registry order.
    document = Document(
        values={
            "model_name": "Example Model",
            "annex_xi": {
                "architecture_and_parameters": 70000000000,
                "licence": "MIT",
                "training_data": "web text",
            },
        }
    )

    assert _component(cyclonedx_bom(document, load())) == {
        "type": "machine-learning-model",
        "name": "Example Model",
        "licenses": [{"license": {"name": "MIT"}}],
        "modelCard": {
            "modelParameters": {
                "modelArchitecture": "70000000000",
                "datasets": [{"type": "dataset", "description": "web text"}],
            },
            "properties": [
                {"name": "gpai-docs:annex:XI.1.1.d", "value": "ee2d2245a673"},
                {"name": "gpai-docs:annex:XI.1.1.f", "value": "529fc91e3f97"},
                {"name": "gpai-docs:annex:XI.1.2.c", "value": _digest("web text")},
            ],
        },
    }
    assert _digest(70000000000) == "ee2d2245a673"
    assert _digest("MIT") == "529fc91e3f97"


def test_cyclonedx_bom_falls_back_to_the_annex_xii_twin_facts() -> None:
    # A document carrying only the downstream set still projects: the first
    # present fact in registry order wins, Annex XI before its Annex XII
    # twin, and the property names carry the ids that produced them.
    document = Document(
        values={
            "annex_xii": {
                "architecture_and_parameters": 5,
                "licence": "MIT",
                "training_data": "the downstream data note",
            }
        }
    )

    bom = cyclonedx_bom(document, load())
    component = _component(bom)

    assert component["licenses"] == [{"license": {"name": "MIT"}}]
    assert component["modelCard"]["modelParameters"] == {
        "modelArchitecture": "5",
        "datasets": [{"type": "dataset", "description": "the downstream data note"}],
    }
    assert [entry["name"] for entry in _properties(bom)] == [
        "gpai-docs:annex:XII.1.f",
        "gpai-docs:annex:XII.1.h",
        "gpai-docs:annex:XII.2.c",
    ]


def test_the_numeric_fact_falls_through_a_prose_twin_to_the_annex_xii_number() -> None:
    # Symmetry with the licence and dataset facts: a numeric Annex XI fact
    # wins, but a prose Annex XI fact does not end the search (a numeric
    # Annex XII twin still rides modelParameters), and nothing numeric on
    # either side omits the entry.
    mixed = Document(
        values={
            "annex_xi": {"architecture_and_parameters": "a transformer"},
            "annex_xii": {"architecture_and_parameters": 5},
        }
    )
    both_numeric = Document(
        values={
            "annex_xi": {"architecture_and_parameters": 7},
            "annex_xii": {"architecture_and_parameters": 5},
        }
    )
    both_prose = Document(
        values={
            "annex_xi": {"architecture_and_parameters": "a transformer"},
            "annex_xii": {"architecture_and_parameters": "a decoder"},
        }
    )

    assert _card(cyclonedx_bom(mixed, load()))["modelParameters"] == {
        "modelArchitecture": "5"
    }
    assert _card(cyclonedx_bom(both_numeric, load()))["modelParameters"] == {
        "modelArchitecture": "7"
    }
    assert "modelParameters" not in _card(cyclonedx_bom(both_prose, load()))


def test_cyclonedx_bom_carries_the_row_less_section_2_fields_when_present() -> None:
    # The BOM's flat property list has no grouping
    # constraint, so a present row-less fact rides it like any other; the
    # card, mirroring the Form's groupings, still omits them (pinned above).
    document = Document(
        values={
            "systemic_risk": True,
            "annex_xi": {
                "evaluation_strategies": "criteria and metrics",
                "adversarial_testing": "an internal red team",
                "system_architecture": "an inference gateway",
            },
        }
    )

    assert _properties(cyclonedx_bom(document, load())) == [
        {"name": "gpai-docs:annex:XI.2.1", "value": _digest("criteria and metrics")},
        {"name": "gpai-docs:annex:XI.2.2", "value": _digest("an internal red team")},
        {"name": "gpai-docs:annex:XI.2.3", "value": _digest("an inference gateway")},
    ]


def test_cyclonedx_bom_carries_row_less_facts_without_the_marker() -> None:
    # Presence, not the condition, drives the property list (values may be
    # provided early): the systemic_risk marker gates the completeness pass,
    # never the projection.
    document = Document(values={"annex_xi": {"evaluation_strategies": "criteria"}})

    assert _properties(cyclonedx_bom(document, load())) == [
        {"name": "gpai-docs:annex:XI.2.1", "value": _digest("criteria")}
    ]


def test_the_prose_architecture_fact_yields_no_model_parameters() -> None:
    # The architecture fact feeds modelParameters only when it is a number:
    # the typed format's shape is prose, never parsed or guessed, so a prose
    # (or boolean) architecture fact adds no parameter entry at all.
    prose = Document(
        values={"annex_xi": {"architecture_and_parameters": "a transformer"}}
    )
    boolean = Document(values={"annex_xi": {"architecture_and_parameters": True}})

    assert "modelParameters" not in _card(cyclonedx_bom(prose, load()))
    assert "modelParameters" not in _card(cyclonedx_bom(boolean, load()))


def test_the_example_document_projects_every_present_fact() -> None:
    # The complete example: every registry field carries a value (22
    # Form-mapped facts and three row-less Section 2 facts), so every field
    # becomes a digest property in registry order; the licence and dataset
    # come from the Annex XI facts, and the name is the placeholder.
    registry = load()
    document = load_document(EXAMPLE)
    bom = cyclonedx_bom(document, registry)
    component = _component(bom)
    card = _card(bom)
    annex_xi = _section(document, "annex_xi")

    assert [entry["name"] for entry in _properties(bom)] == [
        f"gpai-docs:annex:{field.id}" for field in registry.fields
    ]
    assert len(registry.fields) == 25
    assert component["licenses"] == [{"license": {"name": annex_xi["licence"]}}]
    assert card["modelParameters"] == {
        "datasets": [{"type": "dataset", "description": annex_xi["training_data"]}]
    }
    assert "modelArchitecture" not in card["modelParameters"]
    assert component["name"] == "unnamed model"


def test_the_two_exports_quote_the_same_ids() -> None:
    # The exports are two renderings of one projection:
    # the BOM's properties name every present fact, and the card's comments
    # are exactly the Form-mapped ids among them, the row-less Section 2
    # facts riding the BOM's flat property list alone.
    registry = load()
    document = load_document(EXAMPLE)
    card = hf_card_markdown(document, registry)
    bom = cyclonedx_bom(document, registry)
    ids = [entry["name"].removeprefix("gpai-docs:annex:") for entry in _properties(bom)]
    row_less = {field.id for field in registry.fields if not field.form.rows}

    assert row_less == {"XI.2.1", "XI.2.2", "XI.2.3"}
    assert row_less <= set(ids)
    assert set(_annex_comments(card)) == set(ids) - row_less


def test_cyclonedx_json_spells_the_bom_once_and_deterministically() -> None:
    # The writer's contract: the shared refusal walk, indent 2, one trailing
    # newline, and two runs over the same document producing byte-equal text.
    registry = load()
    first = cyclonedx_json(cyclonedx_bom(load_document(EXAMPLE), registry))
    second = cyclonedx_json(cyclonedx_bom(load_document(EXAMPLE), registry))

    assert first == second
    assert first == json.dumps(json.loads(first), indent=2) + "\n"
    assert first.endswith("\n") and not first.endswith("\n\n")


# The shapes the CycloneDX projection must refuse because JSON cannot carry
# them, each as (document text, the cause the refusal names). The walk is the
# extract twin's, imported as-is.
NON_JSON_CASES = [
    pytest.param(
        "schema: 1\nannex_xi:\n  licence: !!binary aGk=\n",
        "Object of type bytes is not JSON serializable",
        id="tagged-bytes",
    ),
    pytest.param(
        "schema: 1\nannex_xi:\n  intended_tasks:\n    - 1: x\n",
        "non-string key 1 cannot be written as JSON",
        id="non-string-key",
    ),
    pytest.param(
        # The cycle carries a leaf, so the fact is present (a leaf-less
        # mapping is an absence to the completeness reading) and the walk
        # meets its own path.
        "schema: 1\nannex_xi:\n  intended_tasks: &x\n    back: *x\n    note: text\n",
        "circular reference cannot be written as JSON",
        id="cycle",
    ),
    pytest.param(
        # The JSON twin's walk deliberately leaves a date to json.dumps's
        # own refusal (the YAML twin is the one that refuses it itself), so
        # the cause is that refusal's, exactly as extract's JSON twin has it.
        "schema: 1\nannex_xi:\n  licence: !!timestamp 2026-05-05\n",
        "Object of type date is not JSON serializable",
        id="date",
    ),
    pytest.param(
        # The row-less facts join the same walk: a
        # present Section-2 value JSON cannot carry refuses like any other
        # fact.
        "schema: 1\nannex_xi:\n  adversarial_testing: !!timestamp 2026-05-05\n",
        "Object of type date is not JSON serializable",
        id="row-less-date",
    ),
    pytest.param(
        "schema: 1\nannex_xi:\n  licence: 1e400\n",
        "non-finite float inf does not round-trip",
        id="non-finite",
    ),
]


@pytest.mark.parametrize(("content", "cause"), NON_JSON_CASES)
def test_cyclonedx_refuses_non_json_native_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    content: str,
    cause: str,
) -> None:
    # Exit 2, one line naming the document and the cause, stdout clean, and
    # nothing written, so a pre-existing target keeps its bytes.
    document = tmp_path / "document.yaml"
    document.write_text(content, encoding="utf-8")
    target = tmp_path / "bom.json"
    target.write_bytes(b"previous bytes")

    code = _run(monkeypatch, ["export", "cyclonedx", str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith(
        "gpai-docs: error: cannot write the CycloneDX BOM of "
    )
    assert str(document) in captured.err
    assert cause in captured.err
    assert target.read_bytes() == b"previous bytes"

    code = _run(monkeypatch, ["export", "cyclonedx", str(document)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert cause in captured.err


def test_hf_card_refuses_a_non_finite_float_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The card's one refusal class, through the command: exit 2, one line,
    # nothing on stdout, a pre-existing -o target untouched.
    document = tmp_path / "document.yaml"
    document.write_text("schema: 1\nannex_xi:\n  licence: 1e400\n", encoding="utf-8")
    target = tmp_path / "README.md"
    target.write_bytes(b"previous bytes")

    code = _run(monkeypatch, ["export", "hf-card", str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert str(document) in captured.err
    assert "non-finite float inf does not round-trip" in captured.err
    assert target.read_bytes() == b"previous bytes"


# --- the commands end to end ---


def test_the_export_commands_are_registered_with_their_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The sub-typer is on the app's surface and names both commands; each
    # help spells its usage and its exit contract, the way extract's does.
    assert _run(monkeypatch, ["--help"]) == 0
    listed = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "export" in listed

    assert _run(monkeypatch, ["export", "--help"]) == 0
    sub = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "hf-card" in sub and "cyclonedx" in sub

    assert _run(monkeypatch, ["export", "hf-card", "--help"]) == 0
    card_help = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "hf-card [OPTIONS] {document}" in card_help
    assert "-o" in card_help
    assert "Exit codes: 0 card written, 2 bad input" in card_help

    assert _run(monkeypatch, ["export", "cyclonedx", "--help"]) == 0
    bom_help = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "cyclonedx [OPTIONS] {document}" in bom_help
    assert "-o" in bom_help
    assert "Exit codes: 0 BOM written, 2 bad input" in bom_help


def test_hf_card_stdout_is_deterministic_and_out_moves_the_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # Two runs, byte-identical bytes on stdout; ``-o -`` names stdout too;
    # an -o file carries exactly those bytes with stdout left clean.
    assert _run(monkeypatch, ["export", "hf-card", str(EXAMPLE)]) == 0
    first = capsysbinary.readouterr()
    assert _run(monkeypatch, ["export", "hf-card", str(EXAMPLE)]) == 0
    second = capsysbinary.readouterr()

    assert first.err == b"" and second.err == b""
    assert first.out == second.out
    assert first.out.decode("utf-8") == hf_card_markdown(load_document(EXAMPLE), load())

    assert _run(monkeypatch, ["export", "hf-card", str(EXAMPLE), "-o", "-"]) == 0
    dashed = capsysbinary.readouterr()
    assert dashed.out == first.out and dashed.err == b""

    target = tmp_path / "README.md"
    assert (
        _run(monkeypatch, ["export", "hf-card", str(EXAMPLE), "-o", str(target)]) == 0
    )
    captured = capsysbinary.readouterr()

    assert captured.out == b"" and captured.err == b""
    assert target.read_bytes() == first.out


def test_cyclonedx_stdout_is_deterministic_json_and_out_moves_the_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # The JSON default: valid JSON, indent 2, one trailing newline, two runs
    # byte-equal; ``-o`` moves the same bytes to a file whatever its suffix.
    assert _run(monkeypatch, ["export", "cyclonedx", str(EXAMPLE)]) == 0
    first = capsysbinary.readouterr()
    assert _run(monkeypatch, ["export", "cyclonedx", str(EXAMPLE)]) == 0
    second = capsysbinary.readouterr()

    assert first.err == b"" and second.err == b""
    assert first.out == second.out
    text = first.out.decode("utf-8")
    assert text == json.dumps(json.loads(text), indent=2) + "\n"
    assert json.loads(text) == cyclonedx_bom(load_document(EXAMPLE), load())

    target = tmp_path / "bom.data"
    assert (
        _run(monkeypatch, ["export", "cyclonedx", str(EXAMPLE), "-o", str(target)]) == 0
    )
    captured = capsysbinary.readouterr()

    assert captured.out == b"" and captured.err == b""
    assert target.read_bytes() == first.out


@pytest.mark.parametrize("command", [["export", "hf-card"], ["export", "cyclonedx"]])
@pytest.mark.parametrize(
    "content",
    [
        None,
        "annex_xi:\n  licence: MIT\n",
        "schema: 1\nannex_xi: [licence]\n",
    ],
)
def test_export_maps_a_bad_document_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: list[str],
    content: str | None,
) -> None:
    # The loader's own refusals are bad input (2) in the shared error style:
    # a missing file, a file without the marker, a section that is not a
    # mapping. Nothing is written for any of them.
    document = tmp_path / "bad.yaml"
    if content is not None:
        document.write_text(content, encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    target = outdir / "out.txt"

    code = _run(monkeypatch, [*command, str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: ")
    assert list(outdir.iterdir()) == []


@pytest.mark.parametrize("command", [["export", "hf-card"], ["export", "cyclonedx"]])
@pytest.mark.parametrize("case", ["directory", "missing-parent"])
def test_export_maps_an_unwritable_out_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: list[str],
    case: str,
) -> None:
    # An -o the process cannot write is bad input (2), mirroring the schema
    # and extract commands' one-liner: a directory and a missing parent are
    # the two deterministic cases.
    target = tmp_path if case == "directory" else tmp_path / "absent" / "out"

    code = _run(monkeypatch, [*command, str(EXAMPLE), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: cannot write ")
    assert str(target) in captured.err


def test_the_card_frontmatter_parses_as_the_facts_mapping() -> None:
    # A last shape pin on the bytes: the frontmatter between the delimiters
    # is a real YAML mapping, and every comment in the body is exactly the
    # annex-id traceability comment.
    document = Document(
        values={"model_name": "Example Model", "annex_xi": {"licence": "MIT"}}
    )
    text = hf_card_markdown(document, load())
    front, _, body = text.removeprefix("---\n").partition("\n---\n")

    assert yaml.safe_load(front) == {"model_name": "Example Model", "license": "MIT"}
    comments = [line for line in body.splitlines() if "<!--" in line]
    assert comments
    assert all(re.fullmatch(r"<!-- annex: \S+ -->", line) for line in comments)
