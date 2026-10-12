"""The document loader's structural checks.

Shapes only: the marker exactly the integer ``1``, annex sections mappings,
records sections lists of string-keyed mappings; violations
are :class:`DocumentError`, and values ride through raw for the typed pass.
"""

from pathlib import Path

import pytest

from gpai_docs.documents import Document, DocumentError, load_document
from gpai_docs.lint import lint
from gpai_docs.registry import load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "model-docs-example.yaml"


def _entries(document: Document, section: str) -> dict[str, object]:
    """The raw entries of one annex section the loader guaranteed a mapping."""
    entries = document.values[section]
    assert isinstance(entries, dict)
    return entries


def test_load_document_reads_the_example_fixture() -> None:
    document = load_document(EXAMPLE)

    assert set(document.values) == {"annex_xi", "annex_xii"}
    annex_xi = _entries(document, "annex_xi")
    tasks = annex_xi["intended_tasks"]
    assert isinstance(tasks, str)
    assert tasks.startswith("Text-to-text")
    # Annex XI's eleven Section 1 points and three Section 2 items; the
    # Section 2 values ride present while the marker is absent (providing them
    # early is no finding), so this fixture is a complete document.
    assert len(annex_xi) == 14
    assert len(_entries(document, "annex_xii")) == 11
    # The two structured elements are mappings, not prose.
    assert isinstance(annex_xi["computational_resources"], dict)
    assert isinstance(annex_xi["energy_consumption"], dict)
    # `schema` is not surfaced, and the example carries its records demo: one
    # Art. 52(1) notification record, its dates read as the strings the
    # format's date leaf accepts.
    assert document.records == {
        "notifications": [
            {
                "compute_flop": 2.5e25,
                "estimation_method": (
                    "Extrapolated from the provider's published training "
                    "report; no measured figure was released."
                ),
                "aware_on": "2026-04-20",
                "notified_on": "2026-04-30",
            }
        ]
    }


def test_load_document_accepts_the_integer_one_marker(tmp_path: Path) -> None:
    path = tmp_path / "marker.yaml"
    path.write_text(
        "schema: 1\nannex_xi:\n  intended_tasks: the tasks\n", encoding="utf-8"
    )

    assert load_document(path) == Document(
        values={"annex_xi": {"intended_tasks": "the tasks"}}
    )


@pytest.mark.parametrize(
    "shape",
    ["annex_xi:\n  - intended_tasks\n", "notifications: {}\n"],
    ids=["annex", "records"],
)
def test_the_marker_is_checked_before_the_shape_checks(
    tmp_path: Path, shape: str
) -> None:
    # A file with both faults reports the version refusal: the marker says
    # how to read the file, so it cannot be read far enough to
    # judge its annex and records shapes.
    path = tmp_path / "both.yaml"
    path.write_text(f"schema: 0\n{shape}", encoding="utf-8")

    with pytest.raises(DocumentError, match="unsupported schema 0"):
        load_document(path)


@pytest.mark.parametrize(
    ("marker", "shown"),
    [(0, "0"), ('"1"', "'1'"), (2, "2"), ("true", "True"), ("1.0", "1.0")],
    ids=["zero", "quoted-one", "two", "bool", "float-one"],
)
def test_load_document_refuses_a_marker_other_than_the_integer_one(
    tmp_path: Path, marker: str, shown: str
) -> None:
    # A bool is an int in Python, so the check is an exact type check; the
    # message names the file, the offending value and the supported version.
    path = tmp_path / "marker.yaml"
    path.write_text(f"schema: {marker}\n", encoding="utf-8")

    with pytest.raises(DocumentError) as excinfo:
        load_document(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert f"unsupported schema {shown}" in message
    assert "the supported version is 1" in message


@pytest.mark.parametrize(
    "text",
    ["annex_xi: {}\n", "schema:\n", "", "\n   \n"],
    ids=["absent", "null", "empty-file", "blank-file"],
)
def test_load_document_refuses_a_missing_marker(tmp_path: Path, text: str) -> None:
    # An empty or blank file has no marker, so the marker rule refuses it
    # rather than reading it as an empty document.
    path = tmp_path / "marker.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(DocumentError) as excinfo:
        load_document(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "the schema marker is missing" in message
    assert "the supported version is 1" in message


@pytest.mark.parametrize("section", ["notifications", "modifications"])
def test_load_document_accepts_an_empty_records_list(
    tmp_path: Path, section: str
) -> None:
    # The empty list is a valid records section, carried as such: absence is
    # the key not being there, and the text-list reading of the empty list
    # is a field-value rule, not the sections'.
    path = tmp_path / "records.yaml"
    path.write_text(f"schema: 1\n{section}: []\n", encoding="utf-8")

    assert load_document(path).records == {section: []}


@pytest.mark.parametrize("section", ["notifications", "modifications"])
@pytest.mark.parametrize("value", ["{}", "the records"], ids=["mapping", "scalar"])
def test_load_document_rejects_a_records_section_that_is_not_a_list(
    tmp_path: Path, section: str, value: str
) -> None:
    path = tmp_path / "records.yaml"
    path.write_text(f"schema: 1\n{section}: {value}\n", encoding="utf-8")

    with pytest.raises(DocumentError, match=rf"{section} must be a list of mappings"):
        load_document(path)


@pytest.mark.parametrize("section", ["notifications", "modifications"])
@pytest.mark.parametrize("entry", ["1", "[1, 2]"], ids=["scalar", "list"])
def test_load_document_rejects_a_records_entry_that_is_not_a_mapping(
    tmp_path: Path, section: str, entry: str
) -> None:
    path = tmp_path / "records.yaml"
    path.write_text(f"schema: 1\n{section}:\n  - {entry}\n", encoding="utf-8")

    with pytest.raises(DocumentError, match=rf"{section}\[0\] must be a mapping"):
        load_document(path)


@pytest.mark.parametrize("section", ["notifications", "modifications"])
def test_load_document_rejects_a_non_string_records_entry_key(
    tmp_path: Path, section: str
) -> None:
    path = tmp_path / "records.yaml"
    path.write_text(f"schema: 1\n{section}:\n  - 1: text\n", encoding="utf-8")

    with pytest.raises(DocumentError, match=rf"{section}\[0\] has a non-string key 1"):
        load_document(path)


def test_load_document_rides_record_values_through_unread(tmp_path: Path) -> None:
    # The loader checks only the sections' shapes; ill-typed
    # values inside entries are the typed pass's findings, not exit 2.
    path = tmp_path / "records.yaml"
    path.write_text(
        "schema: 1\n"
        "notifications:\n"
        "  - compute_flop: lots\n"
        "    extra_key: null\n"
        "modifications:\n"
        "  - provider_record: 'true'\n",
        encoding="utf-8",
    )

    document = load_document(path)

    assert document.records == {
        "notifications": [{"compute_flop": "lots", "extra_key": None}],
        "modifications": [{"provider_record": "true"}],
    }


def test_load_document_reads_a_json_file_and_json_content_alike(
    tmp_path: Path,
) -> None:
    # A .json file parses under JSON's own grammar and JSON content in a
    # .yaml file under the YAML reader; the two readers
    # agree on content both grammars spell the same way.
    text = (
        '{"schema": 1, "annex_xi": {"intended_tasks": "the tasks"}, '
        '"notifications": [{"notified_on": "2026-07-30"}]}'
    )
    as_json = tmp_path / "document.json"
    as_json.write_text(text, encoding="utf-8")
    as_yaml = tmp_path / "document.yaml"
    as_yaml.write_text(text, encoding="utf-8")

    assert load_document(as_json) == load_document(as_yaml)
    assert load_document(as_json).records == {
        "notifications": [{"notified_on": "2026-07-30"}]
    }


def test_a_dotless_exponent_is_a_number_in_both_readers(tmp_path: Path) -> None:
    # `json.dumps(9.0e24)` writes `9e+24`, and both readers must read it as a
    # number: JSON under its own grammar, YAML under the 1.2 core
    # float resolver. The estimation method accompanies the
    # compute so the consistency pass adds nothing under the element either.
    text = (
        '{"schema": 1, "annex_xi": {"computational_resources": '
        '{"training_flop": 9e+24, "estimation_method": "estimated"}}}'
    )
    as_json = tmp_path / "document.json"
    as_json.write_text(text, encoding="utf-8")
    as_yaml = tmp_path / "document.yaml"
    as_yaml.write_text(text, encoding="utf-8")

    registry = load()
    for path in (as_json, as_yaml):
        element = _entries(load_document(path), "annex_xi")["computational_resources"]
        assert isinstance(element, dict)
        assert isinstance(element["training_flop"], float)
        assert element["training_flop"] == 9e24
        assert [
            finding
            for finding in lint(load_document(path), registry)
            if finding.location.startswith("annex_xi.computational_resources")
        ] == []


@pytest.mark.parametrize(
    ("token", "value"),
    [
        ("0", 0),
        ("017", 17),
        ("0o17", 15),
        ("0x1F", 31),
        ("2.3e25", 2.3e25),
        ("9e+24", 9e24),
        ("12:30", "12:30"),
        ("1_000", "1_000"),
        ("2026-07-30", "2026-07-30"),
    ],
    ids=[
        "zero",
        "decimal-leading-zero",
        "octal",
        "hex",
        "unsigned-exponent",
        "signed-exponent",
        "sexagesimal",
        "underscored",
        "date",
    ],
)
def test_the_reader_constructs_yaml_1_2_core_literals(
    tmp_path: Path, token: str, value: object
) -> None:
    # Ints and floats follow the YAML 1.2 core schema, so YAML
    # 1.1's surprises are never constructed: `12:30` and `1_000` stay strings,
    # `017` is decimal seventeen, and no date is built from unquoted text.
    path = tmp_path / "literals.yaml"
    path.write_text(
        "schema: 1\nannex_xi:\n  computational_resources:\n"
        f"    training_flop: {token}\n",
        encoding="utf-8",
    )

    element = _entries(load_document(path), "annex_xi")["computational_resources"]

    assert isinstance(element, dict)
    assert element["training_flop"] == value
    assert type(element["training_flop"]) is type(value)


def test_a_deeply_nested_yaml_document_is_refused(tmp_path: Path) -> None:
    # ~600 nested flow sequences already exhaust the parser's stack; the
    # boundary maps the RecursionError to a clean refusal, never a traceback.
    path = tmp_path / "deep.yaml"
    depth = 2000
    path.write_text(
        "schema: 1\nannex_xi:\n  intended_tasks: " + "[" * depth + "]" * depth + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DocumentError, match="too deeply nested"):
        load_document(path)


def test_a_deeply_nested_json_document_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    depth = 25000
    path.write_text("[" * depth + "]" * depth, encoding="utf-8")

    with pytest.raises(DocumentError, match="too deeply nested"):
        load_document(path)


def test_an_explicit_timestamp_tag_is_a_parse_error_when_impossible(
    tmp_path: Path,
) -> None:
    # The reader constructs no dates from unquoted text, but an explicit
    # `!!timestamp` tag still reaches PyYAML's constructor; its ValueError
    # over an impossible date is a clean refusal, not a crash.
    path = tmp_path / "tagged.yaml"
    path.write_text(
        "schema: 1\nnotifications:\n  - aware_on: !!timestamp 2026-13-01\n",
        encoding="utf-8",
    )

    with pytest.raises(DocumentError, match="invalid YAML"):
        load_document(path)


def test_an_upper_case_json_suffix_still_parses_under_json(tmp_path: Path) -> None:
    # The suffix match is case-insensitive: a .JSON file must not fall back
    # to the YAML reader and read `9e+24` as text.
    path = tmp_path / "document.JSON"
    path.write_text(
        '{"schema": 1, "annex_xi": {"computational_resources": '
        '{"training_flop": 9e+24}}}',
        encoding="utf-8",
    )

    annex = _entries(load_document(path), "annex_xi")
    element = annex["computational_resources"]

    assert isinstance(element, dict)
    assert isinstance(element["training_flop"], float)
    assert element["training_flop"] == 9e24


def test_load_document_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schema": 1,', encoding="utf-8")

    with pytest.raises(DocumentError, match="invalid JSON"):
        load_document(path)


def test_load_document_rejects_a_non_mapping_json_root(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(DocumentError, match="must contain a JSON mapping"):
        load_document(path)


def test_a_json_document_lints_identically_to_its_yaml_twin(tmp_path: Path) -> None:
    yaml_path = tmp_path / "twin.yaml"
    yaml_path.write_text(
        "schema: 1\n"
        "annex_xi:\n"
        "  intended_tasks: Text-to-text generation\n"
        "  computational_resources:\n"
        "    training_flop: 2.3e+25\n"
        "notifications:\n"
        "  - notified_on: 2026-07-30\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "twin.json"
    json_path.write_text(
        '{"schema": 1, "annex_xi": {"intended_tasks": "Text-to-text generation",'
        ' "computational_resources": {"training_flop": 2.3e+25}},'
        ' "notifications": [{"notified_on": "2026-07-30"}]}',
        encoding="utf-8",
    )
    registry = load()

    yaml_findings = lint(load_document(yaml_path), registry)
    json_findings = lint(load_document(json_path), registry)

    assert json_findings == yaml_findings
    # Both really linted: the absent elements are still reported.
    assert yaml_findings


def test_load_document_rejects_a_duplicated_key(tmp_path: Path) -> None:
    path = tmp_path / "duplicated.yaml"
    path.write_text(
        "schema: 1\n"
        "annex_xi:\n"
        "  intended_tasks: the first value\n"
        "  intended_tasks: the second value\n",
        encoding="utf-8",
    )

    with pytest.raises(DocumentError, match="duplicate key"):
        load_document(path)


def test_load_document_rejects_a_duplicated_key_in_json(tmp_path: Path) -> None:
    path = tmp_path / "duplicated.json"
    path.write_text(
        '{"schema": 1, "annex_xi": {"intended_tasks": "first", '
        '"intended_tasks": "second"}}',
        encoding="utf-8",
    )

    with pytest.raises(DocumentError, match="duplicate key"):
        load_document(path)


def test_load_document_rejects_a_non_mapping_annex_section(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("schema: 1\nannex_xi:\n  - intended_tasks\n", encoding="utf-8")

    with pytest.raises(DocumentError, match="annex_xi must be a mapping"):
        load_document(path)


def test_load_document_rejects_a_non_mapping_file(tmp_path: Path) -> None:
    path = tmp_path / "list-root.yaml"
    path.write_text("- schema\n- annex_xi\n", encoding="utf-8")

    with pytest.raises(DocumentError, match="must contain a YAML mapping"):
        load_document(path)


def test_load_document_rejects_a_non_string_key(tmp_path: Path) -> None:
    path = tmp_path / "int-key.yaml"
    path.write_text("schema: 1\nannex_xi:\n  1: text\n", encoding="utf-8")

    with pytest.raises(DocumentError, match="non-string key"):
        load_document(path)


def test_load_document_keeps_a_typoed_top_level_key_for_the_checks(
    tmp_path: Path,
) -> None:
    # A misspelt section must not vanish: the loader keeps it raw, lint
    # reports it through the typed pass's extra-key errors.
    path = tmp_path / "typo.yaml"
    path.write_text("schema: 1\nannex_x1:\n  intended_tasks: text\n", encoding="utf-8")

    assert load_document(path) == Document(
        values={"annex_x1": {"intended_tasks": "text"}}
    )


def test_load_document_rejects_a_non_string_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "int-key.yaml"
    path.write_text("schema: 1\n1: text\n", encoding="utf-8")

    with pytest.raises(DocumentError, match="non-string key"):
        load_document(path)


def test_load_document_reports_an_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(DocumentError, match="cannot read"):
        load_document(tmp_path / "absent.yaml")


def test_load_document_reports_a_non_utf8_file(tmp_path: Path) -> None:
    # Malformed bytes are an unreadable document, not a UnicodeDecodeError.
    path = tmp_path / "latin-1.yaml"
    path.write_bytes(b"annex_xi: caf\xe9\n")

    with pytest.raises(DocumentError, match="cannot read"):
        load_document(path)


def test_load_document_rejects_an_unhashable_key(tmp_path: Path) -> None:
    # A sequence key cannot be a mapping key; stock PyYAML refuses it with
    # "found unhashable key", and the shared reader must not degrade that
    # refusal to a bare TypeError.
    path = tmp_path / "sequence-key.yaml"
    path.write_text("? [a, b]\n: value\n", encoding="utf-8")

    with pytest.raises(DocumentError, match="unhashable key"):
        load_document(path)
