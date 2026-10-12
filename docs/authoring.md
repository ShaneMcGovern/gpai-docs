# Authoring a document

`gpai-docs` checks one document at a time: a single YAML or JSON file
holding a provider's general-purpose AI model documentation under the
keys of the field registry. This guide describes that file: its shape,
its typed values, the conditional elements, the records, and the four
kinds of finding a run can report. The complete annotated example is
[`tests/fixtures/model-docs-example.yaml`](../tests/fixtures/model-docs-example.yaml),
which answers every element of the registry and lints clean; start from
it.

## The shape of a document

A document is one mapping. `schema: 1` is required and fixes how the file
is read; everything else sits under the registry's element keys:

```yaml
schema: 1
systemic_risk: true          # optional; absent means false
annex_xi:                    # Article 53(1)(a) technical documentation
  intended_tasks: "..."
annex_xii:                   # Article 53(1)(b) downstream information
  intended_tasks: "..."
notifications: []            # optional; Article 52(1) records
modifications: []            # optional; provider-modification records
```

The keys under `annex_xi` and `annex_xii` are the registry's
`model_field` names: fourteen under `annex_xi` (eleven Section 1
elements, three Section 2 elements) and eleven under `annex_xii`. A key
the registry does not name is an `unknown` finding, and a key that is
absent, empty or null is a `missing` finding: a blank value is not an
answer.

A `.json` file is read as JSON; anything else is read as YAML.

## Typed values

Each element's accepted shape is declared by its registry type tag, and
`gpai-docs schema` prints the document JSON Schema those tags project, so
editors and pipelines can check the same shapes the lint pass enforces:

```bash
uv run gpai-docs schema --out model-docs.schema.json
```

Text elements take a string. Numbers are the YAML 1.2 core literals:
plain decimals and floats such as `2.3e25` or `9e+24`, with `0o`/`0x` for
octal and hex (`017` reads as decimal seventeen). Quoted numbers and the
YAML 1.1 oddities (`12:30`, `1_000`) are malformed in a number slot, never
guessed. Dates are calendar dates (`2026-05-12`), and an impossible date
(`2026-02-30`) is reported as malformed rather than guessed. The registry's
tag vocabulary is closed - text, text-list, number, date, url, compute and
energy - and the shipped elements use text, compute and energy; each
element's declared shape is enforced, so a list where a text element is
declared, or any other value outside its shape, is a finding.

### The two structured elements

`annex_xi.computational_resources` carries the training compute as a
number, not prose, because the consistency rules compare it:

```yaml
computational_resources:
  training_flop: 2.5e+25
  estimation_method: "Extrapolated from the provider's published training report."
  training_time: "21 days on 4,096 accelerators."
```

`annex_xi.energy_consumption` carries an amount in its reported unit, for
training and for inference:

```yaml
energy_consumption:
  training:
    amount: 1500
    unit: "MWh"
    method: "Estimated from accelerator power draw and training time."
  inference:
    amount: 8.1e+18
    unit: "FLOP"
    method: "Benchmarked over a 30-day production window."
```

Two significant figures matter: the `compute.reporting` rule reports a
training compute carrying more than two significant figures, or one
without its estimation method, for the model's own compute and for each
notified compute.

## Systemic risk and the conditional elements

The optional top-level `systemic_risk` marker states that the model
carries systemic risk; absent means false, and only a real boolean
passes. The three Annex XI Section 2 elements apply only to a model whose
document declares `systemic_risk: true`: `evaluation_strategies`,
`adversarial_testing` and `system_architecture`. When the marker is true
they are checked like any other element; when it is false or absent the
completeness pass skips them. Values may be provided early either way:
answering a conditional element before declaring the marker is no
finding.

## Records

Two optional sections hold the event records the Act requires:

```yaml
notifications:
  - compute_flop: 2.5e+25
    estimation_method: "Extrapolated from the provider's training report."
    aware_on: 2026-06-01
    notified_on: 2026-06-10
modifications:
  - description: "Continued pre-training on a new data mix."
    training_flop: 3.5e+25
    provider_record: true
```

A notification record answers for its compute, its aware and notified
dates and its estimation method; a modification record for its
description. An absent field is a finding resting on the provision that
makes the field meaningful, and the records feed the consistency rules
below.

## The finding kinds

A finding that rests on an element opens with its kind, the element's
registry id and the element's label, then the citation material: the key,
the annex point, the Form rows and audience flags, the verbatim provision
text, and the registry's guidance. A finding about a key or a record field
below an element names the path instead, with no citation. The four kinds
come from four small documents; create them once:

```bash
mkdir -p /tmp/kinds
cat > /tmp/kinds/missing.yaml <<'YAML'
schema: 1
annex_xi:
  intended_tasks: "Text generation and summarisation."
YAML
cat > /tmp/kinds/malformed.yaml <<'YAML'
schema: 1
annex_xi:
  intended_tasks: ["text generation", "summarisation"]
YAML
cat > /tmp/kinds/unknown.yaml <<'YAML'
schema: 1
annex_xi:
  training_datasets: "web text"
YAML
cat > /tmp/kinds/inconsistent.yaml <<'YAML'
schema: 1
annex_xi:
  computational_resources:
    training_flop: 1.1e+26
    estimation_method: "Extrapolated from the provider's published figures."
YAML
```

### `MISSING`

An element that applies to the document has no answer. Add the value, or
declare `systemic_risk: true` if a Section 2 element should not apply.
`uv run gpai-docs lint /tmp/kinds/missing.yaml` opens with:

```text
[MISSING] XI.1.1.b - Acceptable use policies
  Key: annex_xi.acceptable_use_policies
  Annex XI, Section 1, point 1(b) - owed to: AI Office, NCAs
  Form rows: use/acceptable-use-policy
  Form audience flags: ai_office, nca, downstream
  "the acceptable use policies applicable;"
  Guidance: State the acceptable use policies that apply to the model.
```

### `MALFORMED`

A value is present but not in the shape its type tag declares. The
`Reason:` line says what the reader expected and what it found; an
element-bound finding (below) cites the element, while a record-level one
reads `[MALFORMED] notifications[0].aware_on` and the reason, with no
citation. `uv run gpai-docs lint /tmp/kinds/malformed.yaml` opens with:

```text
[MALFORMED] XI.1.1.a - Tasks the model is intended to perform
  Reason: expected text: ['text generation', 'summarisation'] is not text
  Key: annex_xi.intended_tasks
```

### `UNKNOWN`

A key the registry does not name. The finding names the path, so a typo is
easy to see. `uv run gpai-docs lint /tmp/kinds/unknown.yaml` ends with:

```text
[UNKNOWN] annex_xi.training_datasets - no registry entry for this key
```

### `INCONSISTENT`

Values inside the document contradict a rule the provision or the
Commission's guidelines state. The `Reason:` line states the relation and
the `Basis:` lines quote the text it rests on.
`uv run gpai-docs lint /tmp/kinds/inconsistent.yaml` includes:

```text
[INCONSISTENT] XI.1.2.d - Computational resources used to train the model
  Reason: training compute 1.1e+26 FLOP is greater than 10^25 and the document carries no Art. 52(1) notification record
  Key: annex_xi.computational_resources
```

A document the typed pass refuses runs no consistency rule at all, which is
why these are four documents and not one: the malformed one above would
silence the rest. Rules also stay silent where their inputs are absent or
unreadable: an absent value is the completeness pass's story, and a
magnitude no comparison can hold is skipped, never guessed.

## Checking your document

```bash
uv run gpai-docs lint model-docs.yaml             # 0 clean, 1 findings, 2 bad input
uv run gpai-docs lint model-docs.yaml --json      # the findings as data
uv run gpai-docs lint model-docs.yaml --markdown  # a report for a pull request
```

`lint` exits 0 when the document is clean, 1 when it has findings and 2
on bad input, so the command drops straight into CI (the repository's
action wraps exactly this). To compare two versions of a document,
`gpai-docs diff old.yaml new.yaml` reports what changed in the registry's
vocabulary and follows `diff(1)`'s exit codes.

The [registry methodology](methodology.md) states what the registry can
and cannot establish, and the terms its stored text is held to; the
[Form structure note](form-docx-structure.md) is the inspection record of
the Commission's Model Documentation Form, which
`gpai-docs import-docx` and `gpai-docs export-docx` convert to and from.
