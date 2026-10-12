"""The ``extract annex-xii`` command and its subset projection.

The subset is ``schema: 1`` plus the ``annex_xii`` values verbatim, in the
document's own key order; the exit codes (0 extracted, 1 nothing to extract,
2 bad input) and the twins' round-trip refusals are pinned end to end.
"""

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from gpai_docs import cli
from gpai_docs.documents import Document, dump_document_yaml, load_document
from gpai_docs.extract import annex_xii_subset, subset_json, subset_yaml
from gpai_docs.lint import lint
from gpai_docs.registry import load

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = FIXTURES / "model-docs-example.yaml"


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


def test_annex_xii_subset_keeps_the_values_verbatim_in_document_order() -> None:
    # The projection is the whole contract: the marker and the section, no
    # re-typing and no re-ordering. The section is a copy, so a caller can
    # never write back into the loaded document.
    document = load_document(EXAMPLE)

    subset = annex_xii_subset(document)

    section = subset["annex_xii"]
    original = document.values["annex_xii"]
    assert list(subset) == ["schema", "annex_xii"]
    assert subset["schema"] == 1
    assert isinstance(section, dict)
    assert isinstance(original, dict)
    assert section is not original
    assert section == original
    assert list(section) == list(original)


def test_annex_xii_subset_of_a_document_without_the_section_is_empty() -> None:
    # The projection is total: a document that never carried Annex XII
    # projects to the marker plus an empty mapping, which is exactly the
    # shape the command refuses to write.
    subset = annex_xii_subset(Document(values={"annex_xi": {"licence": "MIT"}}))

    assert subset == {"schema": 1, "annex_xii": {}}


def test_extract_writes_a_subset_that_reloads_as_annex_xii_only(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # The round trip through the ordinary loader: the extracted file is a
    # valid v0.1 document carrying the section's values and nothing else (no
    # annex_xi, no records, no provenance header).
    target = tmp_path / "annex-xii.yaml"

    code = _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", str(target)])
    captured = capsysbinary.readouterr()

    assert code == 0
    assert captured.out == b""
    assert captured.err == b""
    source = load_document(EXAMPLE)
    reloaded = load_document(target)
    assert reloaded.values == {"annex_xii": source.values["annex_xii"]}
    assert reloaded.records == {}
    assert target.read_bytes() == subset_yaml(annex_xii_subset(source)).encode("utf-8")


def test_the_subset_lints_with_every_annex_xi_element_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The subset's own lint run, pinned as correct: every Annex XI
    # element reads missing (the subset is Annex XII only) while no Annex XII
    # element does. The example lints with no missing findings at all, so the
    # XI report is the extraction's doing, not the fixture's. The three
    # Section 2 fields stay skipped: no systemic-risk marker.
    registry = load()
    target = tmp_path / "annex-xii.yaml"
    assert (
        _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", str(target)])
        == 0
    )

    missing = [
        finding
        for finding in lint(load_document(target), registry)
        if finding.kind == "missing"
    ]

    assert {finding.location for finding in missing} == {
        field.model_field
        for field in registry.fields
        if field.model_field.startswith("annex_xi.") and field.condition is None
    }
    assert not any(finding.location.startswith("annex_xii.") for finding in missing)
    assert not [
        finding
        for finding in lint(load_document(EXAMPLE), registry)
        if finding.kind == "missing"
    ]


def test_stdout_is_deterministic_header_free_yaml(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    # Two runs, byte-identical bytes: block-style YAML with the marker first,
    # the document's own key order, one trailing newline and no comments, no
    # document-start marker, no provenance noise of any kind.
    assert _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE)]) == 0
    first = capsysbinary.readouterr()
    assert _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE)]) == 0
    second = capsysbinary.readouterr()

    assert first.err == b"" and second.err == b""
    assert first.out == second.out
    text = first.out.decode("utf-8")
    assert text.startswith("schema: 1\n")
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "---" not in text
    assert not [line for line in text.splitlines() if line.startswith("#")]
    dumped = yaml.safe_load(text)
    original = load_document(EXAMPLE).values["annex_xii"]
    assert isinstance(original, dict)
    assert list(dumped) == ["schema", "annex_xii"]
    assert list(dumped["annex_xii"]) == list(original)


def test_out_dash_and_absent_write_the_same_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    # ``-o -`` names stdout; the bytes are the absent ``-o`` run's own, down
    # to the trailing newline.
    assert _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", "-"]) == 0
    dashed = capsysbinary.readouterr()
    assert _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE)]) == 0
    plain = capsysbinary.readouterr()

    assert dashed.err == b"" and plain.err == b""
    assert dashed.out == plain.out


def test_out_file_carries_the_stdout_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # -o moves the output, it does not change it: the file carries the same
    # bytes the stdout run prints, and stdout stays empty.
    assert _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE)]) == 0
    stdout_bytes = capsysbinary.readouterr().out
    target = tmp_path / "annex-xii.yaml"

    assert (
        _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", str(target)])
        == 0
    )
    captured = capsysbinary.readouterr()

    assert captured.out == b""
    assert captured.err == b""
    assert target.read_bytes() == stdout_bytes


def test_out_json_writes_the_json_twin(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # A .json -o path writes the twin: the same data, the same order, indent
    # 2 and one trailing newline, byte-identical across runs.
    target = tmp_path / "annex-xii.json"

    assert (
        _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", str(target)])
        == 0
    )
    captured = capsysbinary.readouterr()

    assert captured.out == b""
    assert captured.err == b""
    text = target.read_text(encoding="utf-8")
    source = load_document(EXAMPLE)
    original = source.values["annex_xii"]
    assert isinstance(original, dict)
    assert text == json.dumps(json.loads(text), indent=2) + "\n"
    assert text == subset_json(annex_xii_subset(source))
    assert json.loads(text) == annex_xii_subset(source)
    assert list(json.loads(text)["annex_xii"]) == list(original)
    assert (
        _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", str(target)])
        == 0
    )
    assert target.read_text(encoding="utf-8") == text


# The shapes the JSON twin must refuse because JSON cannot write them: bytes
# behind an explicit tag, and an int key JSON would silently re-spell as its
# own text. Each tuple is (document text, the value the YAML twin keeps, the
# cause the refusal line names). A date is refused by both twins and pinned
# separately below.
NON_JSON_CASES = [
    pytest.param(
        "schema: 1\nannex_xii:\n  licence: !!binary aGk=\n",
        {"schema": 1, "annex_xii": {"licence": b"hi"}},
        "Object of type bytes is not JSON serializable",
        id="tagged-bytes",
    ),
    pytest.param(
        "schema: 1\nannex_xii:\n  nested:\n    - 1: x\n",
        {"schema": 1, "annex_xii": {"nested": [{1: "x"}]}},
        "non-string key 1 cannot be written as JSON",
        id="non-string-key",
    ),
]


@pytest.mark.parametrize(("content", "kept", "cause"), NON_JSON_CASES)
def test_json_twin_refuses_content_json_cannot_carry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    content: str,
    kept: object,
    cause: str,
) -> None:
    # The twin carries only what JSON writes natively. Content it cannot
    # carry (a tagged value, a key it would silently re-spell) is refused
    # with one line naming the document and the cause, exit 2 and nothing
    # written, never a re-spelling or a traceback. The YAML twin keeps the
    # shape, so the two can never silently disagree.
    document = tmp_path / "document.yaml"
    document.write_text(content, encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    target = outdir / "document.json"

    code = _run(monkeypatch, ["extract", "annex-xii", str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: ")
    assert str(document) in captured.err
    assert cause in captured.err
    assert list(outdir.iterdir()) == []

    assert _run(monkeypatch, ["extract", "annex-xii", str(document)]) == 0
    yaml_captured = capsys.readouterr()

    assert yaml_captured.err == ""
    assert yaml.safe_load(yaml_captured.out) == kept


# A date value, reachable only through an explicit ``!!timestamp`` tag: this
# toolchain's reader constructs no date, so ``yaml.safe_dump`` writing the
# plain scalar means the value reloads as a *string* and the subset would
# re-type itself on the next load. Both twins refuse it, pinned in the two
# positions a date can take below a section: a leaf and a mapping key. Each
# case is (document text, the cause the JSON twin's refusal names).
DATE_CASES = [
    pytest.param(
        "schema: 1\nannex_xii:\n  licence: !!timestamp 2026-05-05\n",
        "Object of type date is not JSON serializable",
        id="date-leaf",
    ),
    pytest.param(
        "schema: 1\nannex_xii:\n  licence: !!timestamp 2026-05-05T12:30:00\n",
        "Object of type datetime is not JSON serializable",
        id="datetime-leaf",
    ),
    pytest.param(
        "schema: 1\nannex_xii:\n  nested:\n    - ? !!timestamp 2026-05-05\n      : x\n",
        "non-string key datetime.date(2026, 5, 5) cannot be written as JSON",
        id="date-key",
    ),
]


@pytest.mark.parametrize(("content", "json_cause"), DATE_CASES)
def test_the_yaml_twin_refuses_a_date_value(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    content: str,
    json_cause: str,
) -> None:
    # The reader constructs no date, so a written date can never round-trip:
    # the YAML twin refuses it (one line naming the document and the cause,
    # exit 2, nothing on stdout, a pre-existing -o target untouched), and the
    # JSON twin keeps refusing it its own way.
    document = tmp_path / "dated.yaml"
    document.write_text(content, encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    yaml_target = outdir / "dated.yaml"
    json_target = outdir / "dated.json"
    yaml_target.write_bytes(b"previous yaml bytes")
    json_target.write_bytes(b"previous json bytes")

    for target in (yaml_target, None):
        argv = ["extract", "annex-xii", str(document)]
        if target is not None:
            argv += ["-o", str(target)]
        code = _run(monkeypatch, argv)
        captured = capsys.readouterr()

        assert code == 2
        assert captured.out == ""
        assert captured.err.count("\n") == 1
        assert str(document) in captured.err
        assert "date 2026-05-05" in captured.err
        assert "does not round-trip" in captured.err
        assert yaml_target.read_bytes() == b"previous yaml bytes"
        assert json_target.read_bytes() == b"previous json bytes"

    code = _run(
        monkeypatch, ["extract", "annex-xii", str(document), "-o", str(json_target)]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert json_cause in captured.err
    assert yaml_target.read_bytes() == b"previous yaml bytes"
    assert json_target.read_bytes() == b"previous json bytes"


def test_json_twin_refuses_a_cyclic_section(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # A YAML alias can make a mapping under the section refer to itself.
    # The walk must terminate rather than trace back, so the twin refuses
    # the cycle with the same one-liner and exit 2, while the YAML twin
    # writes the cycle with anchors and reloads it intact.
    document = tmp_path / "cyclic.yaml"
    document.write_text(
        "schema: 1\nannex_xii:\n  nested: &x\n    back: *x\n", encoding="utf-8"
    )
    outdir = tmp_path / "out"
    outdir.mkdir()
    target = outdir / "cyclic.json"

    code = _run(monkeypatch, ["extract", "annex-xii", str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert str(document) in captured.err
    assert "circular reference cannot be written as JSON" in captured.err
    assert list(outdir.iterdir()) == []

    assert _run(monkeypatch, ["extract", "annex-xii", str(document)]) == 0
    yaml_captured = capsys.readouterr()

    assert yaml_captured.err == ""
    reloaded = yaml.safe_load(yaml_captured.out)
    nested = reloaded["annex_xii"]["nested"]
    assert nested["back"] is nested


def test_json_twin_carries_an_empty_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An empty list is JSON-native content the walk steps through (and
    # through nothing) rather than refuses: the twin writes it.
    document = tmp_path / "empty-list.yaml"
    document.write_text("schema: 1\nannex_xii:\n  licence: []\n", encoding="utf-8")
    target = tmp_path / "empty-list.json"

    assert (
        _run(
            monkeypatch,
            ["extract", "annex-xii", str(document), "-o", str(target)],
        )
        == 0
    )

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "schema": 1,
        "annex_xii": {"licence": []},
    }


# The non-finite floats neither twin may write: JSON's own parser takes a
# bare NaN and overflows 1e400 to infinity, and the YAML reader overflows it
# the same way, so a written subset would carry either the non-standard
# NaN/Infinity JSON or the ``.inf``/``.nan`` YAML spellings this toolchain's
# own reader deliberately reads back as strings.
NON_FINITE_CASES = [
    pytest.param(
        "document.json",
        '{"schema": 1, "annex_xii": {"licence": NaN}}',
        "nan",
        id="json-nan",
    ),
    pytest.param(
        "document.json",
        '{"schema": 1, "annex_xii": {"licence": 1e400}}',
        "inf",
        id="json-overflow",
    ),
    pytest.param(
        "document.json",
        '{"schema": 1, "annex_xii": {"licence": -1e400}}',
        "-inf",
        id="json-negative-overflow",
    ),
    pytest.param(
        "document.yaml",
        "schema: 1\nannex_xii:\n  licence: 1e400\n",
        "inf",
        id="yaml-overflow",
    ),
    pytest.param(
        "document.yaml",
        "schema: 1\nannex_xii:\n  licence: -1e400\n",
        "-inf",
        id="yaml-negative-overflow",
    ),
]


@pytest.mark.parametrize(("name", "content", "kind"), NON_FINITE_CASES)
def test_both_twins_refuse_a_non_finite_float(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    name: str,
    content: str,
    kind: str,
) -> None:
    # Neither twin can write a non-finite float faithfully: JSON has no
    # spelling for one, and the YAML twin's ``.inf``/``.nan`` is read back as
    # a *string* by this toolchain's own reader, so the subset would re-type
    # itself on the next load and extract would not be idempotent over its
    # own output. Both refuse it alike: one line naming the document and the
    # cause, exit 2, nothing on stdout, no half-written target left behind.
    document = tmp_path / name
    document.write_text(content, encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    json_target = outdir / "document.json"
    yaml_target = outdir / "document.yaml"
    json_target.write_bytes(b"previous json bytes")
    yaml_target.write_bytes(b"previous yaml bytes")
    cause = f"non-finite float {kind} does not round-trip"

    for target in (json_target, yaml_target):
        code = _run(
            monkeypatch, ["extract", "annex-xii", str(document), "-o", str(target)]
        )
        captured = capsys.readouterr()

        assert code == 2
        assert captured.out == ""
        assert captured.err.count("\n") == 1
        assert str(document) in captured.err
        assert cause in captured.err
        assert json_target.read_bytes() == b"previous json bytes"
        assert yaml_target.read_bytes() == b"previous yaml bytes"

    code = _run(monkeypatch, ["extract", "annex-xii", str(document)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert cause in captured.err


def test_extract_help_states_the_exit_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exit contract is part of the command's interface: the
    # help names the success, nothing-to-extract and bad-input codes the way
    # diff --help names its own, so a CI consumer can read the contract
    # before wiring the step. Rich may wrap the line, so the assertion reads
    # the words with whitespace collapsed.
    code = _run(monkeypatch, ["extract", "annex-xii", "--help"])
    words = " ".join(_strip_ansi(capsys.readouterr().out).split())

    assert code == 0
    assert (
        "Exit codes: 0 subset written, 1 nothing to extract "
        "(no Annex XII values), 2 bad input" in words
    )


@pytest.mark.parametrize("content", ["schema: 1\nannex_xii: {}\n", "schema: 1\n"])
def test_empty_annex_xii_exits_1_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    content: str,
) -> None:
    # An absent or empty section is a real CI-relevant condition: one line
    # naming the document, exit 1, stdout clean, and the target directory
    # untouched, so the failure leaves no half-written subset for a later run
    # to pick up.
    document = tmp_path / "empty.yaml"
    document.write_text(content, encoding="utf-8")
    outdir = tmp_path / "out"
    outdir.mkdir()
    target = outdir / "annex-xii.yaml"

    code = _run(monkeypatch, ["extract", "annex-xii", str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert str(document) in captured.err
    assert "Annex XII" in captured.err
    assert list(outdir.iterdir()) == []


def test_a_section_with_only_blank_values_still_extracts(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # "Empty" means the section carries no entries. A blank value is the
    # format's absence semantics, which lint judges; extract mirrors what
    # the document writes, so the key rides through verbatim.
    document = tmp_path / "blank.yaml"
    document.write_text("schema: 1\nannex_xii:\n  licence: ''\n", encoding="utf-8")

    assert _run(monkeypatch, ["extract", "annex-xii", str(document)]) == 0
    captured = capsysbinary.readouterr()

    assert captured.err == b""
    assert yaml.safe_load(captured.out.decode("utf-8")) == {
        "schema": 1,
        "annex_xii": {"licence": ""},
    }


def test_empty_annex_xii_keeps_stdout_clean(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Without -o the one-line message still goes to stderr: stdout carries
    # either a subset or nothing at all, never a diagnostic.
    document = tmp_path / "empty.yaml"
    document.write_text("schema: 1\nannex_xii: {}\n", encoding="utf-8")

    code = _run(monkeypatch, ["extract", "annex-xii", str(document)])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out == ""
    assert captured.err.count("\n") == 1


@pytest.mark.parametrize(
    "content",
    [
        None,
        "annex_xii:\n  licence: MIT\n",
        "schema: 1\nannex_xii: [licence]\n",
    ],
)
def test_bad_input_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
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
    target = outdir / "annex-xii.yaml"

    code = _run(monkeypatch, ["extract", "annex-xii", str(document), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: ")
    assert list(outdir.iterdir()) == []


@pytest.mark.parametrize("case", ["directory", "missing-parent"])
def test_unwritable_out_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: str,
) -> None:
    # An -o the process cannot write is bad input (2), mirroring the schema
    # command's one-liner: a directory and a missing parent are the two
    # deterministic cases.
    target = tmp_path if case == "directory" else tmp_path / "absent" / "out.yaml"

    code = _run(monkeypatch, ["extract", "annex-xii", str(EXAMPLE), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: cannot write ")
    assert str(target) in captured.err


# The strings PyYAML's own SafeDumper leaves plain but this toolchain's YAML
# 1.2-core reader constructs as numbers: without the shared dumper's quoting,
# a written subset would re-type itself on the next load.
# Each spelling is one the dumper and the reader disagree about.
NUMBER_LIKE_STRINGS = ["2.3e25", "1e400", "0o17", "0x1F"]


@pytest.mark.parametrize("spelling", NUMBER_LIKE_STRINGS)
def test_dump_document_yaml_quotes_every_number_like_string(
    tmp_path: Path, spelling: str
) -> None:
    # The shared dumper force-quotes, single-quoted style, exactly the
    # strings the reader's own resolvers would construct as numbers (the
    # grammar is single-sourced from the reader, so the two cannot drift),
    # and leaves ordinary text in SafeDumper's own plain style.
    text = dump_document_yaml({"schema": 1, "annex_xii": {"licence": spelling}})

    assert f"licence: '{spelling}'\n" in text
    written = tmp_path / "document.yaml"
    written.write_text(text, encoding="utf-8")
    reloaded = load_document(written)
    section = reloaded.values["annex_xii"]
    assert isinstance(section, dict)
    assert section["licence"] == spelling
    assert isinstance(section["licence"], str)

    assert dump_document_yaml({"licence": "plain text"}) == "licence: plain text\n"


@pytest.mark.parametrize("spelling", NUMBER_LIKE_STRINGS)
def test_a_number_like_string_round_trips_byte_identically(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
    spelling: str,
) -> None:
    # The extraction round trip over these spellings: a document carrying the
    # STRING re-extracts through its own reader, reloads as that string, never
    # as a number, and the second extract is byte-identical to the first, so
    # the twin is idempotent over its own output.
    document = tmp_path / "number-like.yaml"
    document.write_text(
        f"schema: 1\nannex_xii:\n  licence: '{spelling}'\n", encoding="utf-8"
    )

    assert _run(monkeypatch, ["extract", "annex-xii", str(document)]) == 0
    first = capsysbinary.readouterr()

    assert first.err == b""
    assert f"licence: '{spelling}'\n".encode() in first.out
    reloaded = tmp_path / "reloaded.yaml"
    reloaded.write_bytes(first.out)
    section = load_document(reloaded).values["annex_xii"]
    assert isinstance(section, dict)
    assert section["licence"] == spelling

    assert _run(monkeypatch, ["extract", "annex-xii", str(reloaded)]) == 0
    second = capsysbinary.readouterr()

    assert second.out == first.out


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("inf"), id="inf"),
        pytest.param(float("-inf"), id="negative-inf"),
        pytest.param(float("nan"), id="nan"),
    ],
)
def test_dump_document_yaml_refuses_a_non_finite_float(value: float) -> None:
    # The round-trip claim has exactly one shape the dumper refuses itself:
    # it spells a non-finite float ``.inf``/``.nan``, and this toolchain's
    # reader deliberately constructs no float from either text, so the value
    # would read back as the string. The refusal is the ValueError the
    # commands already map to exit 2, it fires wherever the float sits (a
    # value, a key, a nested list), and it fires before any text exists.
    for content in ({"licence": value}, {"nested": [value]}, {value: "x"}):
        with pytest.raises(ValueError, match="does not round-trip"):
            dump_document_yaml({"schema": 1, "annex_xii": content})


def test_dump_document_yaml_writes_a_cycle_the_reader_restores() -> None:
    # A cycle is no non-finite float: YAML writes it as anchors the reader
    # restores, and the refusal walk stops at a container it has already
    # visited instead of tracing back.
    nested: dict[str, object] = {}
    nested["back"] = nested

    text = dump_document_yaml({"schema": 1, "annex_xii": {"nested": nested}})

    reloaded = yaml.safe_load(text)
    restored = reloaded["annex_xii"]["nested"]
    assert restored["back"] is restored
