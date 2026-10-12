# Model Documentation Form - DOCX structure and row inventory

The Model Documentation Form is the checklist the Transparency Chapter of the
Code of Practice provides for Measure 1.1: a provider records the information
the AI Act's transparency obligations require, and the crosses on the right of
each row say which audience the information is meant for - the AI Office
(AIO), national competent authorities (NCAs), or downstream providers (DPs).
This note is the inspection record the importer rests on: it pins the DOCX
that was inspected, answers the content-controls question the importer
depends on, and inventories every row with the crosses as
published. The machine-readable copy of the inventory, with the pin, is
`src/gpai_docs/registry/form.yaml`.

## The pin

| | |
| --- | --- |
| Artefact | Model Documentation Form (WordprocessingML package) |
| Source URL (final, after redirects) | <https://ec.europa.eu/newsroom/dae/redirection/document/118118> |
| Redirect chain | none observed: the newsroom endpoint answers HTTP 200 directly, so the final URL equals the requested one and both are on the same host, `ec.europa.eu` |
| Retrieved | 2026-10-08 |
| Bytes | 104,696 |
| SHA-256 | `c9319ab941744155040e4ceeddbf189efb69d6c4f063453d208eac8e2f691a6f` |

The same values live in `form.yaml`'s `form:` block, which is the registry's
pin for the artefact: re-downloading the bytes and comparing
`artifact_sha256` is the Form check ("artifact
changed"). The document is the one the Commission's Code of Practice page
links as "Model Documentation Form (DOCX)"; the package's own timestamps
(created 2025-07-09, last modified 2025-07-10) match the chapter's
10 July 2025 publication.

## Structure: content controls, not plain tables

The form is made of Word tables, and its rows and cells are wrapped in content
controls, so the tables cannot be walked with `python-docx`'s table API alone.
`word/document.xml` holds:

- 8 tables (7 in the document body, 1 nested inside a cell), 120 rows, 600
  cells and 675 paragraphs in total;
- 319 content controls (`w:sdt`), of which 165 are tick controls (a
  `w14:checkbox` in the control's properties): 138 audience crosses (94 ticked
  and 44 unticked - the three marks of each of the 45 flagged inventory rows
  plus the three on the stray row below), 26 option boxes (the
  Text/Images/Audio/Video options beside the three modality rows, the eight
  parameter-range options, three data-provenance options and the three nested
  category options; all unticked), and 1 stray empty-content control that
  renders nothing. By what the control wraps: 117 of the 165 wrap a table cell,
  41 a run, 6 a paragraph and 1 empty content; the other 154 controls wrap a
  table cell (18), a whole table row (8), a table (2), a paragraph (70), a run
  (45), or nest further controls (11);
- 62 controls carry an alias or a tag (the placeholder text of the response
  fields); 279 are locked (65 `sdtLocked`, 214 `sdtContentLocked`);
- no legacy form-field machinery (`w:fldChar`, `w:instrText`, `w:checkBox`:
  zero). Every audience cross is a `w14:checkbox` content control whose state
  is structured - `w14:checked` (`1` ticked, `0` unticked) with `checkedState`
  U+2612 and `uncheckedState` U+2610 - and the control renders that character:
  the 138 crosses render 94 U+2612 and 44 U+2610, the 26 option boxes render
  U+2610 apiece, and the stray control renders nothing, so 164 of the 165
  render a character. Read `w14:checked`, not the rendered glyph, and unwrap
  the control like any other `w:sdt`;
- no `word/numbering.xml` part and zero `w:numPr` properties, so nothing is
  auto-numbered and **the form publishes no row identifiers**: rows are
  identified only by their section heading and label.

The rows have a fixed geometry: a data row carries its label in the first
cell, the description and response fields in the cells between, and the
three audience crosses in the last three cells. A section-heading row is one
whose first cell spans more than one grid column (`w:gridSpan`), which is
how the walk tells the Form's eight headings from data rows. Five rows
answer through a run-level (inline `w:sdt`) response control, one whose own
content holds the answer's runs rather than a control wrapping a whole cell.

The blank copy's response fields carry guidance, not answers, and guidance
is told apart from an answer by three signs: the control sets
`w:showingPlcHdr`; its text is exactly its own alias or tag value; or its
runs carry the Form's guidance styling, the character styles `Style2` (its
own grey, `w:color` 808080) and `PlaceholderText` (Word's built-in one,
666666), or the run colours 808080, 7F7F7F, 939598 and 0F4761 - the last the
accent blue of one aliased, content-locked label ("Maximum size:") no
provider can fill. An answer carries the document's default formatting.

### Consequence for the importer

Read `word/document.xml` from the package with stdlib `zipfile` and
`xml.etree.ElementTree`, and unwrap `w:sdt`/`w:sdtContent` before walking rows
and cells. A direct-children walk (which is what `python-docx` does) silently
loses the 8 sdt-wrapped rows and 135 sdt-wrapped cells, and the row and cell
indices it produces then no longer line up with the published form. Take each
audience cross from `w14:checked` on the tick control rather than from the
rendered character: the state is the structured source, and one unticked
control renders no character at all (in this copy state and glyph agree
wherever a character is rendered, so a text-based parse yields the same
flags). Joining every `w:t` of a paragraph is also required: label text is
split across runs, so the raw XML text is not cell text. Five wrinkles survive
the unwrapping:

- **Continuation rows carry no label.** Where the published form adds further
  paragraphs under one label, the label cell is merged and the later rows hold
  only a description: the License item has two such rows, Distribution channels
  one, and Number of data points, Training time and Amount of computation used
  for training one each. Carry the label forward from the last row that had one.
- **One DOCX row covers two published rows.** The Output modalities row also
  carries the "For each selected modality ... maximum output size" row, with
  two crosses per audience cell in reading order; the pair must be split.
- **One row's crosses sit in the next table row.** The parameter range row's
  label is in one row and its crosses are in the row holding the range
  options.
- **One row has no crosses at all.** The data-provenance category definitions
  row carries none; it elaborates the Data provenance row.
- **Rows and debris to drop.** A structurally normal row between Model
  architecture and Design specifications of the model carries three ticked
  crosses (AIO, NCAs and DPs) with empty label and description cells; the
  committed inventory excludes it deliberately - it has no label to record and
  no element of its own - and the importer must drop a row only when it has NO
  label, NO description **and no response text** (erratum, 2026-10-10: the
  original two-cell rule was unsafe - 10 walked rows have an empty raw label
  (6 carrying response or control text, 4 only description text), and the
  literal rule would lose `license-type-or-category`, `license-additional-assets`,
  `number-of-data-points-two-significant-figures`,
  `training-time-wall-clock-and-hardware-days`,
  `amount-of-computation-used-for-training-two-significant-figures` and
  `distribution-and-licenses/distribution-channels-downstream-providers` from
  the 46-row location). Two further
  fragments need the same tolerance: the first row of the table that begins
  with How data was obtained and selected is empty except for an unticked
  checkbox in its label cell that renders no character, and an otherwise empty
  cell in the row below the Data provenance checkboxes holds a stray "bu" text
  run.

## The synthetic package the tests build

The pinned DOCX is never committed: the reader and writer tests run against
synthetic packages built in-test by `tests/fixtures/form_docx.py`, whose
document part mirrors the constructs above. The builder writes content
controls (`w:sdt`) around rows, cells and runs; `w14:checkbox` ticks whose
state is `w14:checked`; alias-bearing response fields; labels split across
runs or paragraphs; and section headings whose first cell spans more than
one grid column. The packages are byte-stable (fixed member timestamps,
stored members) and never read from a binary.

The `Row` guidance-styling fields mirror the published form's styling:
`response_style` and `response_color` style the response runs,
`response_control_color` the control's own run properties,
`response_plchdr` the `w:showingPlcHdr` flag, `response_paragraph_style` a
`w:pStyle` on every response paragraph (the paragraph properties a written
value must keep), and `response_inline` a run-level control in a paragraph
of its own. `extra_crosses` writes the split row's hidden second tick
control, and `label_tick` writes a glyph-less tick (the unticked control
that renders no character). `write_package` writes the minimal package
parts with fixed timestamps and stored members (so equal input gives equal
bytes), and stamps `flag_bits` and `external_attr` into every member's local
and central directory headers after the write: the stored header values the
member-fidelity tests plant and the writer must carry through.

## How the row ids were derived

The form publishes no identifiers (see above), so every `row` value in
`form.yaml` is a derived key: `<section>/<key>`, some parts exact slugs of the
published text and many abbreviated - 18 of the 46 ids are plain
`slug(heading)/slug(label)`, 33 of the keys (and 4 of the 8 section parts)
already are exact slugs, and the rest shorten the heading or the label
(`distribution-and-licenses` for "Methods of distribution and licenses",
`data-used-for-training-testing-and-validation` for "Information on the data
used for training, testing, and validation", `computational-resources` for
"Computational resources (during training)", `energy-consumption` for "Energy
consumption (during training and inference)"). Where a label repeats within a
section the key gains a qualifier taken from that row's own text
(`distribution-channels-downstream-providers`, `license-type-or-category`,
`number-of-data-points-two-significant-figures`,
`training-time-wall-clock-and-hardware-days`, `measurement-methodology-energy`,
`measurement-methodology-inference`), and `total-model-size-parameter-range`
names the range row by its parent item rather than by a heading of its own.
Labels are the published text with only the trailing colon, a trailing full
stop, and the running "Select all that apply." instruction trimmed. A
continuation row repeats its item's label; its id differs, which is what
separates the two. The whole id set is pinned in `tests/test_registry_data.py`:
every row is either named by a field's `form.rows` or declared out of scope
there with a reason.

## Row inventory

46 rows in published order, grouped by the form's section headings. `yes` marks
a ticked cross, `no` an unticked one, and `-` means the row carries no crosses
at all. `AIO`, `NCAs` and `DPs` are the form's own column headings. One
structurally normal DOCX row that carries three ticked crosses but no label or
description is left out deliberately (see "Rows and debris to drop" above): it
has no label to record and no element of its own.

| Row ID | Row label (as published) | AIO | NCAs | DPs |
| --- | --- | --- | --- | --- |
| `general-information/legal-name-for-the-model-provider` | Legal name for the model provider | yes | yes | yes |
| `general-information/model-name` | Model name | yes | yes | yes |
| `general-information/model-authenticity` | Model authenticity | yes | yes | no |
| `general-information/release-date` | Release date | yes | yes | yes |
| `general-information/union-market-release-date` | Union market release date | yes | yes | yes |
| `general-information/model-dependencies` | Model dependencies | yes | yes | yes |
| `model-properties/model-architecture` | Model architecture | yes | yes | yes |
| `model-properties/design-specifications-of-the-model` | Design specifications of the model | yes | yes | no |
| `model-properties/input-modalities` | Input modalities | yes | yes | yes |
| `model-properties/input-modalities-maximum-size` | For each selected modality please include maximum input size or write 'N/A' if not defined | yes | no | yes |
| `model-properties/output-modalities` | Output modalities | yes | yes | yes |
| `model-properties/output-modalities-maximum-size` | For each selected modality please include maximum output size or write 'N/A' if not defined | no | no | yes |
| `model-properties/total-model-size` | Total model size | yes | no | no |
| `model-properties/total-model-size-parameter-range` | The range within which the total number of parameters falls | no | yes | yes |
| `distribution-and-licenses/distribution-channels` | Distribution channels | yes | yes | no |
| `distribution-and-licenses/distribution-channels-downstream-providers` | Distribution channels | no | no | yes |
| `distribution-and-licenses/license` | License | yes | yes | no |
| `distribution-and-licenses/license-type-or-category` | License | no | no | yes |
| `distribution-and-licenses/license-additional-assets` | License | yes | no | yes |
| `use/acceptable-use-policy` | Acceptable Use Policy | yes | yes | yes |
| `use/intended-uses` | Intended uses | yes | yes | yes |
| `use/type-and-nature-of-ai-systems` | Type and nature of AI systems in which the general-purpose AI model can be integrated | yes | yes | yes |
| `use/technical-means-for-model-integration` | Technical means for model integration | no | no | yes |
| `use/required-hardware` | Required hardware | no | no | yes |
| `use/required-software` | Required software | no | no | yes |
| `training-process/design-specifications-of-the-training-process` | Design specifications of the training process | yes | yes | no |
| `training-process/decision-rationale` | Decision rationale | yes | yes | no |
| `data-used-for-training-testing-and-validation/data-type-modality` | Data type/modality | yes | yes | yes |
| `data-used-for-training-testing-and-validation/data-provenance` | Data provenance | yes | yes | yes |
| `data-used-for-training-testing-and-validation/data-provenance-category-options` | For definitions of each listed category, see the Template for the Public Summary of the Training Content of General-Purpose AI models provided by the AI Office | - | - | - |
| `data-used-for-training-testing-and-validation/how-data-was-obtained-and-selected` | How data was obtained and selected | yes | yes | no |
| `data-used-for-training-testing-and-validation/number-of-data-points` | Number of data points | no | yes | no |
| `data-used-for-training-testing-and-validation/number-of-data-points-two-significant-figures` | Number of data points | yes | no | no |
| `data-used-for-training-testing-and-validation/scope-and-main-characteristics` | Scope and main characteristics | yes | yes | no |
| `data-used-for-training-testing-and-validation/data-curation-methodologies` | Data curation methodologies | yes | yes | yes |
| `data-used-for-training-testing-and-validation/measures-to-detect-unsuitability-of-data-sources` | Measures to detect unsuitability of data sources | yes | yes | no |
| `data-used-for-training-testing-and-validation/measures-to-detect-identifiable-biases` | Measures to detect identifiable biases | yes | yes | no |
| `computational-resources/training-time` | Training time | no | yes | no |
| `computational-resources/training-time-wall-clock-and-hardware-days` | Training time | yes | no | no |
| `computational-resources/amount-of-computation-used-for-training` | Amount of computation used for training | no | yes | no |
| `computational-resources/amount-of-computation-used-for-training-two-significant-figures` | Amount of computation used for training | yes | no | no |
| `computational-resources/measurement-methodology` | Measurement methodology | yes | yes | no |
| `energy-consumption/amount-of-energy-used-for-training` | Amount of energy used for training | yes | yes | no |
| `energy-consumption/measurement-methodology-energy` | Measurement methodology | yes | yes | no |
| `energy-consumption/benchmarked-amount-of-computation-used-for-inference` | Benchmarked amount of computation used for inference | yes | yes | no |
| `energy-consumption/measurement-methodology-inference` | Measurement methodology | yes | yes | no |

## The crosses and the registry

`form.yaml` records each row's crosses in the registry's own vocabulary
(`ai_office`, `nca`, `downstream`) - the values `fields.yaml` uses for
`recipients` and copies into a field's `audience_flags`. The DP-ticked rows are
the ones Annex XII draws on, and the AIO and NCAs ticks align with the
technical documentation of Annex XI Section 1; the field-to-row mapping itself
belongs to `fields.yaml`. Five rows carry no Annex XI Section 1 or Annex XII
element of their own - the four General information rows that identify the
provider and the model (legal name, model name, model authenticity, model
dependencies) and the data-provenance category list - so they may stay
unmapped there.
