# Registry methodology

This document states what the field registry can and cannot establish, the
rules its stored text is held to, how that text is kept current, and the terms
on which the material it reuses may be reused. It is written for the
practitioners and auditors who read the tool's output, and it describes the
registry as shipped: where this document and the data under
`src/gpai_docs/registry/` disagree, the data is the record.

## What the registry can and cannot establish

The registry is the `eu-ai-act` pack: a machine-readable catalogue of the
documentation elements that Regulation (EU) 2024/1689 requires for
general-purpose AI models. It covers 25 elements:

- **Annex XI, Section 1 - 11 elements**, the technical documentation under
  Article 53(1), point (a): points 1(a)-(f) and 2(a)-(e).
- **Annex XI, Section 2 - 3 elements**, the additional information owed by
  providers of general-purpose AI models with systemic risk: points 1-3.
- **Annex XII - 11 elements**, the information under Article 53(1), point (b):
  points 1(a)-(h) and 2(a)-(c).

Each element is stored with its verbatim provision text, its source
(instrument, CELEX pin, location, language and URL), the date that text was
captured, and a SHA-256 hash of the stored text. Each is also bound to the
Model Documentation Form rows that carry its information, the recipients the
Act owes it to, and the key its content uses in the native document format.

What it establishes:

- **Coverage.** The element inventory is the pinned consolidation's inventory
  of the two annexes, and the data tests pin all 25 ids. The lint check is
  driven by the registry's entries rather than per-element code: a document
  with nothing filled in yields one finding per element that applies - 22 of
  the 25, because the three Section 2 fields wait on the systemic-risk marker
  - and the complete example yields none.
- **The provenance of every stored text.** Each text resolves to a source
  entry that records where it came from, how it was captured and how it is
  verified - an extract source re-fetched from the pinned HTML, or an
  artifact source whose text was hand-extracted from pinned bytes. Offline
  verification recomputes every stored hash; online verification re-fetches
  the source, runs the same extraction and normalisation, and compares the
  result, or re-downloads the artifact's bytes and compares their hash. A
  match means the source still publishes the same text under the same
  normalisation; a mismatch is a finding, never silence.

What it cannot establish:

- **Adequacy.** The registry reads presence, not content. A non-empty value at
  an element's key means the document answered that element; it does not mean
  the answer is accurate, complete, specific or sufficient. Nothing in the
  registry judges whether what a provider wrote satisfies the Act.
- **A verdict.** It never issues a compliance verdict. Findings name what is
  missing, unknown or malformed, or a relation between the document's own
  values that a cited text states, citing the provision where a finding
  concerns an element; the run closes by saying what it is - "engineering
  evidence, not a compliance verdict".
- **The Act's GPAI documentation duties as a whole.** Article 53(1), points
  (c) and (d) are outside this edition, and Annex XI Section 2's three
  elements are checked only for a document that declares systemic risk.

## The document format

A checked document is one YAML or JSON file in the v0.1 format: a `schema: 1`
marker fixes how it is read, values sit under the registry's `model_field`
keys, and each element's accepted shape is declared by its `type:` tag. Two
tags are structured - `annex_xi.computational_resources` carries the training
compute in FLOP as a number, `annex_xi.energy_consumption` an amount in its
reported unit - and the optional `notifications` and `modifications` sections
hold the notification and modification records under the same typed rules.
`gpai-docs schema` prints the document JSON Schema the models project
(`--out PATH` writes it to a file), so editors and pipelines check the same
shapes the lint pass enforces. Numbers are the YAML 1.2 core literals:
plain decimals and floats such as `2.3e25` or `9e+24`, with `0o`/`0x` for
octal and hex (`017` reads as decimal seventeen). Quoted numbers and the
YAML 1.1 oddities (`12:30`, `1_000`) are malformed in a number slot, never
guessed.

An optional top-level `systemic_risk` marker (absent means false, and only a
real boolean passes) states that the model carries systemic risk. The three
Annex XI Section 2 fields apply only to a model whose document declares
`systemic_risk: true`: the completeness pass skips them when the marker is
false or absent, and reports their absence as the normal missing finding when
it is true. Either way, values for those fields may be present early -
providing them before the marker is declared is no finding.

## The consistency rules

The linter's fourth pass reports relations between a document's own values
that a provision or the Commission's guidance states. Its v0.1 catalogue is
three rules and the records-completeness table that makes them evaluable,
each citing the text it rests on verbatim:

- **`notification.due`** - training compute above 10^25 FLOP without an
  Art. 52(1) notification record, or with a notification dated more than two
  weeks after the trigger, or before it (Article 51(1), point (a), Article
  51(2), Article 52(1)).
- **`compute.reporting`** - a training compute carrying more than two
  significant figures, or without its estimation method, for the model's own
  compute and for each notified compute (guidelines paragraphs 120 and 31,
  and the Form's two-significant-figures and measurement-methodology rows).
- **`modification.one-third`** - a modification above one third of the
  model's training compute that the document does not record as a provider
  record. Its criterion is the guidelines' **indicative** one (paragraph 60):
  an indicative criterion, not a threshold the tool decides, and the wording
  attributes it to the guidelines without judging the model or the provider.
- **Records completeness** - a notification record answers for its compute,
  its aware and notified dates and its estimation method, and a modification
  record for its description; each absence is a finding resting on the
  catalogue's declared requiredness and citing the provision that makes the
  field meaningful (Article 52(1), guidelines paragraphs 31 and 60).

The rules stay silent where their inputs are absent or unreadable: an absent
value is the completeness pass's story, a document the typed pass refuses
runs no rule at all, and a magnitude no comparison can hold is skipped, never
guessed at. Guidelines paragraph 115, to which paragraph 60 defers for how
"training compute" is understood, is not among the registry's sources in
this edition, so the registry cites paragraph 60 alone.

## Comparing document versions

Under the Code's Transparency Measure 1.1, signatories update the Model
Documentation to reflect relevant changes, including updated versions of the
same model, and keep previous versions for ten years after the model is placed
on the market (Transparency Chapter, Measure 1.1, second paragraph).
`gpai-docs diff` answers the question those kept versions raise - what changed
between two documents - with the registry's own vocabulary and without judging
either version. Every element the registry names compares in registry order by
its stored value: an element only one document answers is `added` or `removed`,
two present values that differ are `changed`, both reported in the renderers'
canonical form - a float as the shortest spelling that round-trips its double,
a mapping with its keys sorted - and numbers read numerically, so `1` and `1.0`
are one value and a change of spelling is no change at all. An element keeps
its ints exact, and NaN reads equal to NaN, never to a number. After the
elements, the top-level `systemic_risk` marker compares as an attribute of its
own: absent and `false` are one effective value, and two differing effective
values are one `changed` change at `systemic_risk`. The records sections
compare index-aligned when the two lists are equally long: a pair of
canonically equal entries is no change; a pair of mappings with the same key
set reports its differing fields as `changed` changes at
`<section>[i].<field>`, with both values; any other unequal pair - key sets
that differ, non-mappings - falls the whole section back to remove+add, the
old entry removed at its index and the new entry added at its index, so a
same-key-set reorder reads as field-wise change, never as silence. A length
change keeps the v0.1 reading whole: entries match order-free as a multiset of
their canonical entries, duplicates count per occurrence, and reordered equal
entries are no change. Both record readings key an entry, and each field
inside it, by one canonical identity with every number read as the double it
denotes - so two distinct large ints one double cannot tell apart, or one
number respelled between that double's spellings, read as no change in a
record. Diff judges nothing: a
malformed value diffs by its raw reading - whether what is written is valid is
`gpai-docs lint`'s finding - and a key the registry does not name is not a
change at all. The exit code is diff(1)'s - 0 no differences, 1 differences
found, 2 bad input - so a documentation-change gate can read it directly.
Comparing two versions is not assessing either: nothing in a diff says a change
is material, adequate or compliant, and a changed value is never a verdict.

`gpai-docs diff --markdown` and `gpai-docs lint --markdown` render the changes
and the findings as Markdown reports, `gpai-docs extract annex-xii` writes
the Annex XII subset - the information Article 53(1), point (b), owes
downstream providers - as a native document, and `gpai-docs export hf-card`
and `gpai-docs export cyclonedx` project a document to exchange formats, a
Form-grouped model card and a BOM whose properties name every present fact;
none of them judges.

## The exchange-format projections

`gpai-docs export hf-card` and `gpai-docs export cyclonedx` project a native
document into the two exchange formats without judging it. Neither writer
emits a timestamp, so two runs over the same document are byte-identical.

**The card.** The Hugging Face-style model card carries the document's own
top-level facts in its frontmatter, under HF's vocabulary: `model_name`, the
licence and `library_name`, each carried only when the document has it. Its
body is grouped by the Form: one section per Form group that holds a present
Form-mapped fact, in the group order the Form publishes, and each fact under
its registry label with a `<!-- annex: <id> -->` traceability comment
immediately before the value, so a quoted fact always names its element. A
fact whose rows span two Form groups is quoted under each, as the Form files
it. A document answering nothing renders the frontmatter alone.

**The BOM.** The CycloneDX 1.6 BOM carries one component of type
`machine-learning-model` with a single `modelCard`. Every present fact the
registry names becomes a `gpai-docs:annex:<id>` property in registry order,
its value the fact's digest; this includes the fields with no Form rows - the
three Annex XI Section 2 fields - so the BOM is the complete projection where
the card is the Form-mapped subset. The component and card also carry the
facts the CycloneDX schema has a place for: the component name (the
document's `model_name`, or the placeholder `unnamed model`, since CycloneDX
requires a name and the exporter invents no identifier), the licence, a
numeric architecture spelled as text, and the training data as a
description-only dataset entry. Where the registry holds twin elements for
one slot - the Annex XI and Annex XII licence, training-data and architecture
elements - the first present one, Annex XI first, fills it.

**The digest.** A property's value is the first 12 hexadecimal characters of
the SHA-256 of the fact's canonical JSON spelling: sorted keys, compact
separators (no space after the comma or the colon), non-ASCII characters
escaped as `\uXXXX`, and a non-finite number refused rather than spelled. The
spelling is deterministic, so one fact always digests to one value.

## Normalisation rules

Stored text is not raw HTML, and it is not copied by hand. Every provision
passes through one minimal normalisation, and the hash is taken of the result:

1. **HTML entity decoding**, applied to a fixpoint: decoding runs until the
   text stops changing, so a doubled escape such as `&amp;nbsp;` is fully
   decoded instead of being left as `&nbsp;`.
2. **Whitespace collapse:** every run of whitespace becomes a single space.
   This includes the non-breaking space and the other Unicode spaces.
3. **Unicode NFC**, the canonical composition form.
4. **Trim** of leading and trailing whitespace.

The rules are idempotent: normalising already-normalised text changes nothing.
There is no typographic rewriting - no quotes, dashes, letters or spellings
are substituted or corrected - so a stored hash moves only when the text
itself does.

Two kinds of material are never part of stored text:

- **Enumerators.** The consolidation renders its enumerators ("1.", "(a)") in
  blocks separate from the sentences they label. Extraction joins each
  enumerator to its sentence, and the enumerator is stored separately, in the
  registry's `point`: the stored text never contains it.
- **Change-bar marks.** The consolidation's amendment marks ("▼B", "▼M1",
  sometimes followed by a dash rule out to the margin) are tolerated by the
  extractor and excluded from its result: they are skipped wherever they occur
  between blocks, and none is stored.

Extraction is deliberately conservative: if an anchor the extractor was asked
for is missing, or a point has no sentence after it, extraction fails rather
than returning partial text. That is why a changed page is reported as
"extraction failed" and never as a text change.

Authoring and verification call the same extraction and normalisation code, so
a stored hash is never compared against text produced by a different
normaliser.

## The change process

Stored text moves through six steps: detect, triage, fetch, review, commit,
verify.

**Detect.** A weekly scheduled run (Mondays, 06:17 UTC) executes
`gpai-docs registry verify --online` against the live sources. It re-fetches
and re-hashes the extract-mode sources, re-downloads the artifact-mode sources
and the Form and compares their byte hashes, and reports what it finds. The
kinds of finding stay distinct: a source that could not be reached ("could not
verify") is not drift, and an extractor that no longer finds its provision
("extraction failed") is not a text change. The consolidation watch resolves
the act's latest consolidation through the Publications Office Cellar
endpoints - the enacted act's RDF names every consolidation layer of the act,
and the newest layer is the watch's answer. `could_not_verify` still appears
when every resolver form is unreachable, challenged or silent: EUR-Lex's own
legal-content resolver answers a constrained network with a challenge page,
and a challenged page is never read as drift. The scheduled run's history is
the record of when verification last happened.

The watch tries three resolver forms, all probed live on 2026-10-09. The
EUR-Lex legal-content CELEX URL resolves the undated identifier to the latest
consolidated version and redirects to its dated URI; it is challenged by its
WAF from the development container, an environment artefact and not a missing
resolver. The Publications Office Cellar resource URI is the Cellar-side form
of the same identifier; it answers a clean 404, because the resource is not
published there. The enacted act's own Cellar RDF is the third form: it names
every consolidation layer of the act, so its newest dated CELEX is the latest
consolidation, and it answers 200 to a fetcher that sends no Accept header,
naming the act's 2024-07-12 and 2026-07-27 layers. CELEX keeps consolidations
in sector 0 and enacted secondary legislation in sector 3, so the enacted
act's CELEX is the undated consolidation identifier with its sector digit
swapped to 3; an instrument outside that sector pairing answers 404 here, and
the watch reports `could_not_verify` with one reason per attempt.

**Triage.** A non-green run is read before anything is edited. A text change,
an artifact change and a source that could not be reached call for different
responses, and only a real change proceeds.

**Fetch.** `gpai-docs registry fetch` re-fetches the extract-mode sources,
prints a per-source text diff and an element-inventory diff - which lettered
points appeared, vanished or renumbered - and is a dry run unless `--write` is
given. It refuses to write when any selected source fails, and again when the
regenerated file does not validate.

**Review.** A person reads the diff against the official text and decides what
the change means for the fields the source feeds. The tool proposes text;
nothing is committed without a person accepting the diff.

**Commit.** Registry edits ride ordinary pull requests with `fix(registry):`
or `feat(registry):` prefixes, so the release changelog doubles as the
registry's change log, and a correction to the registry, the format or the
rules lands with its entry in the [errata log](errata.md), which records what
changed, why and how to verify it. CI never writes registry data.

**Verify.** After the change is committed, the verification path re-checks it,
and the next scheduled run confirms it from the live source.

`retrieved` records the date the stored text was last captured from its
source. It moves only when the stored text changes, never on a no-change
verification, so it is a provenance date and not a "last checked" date: a
source verified unchanged for months keeps its original `retrieved` date, and
the record of when checking happened is the scheduled run's history.

## Relationship to other frameworks

The registry's crosswalk layer connects the elements to instruments
practitioners use: the EU Code of Practice's Transparency Measures 1.1-1.3,
NIST AI RMF 1.0 and NIST AI 600-1, ISO/IEC 42001 with 42005 and 23894 as
satellites, the OECD AI Principles, the Council of Europe Framework
Convention, and Korea's AI Basic Act. The serialisation formats (CycloneDX
ML-BOM, SPDX 3.0 AI, OSCAL) are recorded as deferred targets for a later
version.

**Mappings are navigation, never conformance.** A mapping says "this element
is where instrument X keeps the corresponding material". It does not say that
the element, the instrument, or a document invoking either conforms to
anything. Findings never cite a crosswalk entry, and the notes say where
material lives; they do not score it.

The normalisation method's documented anchor is the MIT AI Risk Repository's
"best-fit framework synthesis" (Slattery et al., *The AI Risk Repository*,
arXiv:2408.12622): the published reference for how this crosswalk places the
material of different frameworks on one comparable footing. The Repository's
living-database discipline is the model the target pins follow: each target
carries its pinned version and date, and freshness is a review cadence, not
automation.

**No field-to-risk-domain mappings are made.** The registry does not classify
elements, or risks, into risk domains or taxonomies. The MIT AI Risk
Repository is a methodology reference, not a crosswalk target: nothing here
maps a field to one of its risk domains.

## European primacy

The Act's native vocabulary is canonical in every surface. Element identifiers
are the annex points themselves and element labels are drawn from the annex
language; findings cite the annex point, the recipients the Act's provision
names (the AI Office and the national competent authorities for Annex XI,
downstream providers of AI systems for Annex XII), and the verbatim text. The
terminology block keys every entry to the Act's own term - *AI system* at
Article 3(1), *provider* at Article 3(3), *general-purpose AI model* at
Article 3(63) - and never sets a non-Act term up as the frame.

All other vocabularies attach as connected aliases, never as parallel
authorities. The ISO/IEC 22989 definitions, the OECD definitions and Korea's
AI Basic Act terms enter only as aliases beneath an Act term, each with a note
that states where it diverges. ISO/IEC 22989 is not the bridge vocabulary: its
role terms predate the Act and map only partially, so its entries say "partial
match only". Korea's entries name the false friends - its *AI development
business operator* is not the Act's *provider* - and distinguish its
*high-impact AI* from the Act's *high-risk AI system*.

## The language limitation

The registry stores and hashes the English text of the consolidated regulation
(CELEX `02024R1689-20260727`, consolidated as at 27 July 2026); every source
entry records `language: en`. The regulation is equally authentic in all 24
official languages, and the hash binds the English version alone: a change
that touched only another language version would not move a hash here, and the
registry makes no cross-language comparison. Where language versions could be
read differently, the authentic texts govern - not the registry's English
extract.

## Disclaimers

The registry and everything built on it are engineering evidence, not legal
advice.

- **Not legal advice.** Nothing in the registry, or in any finding, says what
  the law requires of anyone or how it applies to a particular model, provider
  or document. That is a legal judgement, and it belongs with the authentic
  text and qualified advice.
- **Not a substitute for the official text.** Stored text is extracted from a
  dated consolidation. The authentic versions of the regulation are those
  published in the *Official Journal*; the consolidation is the working text
  the registry pins, not the source of legal authority.

## Credit lines

Every crosswalk target carries its own reuse terms in the crosswalk data; the
ones that carry obligations are these.

- **NIST.** NIST-authored material (AI RMF 1.0, NIST AI 600-1) is not subject
  to copyright in the United States; it is used here with attribution to NIST.
  The NIST disclaimer applies: the identification of commercial entities
  implies no endorsement by NIST.
- **Commission materials.** The Code of Practice's Transparency Measures, the
  Model Documentation Form and the Commission's GPAI Guidelines are Commission
  documents, reused under CC BY 4.0 with attribution. The registry quotes
  extracts and pins the documents; nothing it publishes presents itself as a
  Commission publication.
- **ISO and CEN.** ISO/IEC texts are copyrighted. The registry reproduces no
  ISO text - ISO rows cite clause and Annex identifiers and link only - and
  the same identifiers-only rule is attached to CEN/CENELEC texts.
- **Other targets.** The OECD Recommendation is reproduced unaltered and not
  for sale; the Council of Europe convention is linked only, with its reuse
  terms recorded as unverified; the KLRI Korean translation is quoted in
  individual terms only.

## The ISO access limitation

When the crosswalk was authored, no authorised copy of ISO/IEC 42001, 42005,
23894 or 22989 was available for checking identifiers, and ISO's public
catalogue pages give month-precision metadata only. The clause and control
numbering behind the ISO rows is therefore unverified, and the registry
records that rather than hiding it:

- every ISO target carries `provisional: true`;
- every ISO row cites clause and Annex identifiers only, and no ISO text is
  reproduced anywhere;
- the ISO rows are navigation pointers to be checked, not verified mappings.

`provisional: true` means exactly "identifiers unverified against an
authorised copy", and it clears when the identifiers have been checked against
one. Until then, read ISO clause and control numbers as provisional.

## The Form's audience crosses

The Commission's Model Documentation Form is the checklist the Code of
Practice's Transparency chapter provides for Measure 1.1. The registry
inventories the Form's rows in `form.yaml`; each field records the rows that
carry its information and the Form's audience crosses as `audience_flags` -
the union of its rows' crosses, in the Form's own vocabulary (AI Office,
national competent authorities, downstream providers).

The Form's crosses can diverge from the Act's recipients, and the registry
keeps both rather than reconciling them: `recipients` is who the Act owes the
information to, `audience_flags` is what the Form marks. The example to hold
on to is `XI.1.2.a`, technical means for model integration: the Form flags it
downstream-only, while its recipients under the Act are the AI Office and the
national competent authorities. Findings render both, and neither view
suppresses the other.

The Form's own mechanics are documented in
[`docs/form-docx-structure.md`](form-docx-structure.md): the pin and byte hash
of the inspected DOCX, the content-controls finding (the rows cannot be read
with a plain table walker), the fact that the Form publishes no row
identifiers - the registry's row ids are derived - and the continuation rows,
stranded crosses and debris the importer must tolerate.

## Reading and writing the Form package

`gpai-docs import-docx` reads a filled copy of the Form into a native document
and `gpai-docs export-docx` writes a native document's values into a copy of
the blank Form. Both are bridges, not fidelity tools: they carry the values
the Form's rows hold and nothing else, and they judge nothing.

**The round trip.** `import-docx(export-docx(doc)) == doc` for documents whose
values are text or numeric-literal amounts, where "==" is per-field equality
after whitespace normalisation and a structured leaf compares by the text the
export renders for it: `training_flop` as `2.3e+25 FLOP (estimated: ...)` - the
amount with its estimation method after it - an energy amount as
`<amount> <unit>`, and methods and times verbatim. The claim's verified
caveats: a blank line inside a value normalises to a single newline (the
settled shape - on the paragraph shape the reader's paragraph join makes it
its one space, which the whitespace normalisation reads equal); rows the Form
gives no response field cannot be carried, `release_date_and_distribution`
first among them (the export writes the value nowhere); and a Form row shared
by several fields files its text to every claimant on import while the export
writes the first carrying claimant's alone, so a later claimant's own text is
not recoverable from the Form (the coarse corners below). The export is
byte-stable for the same template bytes and document: member order is
preserved and the member timestamps are normalised, so the same input writes
the same package.

**What the export writes.** For every field the document carries, in registry
order, the export writes the value once: a plain field on the FIRST row of
its `form.yaml` mapping, a structured element's leaf on the first row routing
to that leaf (a twin row that carries the same leaf stays empty), and a row
two fields share only from its owner, the first carrying claimant in registry
order. A row the document gives no value is left as the template had it, with
its placeholders in place.

**The template is the user's.** The blank Form is obtained from the Commission
by the user and passed with the required `--template`; the tool never bundles
it in the repository, never redistributes it, and never writes over it - the
filled copy goes to `-o` alone. A package whose rows carry no label the
registry's `form.yaml` knows is not the Form, and the run refuses it.

**The placeholder discrimination rests on the artifact.** The blank Form's
response fields carry guidance, not answers. A response reads as absent when
its content control sets `w:showingPlcHdr`, when its text is the control's own
alias, or when its runs carry the Form's guidance styling - the grey `Style2`
or `PlaceholderText` character style, or one of the guidance colours - the
discrimination the blank-Form inspection pinned and verified row by row. Its
visible failure mode is an answer that inherits a guidance style: it reads as
absent, and the element it answers reports a missing finding even though the
document holds the answer. The finding is visible in lint's output, and the
provider clears it by removing the inherited formatting from the response.

**The numeric reading is literal-only.** An import reads a response as a
number only when, after trimming, it is exactly a YAML 1.2 core numeric
literal. `1234 kWh`, `2.3e+25 FLOP (estimated: ...)` and every other spelled
form stay strings: lint names them as malformed amounts and the provider
fixes the document, rather than the tool guessing at units or stripping
text.

**The Form's coarse corners.** One Form row can serve two documentation
elements: the two annexes' elements share rows, and the hardware/software
interaction row and the software-versions row are one row. The import files a
row's text to every element that claims it, so both claimants read the same
answer. The export writes a shared row from its owner alone - the first
claimant that carries a value, in registry order; every other claimant skips
the row, and a shared row no claimant carries stays untouched. When both
claimants carry, the second claimant's own text is therefore not recoverable
from the Form, and the rule keeps repeated export/import cycles from
compounding the shared text: the import re-files the row's text to every
claimant and the owner rewrites it, so every cycle after the text has settled
writes the same bytes. The Form is the lossy party here; the tool records the
coarseness rather than inventing a place the Form does not have.

**Rows without a response field.** Five inventory rows carry no response
field at all - a date control, option checks, an area holding no aliased or
tagged control: `general-information/release-date`,
`general-information/union-market-release-date`,
`model-properties/total-model-size-parameter-range`,
`data-used-for-training-testing-and-validation/data-provenance` and
`data-used-for-training-testing-and-validation/data-provenance-category-options`.
The export writes a value for such a row nowhere and the import reads nothing
from it, so nothing that lands there can round-trip. One field is bitten:
`release_date_and_distribution` renders first onto
`general-information/release-date`, so a value for it is written nowhere and
silently disappears; the fields that list one of these rows later in their
mapping (`architecture_and_parameters`'s parameter-range row, `training_data`'s
provenance row) write on an earlier row first and never reach the fieldless
one.

**The recorded ritual (v0.1).** The real pinned Form, fetched to `/tmp` and
never committed, was checked by hand. The walk locates all 46 inventory rows
(the debris row drops silently); a blank import writes the skeleton document
(`schema: 1` alone) with its summary line; and a document filling 13 rows,
exported into the blank Form and re-imported, reads back every written row
exactly - a plain two-line value on a run-level row (the acceptable-use-policy
row among them) reads back both its lines - with the export byte-stable
across the cycles after the text has settled.
