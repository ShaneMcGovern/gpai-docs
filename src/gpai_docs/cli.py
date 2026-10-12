"""Command-line entry point: a Typer app over the registry pipeline.

``main()`` turns Typer's standalone ``SystemExit`` into the shared exit
contract (0 no findings, 1 findings, 2 bad input) and reports
registry and document defects; each command's ``--help`` carries the rest.
"""

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from gpai_docs.diff import (
    changes_json,
    changes_markdown,
    diff_documents,
    render_changes,
)
from gpai_docs.documents import DocumentError, dump_document_yaml, load_document
from gpai_docs.docxform import (
    DocxError,
    build_document,
    count_duplicate_rows,
    document_values_for_rows,
    locate_rows,
    read_rows,
    summarise,
    write_form,
)
from gpai_docs.export import cyclonedx_bom, cyclonedx_json, hf_card_markdown
from gpai_docs.extract import annex_xii_subset, subset_json, subset_yaml
from gpai_docs.lint import lint, render_finding
from gpai_docs.lint.findings import FOOTER
from gpai_docs.models import ModelDocument
from gpai_docs.registry import RegistryError, exit_code, load, verify
from gpai_docs.registry.fetch import UrllibFetcher, run_fetch
from gpai_docs.report import findings_markdown

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Check EU AI Act GPAI documentation against the traced registry.",
)
registry_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Fetch and verify the registry's source texts.",
)
app.add_typer(registry_app, name="registry")
extract_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Write a document's downstream subsets.",
)
app.add_typer(extract_app, name="extract")
export_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Write a document's exchange-format projections.",
)
app.add_typer(export_app, name="export")


def _checked_timeout(timeout: float) -> float:
    """Reject a ``--timeout`` the socket layer would raise on.

    An uncaught ``ValueError`` would escape ``main()``'s exit contract as a
    traceback instead of the exit 2 bad input owes.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise typer.BadParameter(
            "--timeout must be a positive, finite number of seconds"
        )
    return timeout


def _checked_report_flags(json_output: bool, markdown: bool) -> None:
    """Refuse ``--json`` with ``--markdown`` before any read: bad input."""
    if json_output and markdown:
        print(
            "gpai-docs: error: --json and --markdown are mutually exclusive",
            file=sys.stderr,
        )
        raise typer.Exit(2)


@registry_app.command("fetch")
def fetch(
    write: Annotated[
        bool, typer.Option("--write", help="Persist the regenerated sources.yaml.")
    ] = False,
    celex: Annotated[
        str | None,
        typer.Option("--celex", help="Only re-fetch sources pinned to this CELEX."),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the report as JSON on stdout.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Per-request timeout in seconds.")
    ] = 30.0,
) -> None:
    """Re-fetch extract-mode sources and report what changed (dry run by default)."""
    timeout = _checked_timeout(timeout)
    registry = load()
    report = run_fetch(
        registry, UrllibFetcher(), celex=celex, write=write, timeout=timeout
    )
    if json_output:
        print(json.dumps(asdict(report), indent=2))
    else:
        # The element-inventory diff is the human review aid.
        if report.inventory_added:
            print("inventory added: " + ", ".join(report.inventory_added))
        if report.inventory_removed:
            print("inventory removed: " + ", ".join(report.inventory_removed))
    # A source that could not be re-fetched or re-extracted is a finding.
    if report.failed:
        raise typer.Exit(1)


@registry_app.command("verify")
def verify_registry(
    online: Annotated[
        bool,
        typer.Option("--online", help="Re-fetch the live sources and compare."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the report as JSON on stdout.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Per-request timeout in seconds.")
    ] = 30.0,
) -> None:
    """Check the stored registry, and with --online the live sources."""
    timeout = _checked_timeout(timeout)
    registry = load()
    report = verify(
        registry,
        online=online,
        fetcher=UrllibFetcher() if online else None,
        timeout=timeout,
    )
    if json_output:
        print(json.dumps(asdict(report), indent=2))
    else:
        for finding in report.findings:
            print(f"{finding.kind.value}: {finding.target}: {finding.message}")
        summary = "no findings" if report.ok else f"{len(report.findings)} findings"
        print(f"{summary} - {FOOTER}")
    raise typer.Exit(exit_code(report))


@app.command("lint")
def lint_document(
    document: Annotated[
        Path, typer.Argument(help="Native YAML or JSON document to check.")
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the findings as JSON on stdout.")
    ] = False,
    markdown: Annotated[
        bool,
        typer.Option("--markdown", help="Emit the findings as a Markdown report."),
    ] = False,
) -> None:
    """Check a document: missing, malformed, unknown and inconsistent findings."""
    _checked_report_flags(json_output, markdown)
    registry = load()
    findings = lint(load_document(document), registry)
    if json_output:
        payload = {"findings": [asdict(finding) for finding in findings]}
        print(json.dumps(payload, indent=2))
    elif markdown:
        print(findings_markdown(findings, registry))
    else:
        for finding in findings:
            print(render_finding(finding, registry))
        summary = "no findings" if not findings else f"{len(findings)} findings"
        print(f"{summary} - {FOOTER}")
    raise typer.Exit(1 if findings else 0)


# The human diff run's closing note: validity is lint's to judge.
_LINT_NOTE = (
    "note: values are reported in the renderers' canonical form; "
    "validity is for gpai-docs lint to check"
)


@app.command("diff")
def diff_versions(
    old: Annotated[Path, typer.Argument(help="The earlier document version.")],
    new: Annotated[Path, typer.Argument(help="The later document version.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the changes as JSON on stdout.")
    ] = False,
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Emit the changes as a Markdown table.")
    ] = False,
) -> None:
    """Compare two document versions with the registry's vocabulary.

    Exit codes follow diff(1): 0 no differences, 1 differences found, 2 bad
    input; usable as a CI documentation-change gate. Values are reported in
    the renderers' canonical form; validity is lint's to check.
    """
    _checked_report_flags(json_output, markdown)
    registry = load()
    changes = diff_documents(load_document(old), load_document(new), registry)
    if json_output:
        print(json.dumps(changes_json(changes), indent=2))
    elif markdown:
        print(changes_markdown(changes))
    elif changes:
        # The note closes only a run with values to read: an identical pair
        # prints nothing at all, the diff(1) way.
        print(render_changes(changes))
        print(_LINT_NOTE)
    raise typer.Exit(1 if changes else 0)


@app.command("schema")
def schema_document(
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write the schema to this path, not stdout."),
    ] = None,
) -> None:
    """Print the document JSON Schema (v0.1) the models project."""
    # One dump of the models' own schema (draft 2020-12), so stdout and
    # --out carry the same bytes.
    schema = json.dumps(ModelDocument.model_json_schema(), indent=2)
    if out is None:
        print(schema)
        return
    try:
        out.write_text(schema + "\n", encoding="utf-8")
    except OSError as error:
        # An unwritable target is bad input (2), in the shared error style.
        print(f"gpai-docs: error: cannot write {out}: {error}", file=sys.stderr)
        raise typer.Exit(2) from error


@extract_app.command("annex-xii")
def extract_annex_xii(
    document: Annotated[
        Path, typer.Argument(help="Native YAML or JSON document to extract from.")
    ],
    out: Annotated[
        Path | None,
        typer.Option(
            "-o",
            help="Write here (.json for the JSON twin); - or absent writes stdout.",
        ),
    ] = None,
) -> None:
    """Write the schema-1 document holding only the Annex XII values.

    Exit codes: 0 subset written, 1 nothing to extract (no Annex XII
    values), 2 bad input; nothing is written on 1 or 2.
    """
    subset = annex_xii_subset(load_document(document))
    if not subset["annex_xii"]:
        # Nothing to extract is a CI-relevant condition, not success and not
        # bad input: exit 1. An empty section is the condition; a section of
        # blank values still extracts verbatim.
        print(
            f"gpai-docs: {document} carries no Annex XII values; nothing to extract",
            file=sys.stderr,
        )
        raise typer.Exit(1)
    json_twin = out is not None and out.suffix.lower() == ".json"
    try:
        text = subset_json(subset) if json_twin else subset_yaml(subset)
    except (TypeError, ValueError, RecursionError) as error:
        # Content the twin cannot write faithfully is bad input (2): one
        # line, nothing written.
        twin = "JSON" if json_twin else "YAML"
        print(
            f"gpai-docs: error: cannot write the {twin} twin of {document}: {error}",
            file=sys.stderr,
        )
        raise typer.Exit(2) from error
    if out is None or str(out) == "-":
        sys.stdout.write(text)
        return
    try:
        out.write_text(text, encoding="utf-8")
    except OSError as error:
        # The shared unwritable-target refusal.
        print(f"gpai-docs: error: cannot write {out}: {error}", file=sys.stderr)
        raise typer.Exit(2) from error


@app.command("import-docx")
def import_docx(
    form: Annotated[
        Path, typer.Argument(help="The filled Model Documentation Form .docx package.")
    ],
    out: Annotated[
        Path | None,
        typer.Option(
            "-o",
            help="Write here (.json for the JSON twin); - or absent writes stdout.",
        ),
    ] = None,
) -> None:
    """Read a filled Form package into a native document.

    Every row is read through the mapping layer's ANSWER text (never the
    walker's raw response, which also carries the form's guidance), located
    against the registry's rows and built in registry order. The document is
    written as YAML by default and as the plain JSON spelling for a ``.json``
    ``-o``; the one-line mapping summary goes to stderr.

    Exit codes: 0 document written (the skeleton when nothing maps), 2 bad
    input: an unreadable package or an unwritable ``-o``.
    """
    registry = load()
    walked = read_rows(form)
    located = locate_rows(walked, registry)
    summary = summarise(
        located, registry, duplicate_rows=count_duplicate_rows(walked, registry)
    )
    document = build_document(located, registry)
    json_twin = out is not None and out.suffix.lower() == ".json"
    text = (
        json.dumps(document, indent=2) + "\n"
        if json_twin
        else dump_document_yaml(document)
    )
    if out is None or str(out) == "-":
        sys.stdout.write(text)
    else:
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as error:
            # The shared unwritable-target refusal.
            print(f"gpai-docs: error: cannot write {out}: {error}", file=sys.stderr)
            raise typer.Exit(2) from error
    summary_line = (
        f"mapped {summary.rows_mapped} rows to {summary.fields_written} fields; "
        f"skipped {summary.rows_skipped} rows"
    )
    if summary.duplicate_rows:
        # The note rides the line only when there is one, so a clean import's
        # summary stays byte-stable.
        summary_line += f"; noting {summary.duplicate_rows} duplicate-shaped rows"
    print(summary_line, file=sys.stderr)


@app.command("export-docx")
def export_docx(
    document: Annotated[
        Path, typer.Argument(help="Native YAML or JSON document to export.")
    ],
    out: Annotated[Path, typer.Option("-o", help="Write the filled Form copy here.")],
    template: Annotated[
        Path | None,
        typer.Option(
            "--template",
            help="The blank Model Documentation Form .docx to fill (required).",
        ),
    ] = None,
) -> None:
    """Write a document's values into a copy of the blank Form.

    The blank Form is the user's own (obtained from the Commission, passed
    with the required ``--template``, and never redistributed), and it is
    never modified: the filled copy goes to ``-o`` alone. Each carried value
    is written into its row's response field through the same walk the import
    reads; a package without a recognisable Form row is refused.

    Exit codes: 0 filled copy written, 2 bad input (a missing ``--template``,
    an unreadable template or document, a package with no known Form row, an
    unwritable ``-o``), with nothing written.
    """
    if template is None:
        # Named before anything is read, in the shared one-line style.
        print("gpai-docs: error: --template is required", file=sys.stderr)
        raise typer.Exit(2)
    registry = load()
    values = document_values_for_rows(load_document(document), registry)
    try:
        write_form(template, values, out, registry=registry)
    except OSError as error:
        # write_form reads the template itself, so an escaping OSError is the
        # write failing, and nothing was written.
        print(f"gpai-docs: error: cannot write {out}: {error}", file=sys.stderr)
        raise typer.Exit(2) from error


def _write_projection(text: str, out: Path | None) -> None:
    """Write a projection to ``-o`` (stdout for absent or ``-``).

    An unwritable target is bad input (2), in the shared one-line style.
    """
    if out is None or str(out) == "-":
        sys.stdout.write(text)
        return
    try:
        out.write_text(text, encoding="utf-8")
    except OSError as error:
        print(f"gpai-docs: error: cannot write {out}: {error}", file=sys.stderr)
        raise typer.Exit(2) from error


@export_app.command("hf-card")
def export_hf_card(
    document: Annotated[
        Path, typer.Argument(help="Native YAML or JSON document to export.")
    ],
    out: Annotated[
        Path | None,
        typer.Option("-o", help="Write here; - or absent writes stdout."),
    ] = None,
) -> None:
    """Write a Hugging Face-style model card projection of the document.

    The card is registry-driven and lossy by design: the frontmatter carries
    the document's own facts and the body one section per mapped Form group,
    each value preceded by its ``<!-- annex: ... -->`` traceability comment.
    Fields the Form does not carry (Annex XI Section 2's row-less fields)
    have no group to ride and are omitted.

    Exit codes: 0 card written, 2 bad input (an unreadable document, content
    the card cannot write, an unwritable -o), with nothing written.
    """
    registry = load()
    try:
        text = hf_card_markdown(load_document(document), registry)
    except (TypeError, ValueError, RecursionError) as error:
        print(
            f"gpai-docs: error: cannot write the model card of {document}: {error}",
            file=sys.stderr,
        )
        raise typer.Exit(2) from error
    _write_projection(text, out)


@export_app.command("cyclonedx")
def export_cyclonedx(
    document: Annotated[
        Path, typer.Argument(help="Native YAML or JSON document to export.")
    ],
    out: Annotated[
        Path | None,
        typer.Option("-o", help="Write here; - or absent writes stdout."),
    ] = None,
) -> None:
    """Write a CycloneDX 1.6 BOM projection of the document.

    Every present fact becomes a ``gpai-docs:annex:<id>`` traceability
    property, the row-less Section 2 fields included. Content JSON cannot
    carry is refused through the same walk the extract twin uses, before
    anything is written.

    Exit codes: 0 BOM written, 2 bad input (an unreadable document, content
    the BOM cannot write, an unwritable -o), with nothing written.
    """
    registry = load()
    try:
        text = cyclonedx_json(cyclonedx_bom(load_document(document), registry))
    except (TypeError, ValueError, RecursionError) as error:
        print(
            f"gpai-docs: error: cannot write the CycloneDX BOM of {document}: {error}",
            file=sys.stderr,
        )
        raise typer.Exit(2) from error
    _write_projection(text, out)


def main() -> int:
    """Run the CLI and return the shared exit code."""
    code = 0
    try:
        app()
    except SystemExit as exit_status:
        code = exit_status.code if isinstance(exit_status.code, int) else 0
    except (RegistryError, DocumentError, DocxError) as error:
        print(f"gpai-docs: error: {error}", file=sys.stderr)
        code = 2
    return code
