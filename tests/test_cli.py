"""Pin the CLI entry point's exit-code contract.

The app runs through ``main()`` with ``sys.argv`` monkeypatched, so the tests
see the same codes the console script and ``python -m gpai_docs`` get;
registries, fetchers and Form packages are injected or taken from fixtures.
"""

import dataclasses
import json
import re
import runpy
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from gpai_docs import cli
from gpai_docs.documents import dump_document_yaml, load_document
from gpai_docs.docxform import locate_rows, read_rows
from gpai_docs.lint import lint
from gpai_docs.registry import Registry, RegistryError, load
from gpai_docs.registry.extract import element_inventory, sha256_of
from gpai_docs.registry.fetch import FetchResult

# tests/fixtures is a plain module (no package __init__); its directory goes
# on the path so the import below resolves under pytest's importlib mode and
# mypy alike.
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from form_docx import Row, write_form_docx, write_package

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "registry_mini"
ANNEX_EXCERPT = FIXTURES / "eurlex_annex_excerpt.html"
EXAMPLE_DOCUMENT = FIXTURES / "model-docs-example.yaml"
FOOTER = "engineering evidence, not a compliance verdict"

# The Form's three audience columns, all ticked.
ALL_CROSSES = {"ai_office": True, "nca": True, "downstream": True}

REGULATION_URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727"
)
RESOLVER_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689"
# The Form DOCX pin from the fixture; FORM_BODY is the bytes its recorded
# hash covers.
FORM_URL = "https://ec.europa.eu/newsroom/dae/redirection/document/118118"
FORM_BODY = b"the form docx bytes"
# The Annex XI point 1(a) text, pinned in tests/test_extract.py.
XI_1_1_A = (
    "the tasks that the model is intended to perform and the type and nature of "
    "AI systems in which it can be integrated;"
)


class _FakeFetcher:
    """One canned body for any URL; records what was asked for."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self._status = status
        self.calls: list[tuple[str, float]] = []

    def fetch(self, url: str, timeout: float) -> FetchResult:
        self.calls.append((url, timeout))
        return FetchResult(body=self._body, final_url=url, status=self._status)


class _RoutedFetcher:
    """Canned responses by URL; records what was asked for."""

    def __init__(self, responses: dict[str, FetchResult]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, float]] = []

    def fetch(self, url: str, timeout: float) -> FetchResult:
        self.calls.append((url, timeout))
        return self._responses[url]


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["gpai-docs", *argv])
    return cli.main()


# Rich styles Typer's usage errors into spans under forced colour (so
# ``--timeout`` arrives split); assertions read captured text unstyled.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Captured CLI text without ANSI styling, so assertions read the words."""
    return _ANSI_ESCAPE.sub("", text)


def _registry_with_fields(identifiers: list[str]) -> Registry:
    """The mini registry with one field per identifier, in that order."""
    registry = load(MINI)
    fields = [
        registry.fields[0].model_copy(update={"id": identifier})
        for identifier in identifiers
    ]
    return dataclasses.replace(
        registry, fields=fields, by_id={field.id: field for field in fields}
    )


def test_no_arguments_prints_the_command_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # click treats no arguments as a usage error: the help text goes to stdout
    # and the shared exit contract calls it bad input (2).
    code = _run(monkeypatch, [])

    assert code == 2
    assert "registry" in capsys.readouterr().out


def test_lint_help_names_the_consistency_checks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The summary is the discovery surface for what a run checks; Rich may
    # wrap the line, so the assertion reads the words with whitespace
    # collapsed.
    code = _run(monkeypatch, ["lint", "--help"])
    words = " ".join(_strip_ansi(capsys.readouterr().out).split())

    assert code == 0
    assert (
        words.count(
            "Check a document: missing, malformed, unknown and inconsistent findings."
        )
        == 1
    )


def test_python_m_reaches_the_same_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # runpy is what covers __main__.py, which nothing else imports.
    monkeypatch.setattr(sys, "argv", ["gpai-docs"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("gpai_docs", run_name="__main__")
    assert excinfo.value.code == 2


def test_registry_fetch_json_is_a_clean_dry_run_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fetcher = _FakeFetcher(ANNEX_EXCERPT.read_bytes())
    monkeypatch.setattr(cli, "load", lambda: load(MINI))
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    code = _run(monkeypatch, ["registry", "fetch", "--json", "--timeout", "5"])
    captured = capsys.readouterr()

    assert code == 0
    # stdout is a pure JSON document; the per-source diff stays on stderr.
    payload = json.loads(captured.out)
    assert payload["changed"] == ["xi-1-1-a"]
    assert payload["failed"] == []
    assert fetcher.calls == [
        (
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727",
            5.0,
        )
    ]
    assert "xi-1-1-a: changed" in captured.err


def test_registry_fetch_maps_a_failed_fetch_to_a_findings_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fetcher = _FakeFetcher(b"", status=202)
    monkeypatch.setattr(cli, "load", lambda: load(MINI))
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    code = _run(monkeypatch, ["registry", "fetch"])

    assert code == 1
    assert "xi-1-1-a: failed" in capsys.readouterr().err


def test_registry_fetch_maps_a_broken_registry_to_bad_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode() -> None:
        raise RegistryError("fields.yaml: broken")

    monkeypatch.setattr(cli, "load", explode)

    code = _run(monkeypatch, ["registry", "fetch"])

    assert code == 2
    assert "fields.yaml: broken" in capsys.readouterr().err


def test_registry_fetch_prints_the_inventory_diff_in_human_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A fetch prints the element-inventory diff in human mode too;
    # the mini registry registers one of the excerpt's eleven XI points.
    fetcher = _FakeFetcher(ANNEX_EXCERPT.read_bytes())
    monkeypatch.setattr(cli, "load", lambda: load(MINI))
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    code = _run(monkeypatch, ["registry", "fetch"])
    out = _strip_ansi(capsys.readouterr().out)

    assert code == 0
    assert "inventory added: XI.1.1.b" in out
    # Nothing has vanished, so no removal line is printed.
    assert "inventory removed:" not in out


def test_registry_fetch_prints_a_vanished_inventory_id_in_human_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A registered point the document no longer carries is the "vanished"
    # half of the inventory diff.
    fetcher = _FakeFetcher(ANNEX_EXCERPT.read_bytes())
    registry = _registry_with_fields(["XI.1.1.a", "XI.1.1.g"])
    monkeypatch.setattr(cli, "load", lambda: registry)
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    code = _run(monkeypatch, ["registry", "fetch"])
    out = _strip_ansi(capsys.readouterr().out)

    assert code == 0
    assert "inventory removed: XI.1.1.g" in out


def test_registry_fetch_prints_no_inventory_lines_when_the_diff_is_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The inventory lines appear only when there is a diff to review.
    inventory = element_inventory(ANNEX_EXCERPT.read_bytes(), "XI")
    registry = _registry_with_fields(inventory)
    fetcher = _FakeFetcher(ANNEX_EXCERPT.read_bytes())
    monkeypatch.setattr(cli, "load", lambda: registry)
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    code = _run(monkeypatch, ["registry", "fetch"])
    out = _strip_ansi(capsys.readouterr().out)

    assert code == 0
    assert "inventory" not in out


@pytest.mark.parametrize(
    "command", [["registry", "fetch"], ["registry", "verify", "--online"]]
)
@pytest.mark.parametrize("value", ["-1", "nan", "inf", "-inf"])
def test_an_invalid_timeout_is_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
    value: str,
) -> None:
    # A negative or non-finite timeout would reach ``socket.settimeout`` and
    # escape as a traceback; it is bad input (2), rejected before any fetch.
    class NeverFetched:
        def fetch(self, url: str, timeout: float) -> FetchResult:
            raise AssertionError(f"fetched {url!r} with timeout {timeout!r}")

    monkeypatch.setattr(cli, "load", lambda: load(MINI))
    monkeypatch.setattr(cli, "UrllibFetcher", NeverFetched)

    code = _run(monkeypatch, [*command, f"--timeout={value}"])
    err = _strip_ansi(capsys.readouterr().err)

    assert code == 2
    assert "--timeout" in err
    assert "positive" in err


def test_ctrl_c_keeps_the_shell_convention(monkeypatch: pytest.MonkeyPatch) -> None:
    # 130 is 128 + SIGINT, the exit code a shell expects from an interrupted
    # process; typer turns the KeyboardInterrupt into it.
    class Interrupted:
        def fetch(self, url: str, timeout: float) -> FetchResult:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "load", lambda: load(MINI))
    monkeypatch.setattr(cli, "UrllibFetcher", Interrupted)

    assert _run(monkeypatch, ["registry", "fetch"]) == 130


def _tampered_registry() -> Registry:
    registry = load(MINI)
    source = registry.sources["xi-1-1-a"].model_copy(update={"text": "tampered"})
    return dataclasses.replace(registry, sources={"xi-1-1-a": source})


def test_registry_verify_reports_a_clean_offline_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load", lambda: load(MINI))

    code = _run(monkeypatch, ["registry", "verify"])
    captured = capsys.readouterr()

    assert code == 0
    # The shared footer is single-sourced from the lint package; the pinned
    # literal keeps the two print paths from drifting apart.
    assert captured.out.strip() == f"no findings - {FOOTER}"


def test_registry_verify_maps_a_finding_to_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load", _tampered_registry)

    code = _run(monkeypatch, ["registry", "verify"])
    out = capsys.readouterr().out

    assert code == 1
    assert "integrity" in out
    assert "xi-1-1-a" in out


def test_registry_verify_json_is_the_minimal_findings_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load", _tampered_registry)

    code = _run(monkeypatch, ["registry", "verify", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert set(payload) == {"findings"}
    (finding,) = payload["findings"]
    assert set(finding) == {"kind", "target", "message"}
    assert finding["kind"] == "integrity"
    assert finding["target"] == "xi-1-1-a"
    assert finding["message"]


def test_registry_verify_never_touches_the_network_without_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = _RoutedFetcher({})
    monkeypatch.setattr(cli, "load", lambda: load(MINI))
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    assert _run(monkeypatch, ["registry", "verify"]) == 0
    assert fetcher.calls == []


def test_registry_verify_online_uses_the_injected_fetcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load(MINI)
    source = registry.sources["xi-1-1-a"].model_copy(
        update={"text": XI_1_1_A, "sha256": sha256_of(XI_1_1_A)}
    )
    registry = dataclasses.replace(registry, sources={"xi-1-1-a": source})
    fetcher = _RoutedFetcher(
        {
            REGULATION_URL: FetchResult(
                body=ANNEX_EXCERPT.read_bytes(),
                final_url=REGULATION_URL,
                status=200,
            ),
            RESOLVER_URL: FetchResult(body=b"", final_url=REGULATION_URL, status=200),
            FORM_URL: FetchResult(body=FORM_BODY, final_url=FORM_URL, status=200),
        }
    )
    monkeypatch.setattr(cli, "load", lambda: registry)
    monkeypatch.setattr(cli, "UrllibFetcher", lambda: fetcher)

    code = _run(monkeypatch, ["registry", "verify", "--online", "--timeout", "5"])

    assert code == 0
    assert fetcher.calls == [
        (REGULATION_URL, 5.0),
        (FORM_URL, 5.0),
        (RESOLVER_URL, 5.0),
    ]


def test_registry_verify_maps_a_broken_registry_to_bad_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode() -> None:
        raise RegistryError("fields.yaml: broken")

    monkeypatch.setattr(cli, "load", explode)

    code = _run(monkeypatch, ["registry", "verify"])

    assert code == 2
    assert "fields.yaml: broken" in capsys.readouterr().err


def test_lint_reports_the_example_as_a_clean_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The complete example is the demo: every element present and well-typed,
    # so the run closes with the shared footer and exit 0.
    code = _run(monkeypatch, ["lint", str(EXAMPLE_DOCUMENT)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.strip() == f"no findings - {FOOTER}"
    assert captured.err == ""


def test_lint_exits_one_and_closes_with_the_finding_count(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The run-level closer is a fixed shape: count plus the shared
    # footer, printed once, after the citation blocks.
    path = tmp_path / "bare.yaml"
    path.write_text("schema: 1\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path)])
    out = capsys.readouterr().out

    assert code == 1
    assert "[MISSING] XI.1.2.e" in out
    assert "Annex XI, Section 1, point 2(e)" in out
    assert out.count(FOOTER) == 1
    assert out.rstrip().endswith(f"22 findings - {FOOTER}")


def test_lint_json_is_the_minimal_findings_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "bare.yaml"
    path.write_text("schema: 1\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert set(payload) == {"findings"}
    assert len(payload["findings"]) == 22
    # The basis keys are always present, empty on findings that rest only on
    # the element's own source.
    assert payload["findings"][0] == {
        "kind": "missing",
        "location": "annex_xi.intended_tasks",
        "field_id": "XI.1.1.a",
        "message": None,
        "citations": [],
        "basis_forms": [],
        "label": None,
    }


def test_lint_json_of_the_example_is_a_clean_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The example lints clean; the payload keeps the stable findings wrapper
    # the JSON contract pins.
    code = _run(monkeypatch, ["lint", str(EXAMPLE_DOCUMENT), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == {"findings": []}


def test_lint_json_carries_the_section_2_findings_when_the_marker_is_true(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The --json shape of the conditional fields: a marker-true document
    # without Section 2 values reports the three missing items through the
    # same stable finding shape.
    path = tmp_path / "systemic.yaml"
    path.write_text("schema: 1\nsystemic_risk: true\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert set(payload) == {"findings"}
    assert [
        finding
        for finding in payload["findings"]
        if finding["field_id"] is not None and finding["field_id"].startswith("XI.2.")
    ] == [
        {
            "kind": "missing",
            "location": "annex_xi.evaluation_strategies",
            "field_id": "XI.2.1",
            "message": None,
            "citations": [],
            "basis_forms": [],
            "label": None,
        },
        {
            "kind": "missing",
            "location": "annex_xi.adversarial_testing",
            "field_id": "XI.2.2",
            "message": None,
            "citations": [],
            "basis_forms": [],
            "label": None,
        },
        {
            "kind": "missing",
            "location": "annex_xi.system_architecture",
            "field_id": "XI.2.3",
            "message": None,
            "citations": [],
            "basis_forms": [],
            "label": None,
        },
    ]
    assert len(payload["findings"]) == 25


def test_lint_markdown_of_the_example_is_the_bare_closer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A clean run renders no section: the Markdown report is the italic
    # closer alone (the shared footer constant), and exit stays 0.
    code = _run(monkeypatch, ["lint", str(EXAMPLE_DOCUMENT), "--markdown"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == f"*no findings - {FOOTER}*\n"
    assert captured.err == ""


def test_lint_markdown_reports_the_bare_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Findings mode: exit 1 with the sections on stdout, closed by the italic
    # count line (exactly one footer occurrence, the closer's).
    path = tmp_path / "bare.yaml"
    path.write_text("schema: 1\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path), "--markdown"])
    out = capsys.readouterr().out

    assert code == 1
    assert out.startswith(
        "### [MISSING] XI.1.1.a - Tasks the model is intended to perform\n"
    )
    assert out.count(FOOTER) == 1
    assert out.rstrip().endswith(f"*22 findings - {FOOTER}*")


def test_lint_markdown_maps_a_bad_document_to_bad_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The Markdown flag reads through the ordinary loader: its refusals are
    # the shared bad input, with no report bytes.
    code = _run(monkeypatch, ["lint", "absent.yaml", "--markdown"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "cannot read" in captured.err


def test_lint_json_carries_the_record_location_of_a_late_notification(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # A record finding is field-less and addressed at its record: the payload
    # shows ``notifications[0]`` with the record label and the rule's three
    # cited sources. The element carries its method so compute.reporting
    # contributes nothing.
    path = tmp_path / "late.yaml"
    path.write_text(
        "schema: 1\n"
        "annex_xi:\n"
        "  computational_resources:\n"
        "    training_flop: 2.5e+25\n"
        "    estimation_method: extrapolated from the training report\n"
        "notifications:\n"
        "  - compute_flop: 2.5e+25\n"
        "    estimation_method: extrapolated from the training report\n"
        "    aware_on: 2026-07-20\n"
        "    notified_on: 2026-08-04\n",
        encoding="utf-8",
    )

    code = _run(monkeypatch, ["lint", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    (finding,) = [
        item for item in payload["findings"] if item["kind"] == "inconsistent"
    ]
    assert finding["location"] == "notifications[0]"
    assert finding["field_id"] is None
    assert finding["label"] == "Art. 52 notification record"
    assert finding["citations"] == [
        "reg-2024-1689-art-51-1-a",
        "reg-2024-1689-art-51-2",
        "reg-2024-1689-art-52-1",
    ]


def test_lint_maps_a_non_mapping_annex_section_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("schema: 1\nannex_xi:\n  - intended_tasks\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path)])

    assert code == 2
    assert "annex_xi must be a mapping" in capsys.readouterr().err


def test_lint_maps_a_duplicated_key_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicated.yaml"
    path.write_text("annex_xi:\n  a_key: 1\n  a_key: 2\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path)])

    assert code == 2
    assert "duplicate key" in capsys.readouterr().err


def test_lint_maps_a_missing_file_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    code = _run(monkeypatch, ["lint", str(tmp_path / "absent.yaml")])

    assert code == 2
    assert "cannot read" in capsys.readouterr().err


def test_lint_maps_a_non_utf8_file_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Malformed bytes are bad input (2), not a UnicodeDecodeError traceback:
    # the loader names the file in its own error.
    path = tmp_path / "latin-1.yaml"
    path.write_bytes(b"annex_xi: caf\xe9\n")

    code = _run(monkeypatch, ["lint", str(path)])

    assert code == 2
    assert "cannot read" in _strip_ansi(capsys.readouterr().err)


def test_lint_maps_an_unhashable_key_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # A YAML sequence key cannot be a mapping key; it is bad input (2), the
    # way stock PyYAML refuses it, never a bare TypeError traceback.
    path = tmp_path / "sequence-key.yaml"
    path.write_text("? [a, b]\n: value\n", encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path)])

    assert code == 2
    assert "unhashable key" in _strip_ansi(capsys.readouterr().err)


@pytest.mark.parametrize(
    "day", ["2026-13-01", "2026-02-30"], ids=["bad-month", "bad-day"]
)
def test_lint_reports_an_out_of_range_unquoted_date_as_a_finding(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    day: str,
) -> None:
    # The malformed example, end to end: the unquoted out-of-range
    # date is a finding (exit 1 with valid JSON), never a parser traceback.
    path = tmp_path / "date.yaml"
    path.write_text(
        f"schema: 1\nnotifications:\n  - aware_on: {day}\n", encoding="utf-8"
    )

    code = _run(monkeypatch, ["lint", str(path), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 1
    assert captured.err == ""
    assert [
        (finding["kind"], finding["location"], finding["message"])
        for finding in payload["findings"]
        if finding["kind"] == "malformed"
    ] == [
        (
            "malformed",
            "notifications[0].aware_on",
            f"expected a date: '{day}' is not a date",
        )
    ]


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_lint_maps_a_deeply_nested_document_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    suffix: str,
) -> None:
    # Both readers map a nesting overflow to the clean refusal:
    # bad input with one line naming the file, never a RecursionError.
    depth = 2000 if suffix == ".yaml" else 25000
    path = tmp_path / f"deep{suffix}"
    path.write_text("[" * depth + "]" * depth, encoding="utf-8")

    code = _run(monkeypatch, ["lint", str(path)])

    assert code == 2
    assert "too deeply nested" in _strip_ansi(capsys.readouterr().err)


# The two minimal documents the diff tests change between; they differ in
# one Annex XI element, and the shipped registry is what names it.
_OLD_LICENCE = 'schema: 1\nannex_xi:\n  licence: "Apache License 2.0"\n'
_NEW_LICENCE = 'schema: 1\nannex_xi:\n  licence: "MIT License"\n'


def _document(tmp_path: Path, name: str, text: str) -> Path:
    """One YAML document written where the CLI can load it."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_diff_of_identical_documents_is_a_silent_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The complete example against itself: no differences, no output, exit
    # 0 (the diff(1) convention's "same"); diff is the one command
    # whose 1 means "different" rather than "findings".
    code = _run(monkeypatch, ["diff", str(EXAMPLE_DOCUMENT), str(EXAMPLE_DOCUMENT)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_diff_of_a_nan_carrying_document_against_itself_is_no_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The JSON grammar admits a bare NaN, and for diff the writer's value is
    # the writer's value: two NaNs read as one, so a self-comparison is
    # silence (exit 0), never a ``changed`` whose two sides spell alike.
    path = tmp_path / "nan.json"
    path.write_text(
        '{"schema": 1, "annex_xi": {"intended_tasks": NaN}}', encoding="utf-8"
    )

    code = _run(monkeypatch, ["diff", str(path), str(path)])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert captured.err == ""

    code = _run(monkeypatch, ["diff", str(path), str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == {"changes": []}


def test_diff_reports_a_change_with_the_lint_note(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The human rendering, end to end: the pinned line (sign, registry path,
    # canonical values) and the one-line note that values are canonical and
    # validity is lint's.
    old = _document(tmp_path, "old.yaml", _OLD_LICENCE)
    new = _document(tmp_path, "new.yaml", _NEW_LICENCE)

    code = _run(monkeypatch, ["diff", str(old), str(new)])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out == (
        '~ annex_xi.licence: "Apache License 2.0" -> "MIT License"\n'
        "note: values are reported in the renderers' canonical form; "
        "validity is for gpai-docs lint to check\n"
    )
    assert captured.err == ""


def test_diff_json_is_the_stable_change_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # A document that fills the field and one that does not: the payload
    # keeps both value keys, null for the absent side.
    old = _document(tmp_path, "old.yaml", _OLD_LICENCE)
    new = _document(tmp_path, "new.yaml", "schema: 1\n")

    code = _run(monkeypatch, ["diff", str(old), str(new), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload == {
        "changes": [
            {
                "location": "annex_xi.licence",
                "kind": "removed",
                "from": "Apache License 2.0",
                "to": None,
            }
        ]
    }


def test_diff_json_of_identical_documents_is_a_clean_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = _run(
        monkeypatch, ["diff", str(EXAMPLE_DOCUMENT), str(EXAMPLE_DOCUMENT), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == {"changes": []}


def test_diff_markdown_is_the_change_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The table: the four columns, one row per change, canonical values
    # in the value cells.
    old = _document(tmp_path, "old.yaml", _OLD_LICENCE)
    new = _document(tmp_path, "new.yaml", _NEW_LICENCE)

    code = _run(monkeypatch, ["diff", str(old), str(new), "--markdown"])

    assert code == 1
    assert capsys.readouterr().out == (
        "| location | change | from | to |\n"
        "| --- | --- | --- | --- |\n"
        '| annex_xi.licence | changed | "Apache License 2.0" | "MIT License" |\n'
    )


@pytest.mark.parametrize("flags", [["--json", "--markdown"], ["--markdown", "--json"]])
def test_diff_refuses_json_and_markdown_together(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
) -> None:
    # The two report forms are one another's negation: refused as
    # bad input before any document is read, and the whole line is pinned,
    # bytes for bytes.
    code = _run(monkeypatch, ["diff", "old.yaml", "new.yaml", *flags])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err == (
        "gpai-docs: error: --json and --markdown are mutually exclusive\n"
    )


@pytest.mark.parametrize(
    ("name", "text", "fragment"),
    [
        ("absent", None, "cannot read"),
        ("v2", "schema: 2\n", "unsupported schema"),
        ("list", "schema: 1\nannex_xi:\n  - intended_tasks\n", "must be a mapping"),
        (
            "duplicated",
            "schema: 1\nannex_xi:\n  a_key: 1\n  a_key: 2\n",
            "duplicate key",
        ),
    ],
    ids=["missing-file", "unsupported-schema", "non-mapping-annex", "duplicate-key"],
)
def test_diff_maps_a_bad_document_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    name: str,
    text: str | None,
    fragment: str,
) -> None:
    # Each input loads through the ordinary loader, whose refusals
    # are the shared bad input (exit 2, the error prefix naming the file); a
    # parser refusal may carry the reader's own multi-line mark.
    path = (
        tmp_path / "absent.yaml"
        if text is None
        else _document(tmp_path, f"{name}.yaml", text)
    )

    code = _run(monkeypatch, ["diff", str(path), str(EXAMPLE_DOCUMENT)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith("gpai-docs: error: ")
    assert fragment in captured.err


def test_diff_loads_the_old_version_before_the_new_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Both sides load in argument order, so when both are bad the first
    # refusal is the one reported.
    new = _document(tmp_path, "new.yaml", "schema: 2\n")

    code = _run(monkeypatch, ["diff", str(tmp_path / "absent.yaml"), str(new)])
    captured = capsys.readouterr()

    assert code == 2
    assert "cannot read" in captured.err


def test_schema_prints_no_findings_footer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The run-level footer closes findings runs (registry verify, lint); a
    # schema dump is not a findings report and carries no footer.
    code = _run(monkeypatch, ["schema"])

    assert code == 0
    assert FOOTER not in capsys.readouterr().out


@pytest.mark.parametrize("case", ["directory", "missing-parent"])
def test_schema_maps_an_unwritable_out_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: str,
) -> None:
    # A --out the process cannot write is bad input (2): one line naming the
    # target, not an OSError traceback. A directory and a missing parent are
    # the two deterministic cases.
    target = tmp_path if case == "directory" else tmp_path / "absent" / "schema.json"

    code = _run(monkeypatch, ["schema", "--out", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: cannot write ")
    assert str(target) in captured.err


# import-docx: the filled Form package into a document, mapped through the
# layer's ``answers`` rather than the walker's raw ``response`` text; the
# summary is one line on stderr and bad input is exit 2 with nothing written.


def _filled_form(tmp_path: Path) -> Path:
    """One filled synthetic Form: an architecture row and an amount row."""
    return write_form_docx(
        tmp_path / "form.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture:",
                response="a transformer architecture",
                crosses=ALL_CROSSES,
            ),
            Row(heading="Computational resources (during training)"),
            Row(
                label="Amount of computation used for training:",
                response="2.3e+25",
                crosses={"nca": True},
            ),
        ],
    )


# What that form maps to: the architecture answer fills its field in both
# annexes, and the literal amount becomes the compute element's number.
_FILLED_DOCUMENT = {
    "schema": 1,
    "annex_xi": {
        "architecture_and_parameters": "a transformer architecture",
        "computational_resources": {"training_flop": 2.3e25},
    },
    "annex_xii": {"architecture_and_parameters": "a transformer architecture"},
}


def test_import_docx_writes_the_document_as_yaml_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # The default run: the document YAML on stdout (deterministic, the
    # dumper's bytes) and the mapping summary on stderr; ``-o -`` names stdout
    # too and prints the same bytes.
    package = _filled_form(tmp_path)

    code = _run(monkeypatch, ["import-docx", str(package)])
    captured = capsysbinary.readouterr()

    assert code == 0
    assert captured.out == dump_document_yaml(_FILLED_DOCUMENT).encode("utf-8")
    assert captured.out.endswith(b"\n") and not captured.out.endswith(b"\n\n")
    assert yaml.safe_load(captured.out.decode("utf-8")) == _FILLED_DOCUMENT
    assert captured.err == b"mapped 2 rows to 3 fields; skipped 0 rows\n"

    assert _run(monkeypatch, ["import-docx", str(package), "-o", "-"]) == 0
    assert capsysbinary.readouterr() == captured


def test_an_imported_document_lints_with_its_unwritten_fields_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The import is lint's input: one Use row fills its field in both
    # annexes, so the only findings are the missing ones for the fields the
    # form left unanswered; the Section 2 fields are skipped, an
    # imported document carrying no systemic-risk marker.
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(heading="Use"),
            Row(
                label="Intended uses:",
                response="serve coffee",
                crosses=ALL_CROSSES,
            ),
        ],
    )
    target = tmp_path / "imported.yaml"

    assert _run(monkeypatch, ["import-docx", str(package), "-o", str(target)]) == 0

    registry = load()
    findings = lint(load_document(target), registry)
    written = {"annex_xi.intended_tasks", "annex_xii.intended_tasks"}
    assert all(finding.kind == "missing" for finding in findings)
    assert {finding.location for finding in findings} == {
        field.model_field for field in registry.fields if field.condition is None
    } - written


def test_import_docx_out_file_carries_the_stdout_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # -o moves the output, it does not change it: the file carries the bytes
    # the stdout run prints, and the summary still reaches stderr.
    package = _filled_form(tmp_path)
    assert _run(monkeypatch, ["import-docx", str(package)]) == 0
    stdout_run = capsysbinary.readouterr()
    target = tmp_path / "imported.yaml"

    assert _run(monkeypatch, ["import-docx", str(package), "-o", str(target)]) == 0
    captured = capsysbinary.readouterr()

    assert captured.out == b""
    assert captured.err == stdout_run.err
    assert target.read_bytes() == stdout_run.out


def test_import_docx_out_json_writes_the_json_twin(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # A .json -o path writes the plain JSON spelling of the same document:
    # indent 2, one trailing newline, with no refusal walk between it and
    # json.dumps (the import output is JSON-native by construction).
    package = _filled_form(tmp_path)
    target = tmp_path / "imported.json"

    assert _run(monkeypatch, ["import-docx", str(package), "-o", str(target)]) == 0
    captured = capsysbinary.readouterr()

    assert captured.out == b""
    assert captured.err == b"mapped 2 rows to 3 fields; skipped 0 rows\n"
    text = target.read_text(encoding="utf-8")
    assert text == json.dumps(_FILLED_DOCUMENT, indent=2) + "\n"
    assert json.loads(text) == _FILLED_DOCUMENT


def test_an_empty_import_writes_the_skeleton_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # Nothing to import is a fact, not an error: the skeleton
    # goes out, the summary names the located row no field draws on, and the
    # exit stays 0.
    package = write_form_docx(
        tmp_path / "blank.docx",
        [
            Row(heading="General information"),
            Row(label="Legal name for the model provider", crosses=ALL_CROSSES),
        ],
    )

    code = _run(monkeypatch, ["import-docx", str(package)])
    captured = capsysbinary.readouterr()

    assert code == 0
    assert captured.out == b"schema: 1\n"
    assert captured.err == b"mapped 0 rows to 0 fields; skipped 1 rows\n"


def test_the_summary_notes_duplicate_shaped_rows(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # A shape the form carries twice: the first match wins and the second is
    # the duplicate shape the summary line notes.
    package = write_form_docx(
        tmp_path / "duplicated.docx",
        [
            Row(heading="Use"),
            Row(label="Intended uses:", response="first answer", crosses=ALL_CROSSES),
            Row(
                label="Intended uses:",
                response="second answer",
                crosses=ALL_CROSSES,
            ),
        ],
    )

    code = _run(monkeypatch, ["import-docx", str(package)])
    captured = capsysbinary.readouterr()

    assert code == 0
    assert captured.err == (
        b"mapped 1 rows to 2 fields; skipped 0 rows; noting 1 duplicate-shaped rows\n"
    )
    document = yaml.safe_load(captured.out.decode("utf-8"))
    assert document["annex_xi"]["intended_tasks"] == "first answer"
    assert document["annex_xii"]["intended_tasks"] == "first answer"


def test_a_verbatim_number_like_string_is_quoted_and_reloads_as_a_string(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # The writer must quote the strings the reader's 1.2-core grammar would
    # construct as numbers: an amount text with no finite double and a method
    # text that spells an octal both stay strings through write and reload
    # (PyYAML's own dumper would leave them plain).
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(heading="Computational resources (during training)"),
            Row(
                label="Amount of computation used for training:",
                response="1e400",
                crosses={"nca": True},
            ),
            Row(
                label="Measurement methodology:",
                response="0o17",
                crosses={"ai_office": True, "nca": True},
            ),
        ],
    )
    target = tmp_path / "imported.yaml"

    code = _run(monkeypatch, ["import-docx", str(package), "-o", str(target)])
    captured = capsysbinary.readouterr()

    assert code == 0
    text = target.read_text(encoding="utf-8")
    assert "training_flop: '1e400'\n" in text
    assert "estimation_method: '0o17'\n" in text
    reloaded = load_document(target)
    section = reloaded.values["annex_xi"]
    assert isinstance(section, dict)
    resources = section["computational_resources"]
    assert isinstance(resources, dict)
    assert resources["training_flop"] == "1e400"
    assert resources["estimation_method"] == "0o17"
    assert captured.err == b"mapped 2 rows to 1 fields; skipped 0 rows\n"


def test_import_docx_maps_an_unreadable_package_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The input half of the exit-2 cases: a missing file, a non-zip, a package
    # without word/document.xml and a malformed document part each read as
    # one line naming the path, exit 2, stdout clean.
    malformed = write_package(tmp_path / "malformed.docx", "<w:document")
    no_part = tmp_path / "no-part.docx"
    with zipfile.ZipFile(no_part, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
    not_a_zip = tmp_path / "not-a-zip.docx"
    not_a_zip.write_text("this is not a zip file", encoding="utf-8")

    for path in (tmp_path / "absent.docx", not_a_zip, no_part, malformed):
        code = _run(monkeypatch, ["import-docx", str(path)])
        captured = capsys.readouterr()

        assert code == 2, path
        assert captured.out == ""
        assert captured.err.count("\n") == 1
        assert captured.err.startswith("gpai-docs: error: ")
        assert str(path) in captured.err


@pytest.mark.parametrize("case", ["directory", "missing-parent"])
def test_import_docx_maps_an_unwritable_out_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: str,
) -> None:
    # The output half: a directory and a missing parent are the two
    # deterministic unwritable targets, and neither leaves the summary on
    # stderr (the run failed before it mapped anything).
    package = _filled_form(tmp_path)
    target = tmp_path if case == "directory" else tmp_path / "absent" / "out.yaml"

    code = _run(monkeypatch, ["import-docx", str(package), "-o", str(target)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: cannot write ")
    assert str(target) in captured.err


def test_import_docx_help_states_the_exit_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exit contract is part of the command's interface, as extract's help
    # names its own; Rich may wrap the line, so the assertion reads the words
    # with whitespace collapsed.
    code = _run(monkeypatch, ["import-docx", "--help"])
    words = " ".join(_strip_ansi(capsys.readouterr().out).split())

    assert code == 0
    assert (
        "Exit codes: 0 document written (the skeleton when nothing maps), "
        "2 bad input" in words
    )


# export-docx: the document into a copy of the blank Form.


def _export_template(tmp_path: Path, name: str = "blank.docx") -> Path:
    """One fillable synthetic Form: the intended-tasks answer field alone."""
    return write_form_docx(
        tmp_path / name,
        [
            Row(heading="Use"),
            Row(
                label="Intended uses",
                response="Click here to add text.",
                response_style="Style2",
                crosses=ALL_CROSSES,
            ),
        ],
    )


def _exportable_document(tmp_path: Path, name: str = "model-docs.yaml") -> Path:
    """One native document the synthetic template can carry."""
    document = tmp_path / name
    document.write_text(
        dump_document_yaml(
            {"schema": 1, "annex_xi": {"intended_tasks": "serve coffee"}}
        ),
        encoding="utf-8",
    )
    return document


def test_the_docx_commands_are_registered_with_their_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Both commands are on the app's own surface, and each help spells the
    # documented usage. The usage line's command part is asserted, not Click's
    # derived prog name: under ``python -m pytest`` that name would make the
    # test depend on how the runner was invoked.
    assert _run(monkeypatch, ["--help"]) == 0
    listed = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "import-docx" in listed and "export-docx" in listed

    assert _run(monkeypatch, ["import-docx", "--help"]) == 0
    import_help = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "Usage:" in import_help
    assert "import-docx [OPTIONS] {form}" in import_help
    assert "-o" in import_help

    assert _run(monkeypatch, ["export-docx", "--help"]) == 0
    export_help = " ".join(_strip_ansi(capsys.readouterr().out).split())
    assert "Usage:" in export_help
    assert "export-docx [OPTIONS] {document}" in export_help
    assert "-o" in export_help and "--template" in export_help


def test_export_docx_writes_the_filled_copy_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # The success path: the value lands in the template's row through the
    # same walk the import runs, the run is silent on both streams, and the
    # template itself is untouched (its placeholder still reads absent).
    template = _export_template(tmp_path)
    document = _exportable_document(tmp_path)
    out = tmp_path / "filled.docx"

    code = _run(
        monkeypatch,
        ["export-docx", str(document), "-o", str(out), "--template", str(template)],
    )
    captured = capsysbinary.readouterr()

    assert code == 0
    assert captured.out == b"" and captured.err == b""
    registry = load()
    assert locate_rows(read_rows(out), registry)["use/intended-uses"] == "serve coffee"
    assert locate_rows(read_rows(template), registry)["use/intended-uses"] == ""


def test_export_docx_requires_the_template(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # --template is required, and the check comes before anything is read:
    # the document path names nothing either, yet the run reports the missing
    # option alone, exit 2, nothing written.
    out = tmp_path / "filled.docx"

    code = _run(
        monkeypatch, ["export-docx", str(tmp_path / "absent.yaml"), "-o", str(out)]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err == "gpai-docs: error: --template is required\n"
    assert not out.exists()


def test_export_docx_maps_an_unreadable_template_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The template half of the exit-2 matrix: a missing file, a non-zip, a
    # package without word/document.xml, a malformed document part and a
    # package whose rows are none of the Form's each read as one line naming
    # the path, exit 2, stdout clean, nothing written.
    malformed = write_package(tmp_path / "malformed.docx", "<w:document")
    no_part = tmp_path / "no-part.docx"
    with zipfile.ZipFile(no_part, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
    not_a_zip = tmp_path / "not-a-zip.docx"
    not_a_zip.write_text("this is not a zip file", encoding="utf-8")
    foreign = write_form_docx(
        tmp_path / "other.docx", [Row(label="Some other form row", response="x")]
    )
    document = _exportable_document(tmp_path)
    out = tmp_path / "filled.docx"

    for template in (tmp_path / "absent.docx", not_a_zip, malformed, no_part, foreign):
        code = _run(
            monkeypatch,
            [
                "export-docx",
                str(document),
                "-o",
                str(out),
                "--template",
                str(template),
            ],
        )
        captured = capsys.readouterr()

        assert code == 2, template
        assert captured.out == ""
        assert captured.err.count("\n") == 1
        assert captured.err.startswith("gpai-docs: error: ")
        assert str(template) in captured.err
        assert not out.exists()


def test_export_docx_maps_an_unreadable_document_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # The document half: a missing file, a file without the schema marker and
    # a value the renderer cannot read are each exit 2, one line, stdout
    # clean, nothing written; a valid template never rescues them.
    template = _export_template(tmp_path)
    unmarked = tmp_path / "unmarked.yaml"
    unmarked.write_text("annex_xi:\n  licence: MIT\n", encoding="utf-8")
    unreadable_value = tmp_path / "unreadable.yaml"
    unreadable_value.write_text(
        "schema: 1\nannex_xi:\n  licence:\n    - a\n", encoding="utf-8"
    )
    out = tmp_path / "filled.docx"

    for document in (tmp_path / "absent.yaml", unmarked, unreadable_value):
        code = _run(
            monkeypatch,
            [
                "export-docx",
                str(document),
                "-o",
                str(out),
                "--template",
                str(template),
            ],
        )
        captured = capsys.readouterr()

        assert code == 2, document
        assert captured.out == ""
        assert captured.err.count("\n") == 1
        assert captured.err.startswith("gpai-docs: error: ")
        assert not out.exists()


@pytest.mark.parametrize("case", ["directory", "missing-parent"])
def test_export_docx_maps_an_unwritable_out_to_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: str,
) -> None:
    # The output half, mirroring import's: a directory and a missing parent
    # are the two deterministic unwritable targets; the template stays
    # byte-identical.
    template = _export_template(tmp_path)
    document = _exportable_document(tmp_path)
    target = tmp_path if case == "directory" else tmp_path / "absent" / "out.docx"
    before = template.read_bytes()

    code = _run(
        monkeypatch,
        ["export-docx", str(document), "-o", str(target), "--template", str(template)],
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("gpai-docs: error: cannot write ")
    assert str(target) in captured.err
    assert template.read_bytes() == before


def test_export_docx_refuses_to_write_over_the_template(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # -o naming the template is refused (the blank Form is the user's and is
    # never modified): one line, exit 2, the template's bytes untouched.
    template = _export_template(tmp_path)
    document = _exportable_document(tmp_path)
    before = template.read_bytes()

    code = _run(
        monkeypatch,
        [
            "export-docx",
            str(document),
            "-o",
            str(template),
            "--template",
            str(template),
        ],
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith(
        "gpai-docs: error: refusing to overwrite the template"
    )
    assert template.read_bytes() == before


def test_export_docx_help_states_the_exit_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(monkeypatch, ["export-docx", "--help"])
    words = " ".join(_strip_ansi(capsys.readouterr().out).split())

    assert code == 0
    assert "Exit codes: 0 filled copy written, 2 bad input" in words
