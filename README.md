# gpai-docs

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.13.15](https://img.shields.io/badge/python-3.13.15-blue.svg)](https://www.python.org/downloads/)
[![Validate](https://github.com/ShaneMcGovern/gpai-docs/actions/workflows/validate.yml/badge.svg)](https://github.com/ShaneMcGovern/gpai-docs/actions/workflows/validate.yml)
[![Coverage](badges/coverage.svg)](badges/coverage.svg)
[![uv](https://img.shields.io/badge/uv-package%20manager-green.svg)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/badge/ruff-linted-261230.svg)](https://github.com/astral-sh/ruff)

Check EU AI Act GPAI model documentation: `gpai-docs` reads a provider's
documentation as one YAML or JSON file, compares it with a field registry
of every element Article 53 and Annexes XI and XII of Regulation (EU)
2024/1689 require for general-purpose AI models, and reports what is
missing, malformed, unknown or inconsistent. Every finding is traced to
the verbatim provision it rests on, stored with its source record (a
CELEX pin where the source has one), its retrieval date and a SHA-256 in
the registry that ships with the tool. It also
compares document versions, converts to and from the Commission's Model
Documentation Form, and exports projections for a model card or a
CycloneDX BOM. The registry travels with the repository, so the checks run
offline.

The tool issues findings, not verdicts. `lint` and `registry verify` close
every run by saying what it is - engineering evidence, not a compliance
verdict - and nothing here certifies that any model complies with
anything.

## Installation

**From source, until publication.** Clone the repository and open it in
its dev container: [Docker](https://docs.docker.com/get-docker/),
[VS Code](https://code.visualstudio.com/) and the
[Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers),
and no Python or uv on the host. The container syncs the environment on
first start, and everything runs through `uv run`:

```bash
git clone https://github.com/ShaneMcGovern/gpai-docs
cd gpai-docs
# inside the dev container:
uv run gpai-docs lint tests/fixtures/model-docs-example.yaml
```

> **Pending publication.** `gpai-docs` is not published to PyPI, and the
> container image is not published to a registry, yet; publication is the
> maintainer's pending decision. Until it lands, `pip install gpai-docs`
> and `docker pull` have nothing to fetch, and
> [the action](#use-it-in-ci) cannot run its install step. Install from
> source, above, until this note is replaced.

[CONTRIBUTING.md](CONTRIBUTING.md) covers the container, the quality gate,
and the everyday commands for changing the project.

## Quick start

The repository ships a complete annotated document,
`tests/fixtures/model-docs-example.yaml`, that answers every element of
the registry. Lint it:

```bash
uv run gpai-docs lint tests/fixtures/model-docs-example.yaml
```

```text
no findings - engineering evidence, not a compliance verdict
```

`lint` exits 0 when a document is clean, 1 when it has findings, and 2 on
bad input, so it drops straight into a CI step.

An incomplete document reports each gap with its citation. This one answers
a single element and misspells a key:

```bash
cat > /tmp/incomplete.yaml <<'YAML'
schema: 1
annex_xi:
  intended_tasks: "Text generation and summarisation."
  training_datasets: "Web text, books and licensed corpora."
YAML
uv run gpai-docs lint /tmp/incomplete.yaml
```

```text
[MISSING] XI.1.1.b - Acceptable use policies
  Key: annex_xi.acceptable_use_policies
  Annex XI, Section 1, point 1(b) - owed to: AI Office, NCAs
  Form rows: use/acceptable-use-policy
  Form audience flags: ai_office, nca, downstream
  "the acceptable use policies applicable;"
  Guidance: State the acceptable use policies that apply to the model.
```

Every other unanswered element follows the same shape; the run then ends
with a one-line `[UNKNOWN]` finding naming the misspelled key, and closes
with `22 findings - engineering evidence, not a compliance verdict` before
exiting 1. `--json` emits the findings as data; `--markdown` renders the
report as a Markdown document for a pull request or a job summary.

## What you can do

### Check a document

`gpai-docs lint <document>` runs the four passes - completeness against
the registry, shape and type checks, unknown-key detection, and the
consistency rules - and cites the provision behind every finding that
rests on an element; a finding about a key the registry does not name, or
about a record field below an element, carries the path and the reason
instead. The
[authoring guide](docs/authoring.md) covers the document format and what
each finding kind means; [docs/methodology.md](docs/methodology.md) states
what the registry can and cannot establish.

### Compare two versions

`gpai-docs diff <old> <new>` reports what changed between two document
versions in the registry's vocabulary, with values in their canonical
form and no judgment: validity is `lint`'s to check. The exit codes follow
`diff(1)`, so a documentation change can gate a pipeline:

```bash
cp tests/fixtures/model-docs-example.yaml /tmp/updated.yaml
# ...edit one value in /tmp/updated.yaml...
uv run gpai-docs diff tests/fixtures/model-docs-example.yaml /tmp/updated.yaml
```

```text
~ annex_xi.computational_resources: {"estimation_method":"Extrapolated from the provider's published training report; no measured figure was released.","training_flop":"2.5e+25","training_time":"21 days on 4,096 accelerators."} -> {"estimation_method":"Extrapolated from the provider's published training report; no measured figure was released.","training_flop":"2.5e+25","training_time":"28 days on 4,096 accelerators."}
note: values are reported in the renderers' canonical form; validity is for gpai-docs lint to check
```

### Work with the Form

The Commission's Model Documentation Form is the Word document providers
use to record the same information; the tool moves between it and the
native format:

- `gpai-docs import-docx <form.docx> -o model-docs.yaml` reads a filled
  Form package into a native document.
- `gpai-docs export-docx model-docs.yaml -o filled.docx --template BLANK_FORM.docx`
  writes a document's values into a copy of the blank Form. The blank Form
  is the user's own, obtained from the Commission and passed with
  `--template`; it is never redistributed and never modified.
- `gpai-docs extract annex-xii model-docs.yaml -o annex-xii.yaml` writes
  the Annex XII subset (the information owed to downstream providers) as a
  document of its own.

[docs/form-docx-structure.md](docs/form-docx-structure.md) is the
inspection record of the Form's structure and its 46-row inventory.

### Export projections

- `gpai-docs export hf-card model-docs.yaml -o README.md` writes a
  Hugging Face-style model card: frontmatter with the document's facts,
  then one section per Form group, each value preceded by an
  `<!-- annex: ... -->` traceability comment.
- `gpai-docs export cyclonedx model-docs.yaml -o bom.json` writes a
  CycloneDX 1.6 BOM in which every present fact becomes a
  `gpai-docs:annex:<id>` property.

Both refuse content they cannot write faithfully rather than dropping it,
and both write to stdout when `-o` is `-` or absent.

### Keep the registry true

The registry is the tool's source of truth: 25 elements, each with its
verbatim provision text, its source record - a CELEX pin where the source
has one - and a SHA-256 of the stored text.

- `gpai-docs registry verify` re-hashes the stored registry offline (every
  CI run does this); `--online` re-fetches each pinned source and reports
  drift, including a newer consolidation layer.
- `gpai-docs registry fetch` re-fetches the machine-extracted sources and
  reports what changed, as a dry run unless `--write` persists it.
- `gpai-docs schema` prints the document JSON Schema the models project,
  for editors and pipelines; `--out PATH` writes it to a file.

Corrections to the registry, the format and the rules are logged in
[docs/errata.md](docs/errata.md), append-only, and each entry says how to
verify it.

## Commands

| Command | What it does | Exit codes |
| --- | --- | --- |
| `gpai-docs lint <document>` | The four checking passes, with citations; `--json` or `--markdown` for data and report output | 0 clean, 1 findings, 2 bad input |
| `gpai-docs diff <old> <new>` | The version diff, in the registry's vocabulary; `--json` or `--markdown` | diff(1): 0 none, 1 differences, 2 bad input |
| `gpai-docs extract annex-xii <document> -o <path>` | The Annex XII subset as a document | 0 written, 1 nothing to extract, 2 bad input |
| `gpai-docs import-docx <form.docx> -o <path>` | A filled Form package read into a native document | 0 written, 2 bad input |
| `gpai-docs export-docx <document> -o <path> --template <form.docx>` | A document's values written into a copy of the blank Form | 0 written, 2 bad input |
| `gpai-docs export hf-card <document> [-o <path>]` | A Hugging Face-style model-card projection | 0 written, 2 bad input |
| `gpai-docs export cyclonedx <document> [-o <path>]` | A CycloneDX 1.6 BOM projection | 0 written, 2 bad input |
| `gpai-docs schema [--out <path>]` | The document JSON Schema | 0 printed, 2 bad input |
| `gpai-docs registry verify [--online]` | The registry check: offline, or against the live sources | 0 clean, 1 findings, 2 bad input |
| `gpai-docs registry fetch [--write] [--celex <id>]` | Re-fetch the extract-mode sources; a dry run by default | 0 reported, 1 a source failed, 2 bad input |

`gpai-docs --help` lists them all; every subcommand takes `--help`.

## Use it in CI

`action.yml` wraps `gpai-docs lint` as a composite action: it sets up
Python, installs a released `gpai-docs`, and runs the linter over your
document. The step's outcome is the linter's: exit 1 (findings) fails the
step, exit 2 (bad input) fails it too. Findings stop a job unless the
caller sets `continue-on-error`, exactly as with any linter action.

```yaml
name: Lint the model documentation
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7.0.1
      - uses: ShaneMcGovern/gpai-docs@vX.Y.Z
        with:
          document: model-docs.yaml
          version: "X.Y.Z"
```

`@vX.Y.Z` and `version: "X.Y.Z"` are placeholders for a release tag: the
tags are on the
[releases page](https://github.com/ShaneMcGovern/gpai-docs/releases/latest).
Pin one there for a reproducible pipeline; `version` defaults to
`latest`, which installs unpinned.

| Input | Required | Default | What it does |
| --- | --- | --- | --- |
| `document` | yes | - | Path to the native YAML or JSON document to check |
| `args` | no | empty | Extra `lint` flags, for example `--markdown` |
| `version` | no | `latest` | The `gpai-docs` release to install |
| `python` | no | `3.13` | The interpreter to run it with |

The [pending-publication note](#installation) applies: the action's
install step needs `gpai-docs` on PyPI, which has not happened yet.

## Run it in Docker

The repository's Dockerfile builds the CLI as an image, for a pipeline
that has no GitHub Actions or no wish for one:

```bash
docker build --tag gpai-docs .
docker run --rm -v "$PWD:/work" gpai-docs lint /work/model-docs.yaml
```

The image mounts your working directory at `/work` and runs `gpai-docs`
as a non-root user; the exit codes are the same as the CLI's.

## Known limitations

- **Not published yet.** PyPI, a container registry and therefore the
  action's install step all wait on the publication decision.
- **One instrument, one language.** The registry covers the EU AI Act's
  documentation duties for GPAI models (Article 53; Annexes XI and XII;
  25 elements) in the Act's English text. It does not cover other
  instruments, other language versions, or other parts of the Act.
- **Guidance is cited, not law.** Where a consistency rule rests on the
  Commission's guidelines, the finding says so and quotes them; the
  guidelines are guidance.
- **No compliance verdict.** Findings and drift reports are evidence about
  a document, never a certification or a legal opinion.
- **Conditional elements.** The three Annex XI Section 2 elements apply
  only to a document that declares `systemic_risk: true`.
- **The Form round trip is yours.** The blank Form must come from the
  Commission; the repository never carries or redistributes it.

## Documentation

- **[Authoring guide](docs/authoring.md)** - the native document format,
  the typed values, and what each finding kind means
- **[Registry methodology](docs/methodology.md)** - what the registry can
  and cannot establish, the rules, the change process and the terms of
  reuse
- **[Form structure](docs/form-docx-structure.md)** - the Model
  Documentation Form's structure and row inventory, as inspected
- **[Provider corpus](corpus/README.md)** - the provenance and licensing
  record for the twelve provider documents and the source-verification
  script; the documents themselves are not distributed
- **[Errata](docs/errata.md)** - the append-only log of corrections to the
  registry, the format and the rules
- **[Paper](docs/paper.md)** - the registry-anchored verification approach,
  written up for review; the arXiv submission source it generates is in
  [`paper/`](paper/README.md)
- **[uv](https://docs.astral.sh/uv/)** - package manager and lockfile
  reference

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev container, the quality
gate, commit message rules, tests and releases.

## License

MIT License - see the [LICENSE](LICENSE) file for details.

Copyright 2026 Shane McGovern
