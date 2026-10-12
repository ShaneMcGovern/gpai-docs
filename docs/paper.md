# Registry-anchored verification for EU AI Act GPAI model documentation

**A draft working paper for the gpai-docs project.**

**Status:** draft, for maintainer review; submission (arXiv) is the maintainer's decision and has not been made.

## Abstract

Article 53(1) of Regulation (EU) 2024/1689 obliges providers of general-purpose AI (GPAI) models to draw up technical documentation (Annex XI) and to make information available to downstream providers (Annex XII). We present `gpai-docs`, an open toolchain that checks a provider's documentation against those two annexes, and only against them. Verification names the cited legal text, not the document: a document is checked for presence, shape and a few internal relations, and never for adequacy. Its distinguishing property is provenance: the legal text that findings cite is machine-extracted from a dated, hash-verified consolidation of the Act (the guideline and Code texts are hand-extracted from byte-pinned artifacts), and a scheduled pipeline re-verifies every source, reporting drift as well as findings. We describe the field registry (25 elements: the 22 checked by default, each mapped to the Commission's Model Documentation Form and to the recipients the Act owes the information to, and the three Annex XI Section 2 elements owed only by models with systemic risk), the typed document format and its registry-model lockstep, three consistency rules grounded in the Act's provisions and the Commission's guidance, and a twelve-document corpus, authored here to represent real providers' published facts, with expected results derived by hand from the registry. We also state the toolchain's deliberate limits: it issues no compliance verdict, hashes the English consolidation alone, and treats the Commission's guidelines as cited guidance, not as law. The toolchain is built as a Python library, a CLI and a container image; the registry and the corpus's provenance record are maintained under an open licence in the project repository.

## 1. Introduction

The GPAI documentation duties have applied since 2 August 2025, and enforcement powers began on 2 August 2026; models placed on the market before 2 August 2025 must comply by 2 August 2027. The obligations sit in a long annex apparatus. Annex XI specifies the contents of the technical documentation point by point, Annex XII the information owed to downstream providers, and the Commission's GPAI Code of Practice offers a Model Documentation Form, distributed only as a Word document, that providers may use to record the information. The duties are not universal: Article 53(2) disapplies Article 53(1), points (a) and (b), for models released under a free and open-source licence with public parameters, unless they carry systemic risk (Section 7).

We ran an adversarial search for adjacent work in October 2026, over package registries, code hosts and the open web, and re-ran it at each milestone. The search found a prototype open validator covering Annex IV and Annex XI Sections 1 and 2 under its own decomposition, without Annex XII, the Commission Form or, to our reading of its published documentation, provenance machinery for cited text (actcheck, 2026); and an unmaintained, Form-derived schema dataset whose scope is the Form's rows, not the annex elements. As of that search, no maintained open tool validated Annex XI and Annex XII documentation together with traceability to the legal text. A search can never fully exclude prior art, so Section 8 positions this work against what the search found rather than resting on what it did not.

`gpai-docs` is built on three commitments:

1. **The registry is the single source of truth.** The registry holds an entry for every published element of Annex XI and Annex XII - 25 in all, three of them conditional elements of Annex XI Section 2. Each entry carries the published enumerator, the recipients the Act owes the information to, the element's mapping to the Model Documentation Form (with a recorded note where the Form carries none), drafting guidance, and the verbatim provision text with its retrieval date and SHA-256 hash.
2. **Evidence is verified, not assumed.** The regulation text is machine-extracted from the Publications Office's consolidated version, and the guideline and Code texts are hand-extracted from byte-pinned artifacts. A pipeline re-verifies every source - fetching, extracting, normalising and comparing on a schedule - and reports drift as a finding about the text, never as speculation.
3. **No verdicts.** The tool reports what is missing, ill-typed, or inconsistent with cited text, and it never says "compliant". Every report closes with that statement, and tests sweep the rendered findings and the report for the forbidden vocabulary.

## 2. The registry

**Fields.** The registry holds 25 elements: 11 in Annex XI Section 1, 3 in Annex XI Section 2 and 11 in Annex XII. Each element carries a registry id (`XI.1.1.a` ... `XII.2.c`), the published enumerator as printed, the labels from the Act, the recipient set (`ai_office`, `nca`, `downstream`), the Model Documentation Form rows that carry the element, and the native document key. The three Section 2 elements apply only to models with systemic risk, and the Form does not carry them.

**Sources.** The registry draws on 39 provisions and instrument texts. Thirty-four are extract-mode entries: the AI Act's Annex XI and Annex XII points, the chapeau sentences, the conditioning note after XI.1.2(e), and Articles 51(1)(a), 51(2), 52(1), 53(1)(a), 53(1)(b) and 53(4). Five are artifact-mode entries (Code measures and Commission guideline paragraphs), whose bytes are pinned and whose text was hand-extracted once and verified by a human. Extract-mode entries carry a machine locator (`element`, `chapeau`, `following_note`, `article`), so verification re-derives the text through the same code path that authored it.

**Retrieval.** The consolidated Act is fetched from the Publications Office's Cellar service, and the canonical citation remains the EUR-Lex CELEX identifier. Normalisation is minimal and idempotent: entity decoding, whitespace collapse, Unicode NFC and trimming. Hashes therefore move only when the text does. YAML's implicit typing is a documented trap, and the reader handles it deliberately: it implements YAML 1.2 core number semantics and constructs no dates, so impossible dates and look-alike numbers surface as findings rather than misreadings.

**The consolidation watch.** A dated pin (`02024R1689-20260727`) could silently age while still serving unchanged bytes. Each scheduled verification therefore probes the documented resolver forms - the EUR-Lex legal-content resolver, the undated Cellar resource, and the enacted act's RDF, which names every consolidation layer and is the form that answers. The watch reports a newer layer as one finding kind and an unreachable resolver as another, and it never conflates either with text drift.

## 3. The document format

A native document is YAML or JSON with a `schema: 1` marker, one mapping per annex, and two optional records sections (Art. 52 notifications; modifications). The field registry's tags type every value against a closed vocabulary of text, text-list, number, date, url, compute and energy, of which the shipped elements use text, compute and energy. Two structured shapes exist: compute (`training_flop`, `estimation_method`, `training_time`) and energy (nested training and inference amounts, units and methods). The types exist because the consistency rules must compare numbers, and free prose cannot be compared.

Pydantic v2 models for every element are the single validation authority. A lockstep test binds every registry field to its model and back, and every rule tag to a format reading, and the models project to JSON Schema through `gpai-docs schema`. A completed Model Documentation Form can be imported (`gpai-docs import-docx`) and written back out (`gpai-docs export-docx`), with the Form's coarseness showing at the edges: on import a shared row's text files to every claimant, on export the first carrying claimant's is written, and a row with no response field cannot be carried (Section 7). Presence follows the format's absence semantics: a missing key, null, an empty string and an empty list are all absences, and anything else ill-shaped is a finding rather than a coerced value. Any well-shaped, non-empty value satisfies its element: the tool reads presence, never adequacy, so a clean run means every applicable element was answered, not that the answers are accurate, complete or sufficient.

## 4. The linter

Findings come in four kinds: `missing`, `malformed`, `unknown` and `inconsistent`. The pass order is typed validation, completeness in registry order, unknown keys, and then the consistency rules; a value the typed pass rejects is never re-reported as missing. The refusal is total: a document the typed pass rejects runs no consistency rule, so one malformed value silences the relations a later pass would have reported. The consistency layer implements three rules and the records-completeness table that makes them evaluable, and every finding renders its citations verbatim beneath it:

- **`notification.due`** (Art. 51(1)(a), 51(2), 52(1)): training compute above 10^25 FLOP with no Article 52(1) notification record, a record whose notification exceeds the two-week window, or reversed dates.
- **`compute.reporting`** (guidelines paragraphs 120 and 31; the Form's two-significant-figures and methodology rows): unrounded compute, and estimation methods reported as missing.
- **`modification.one-third`** (guidelines paragraph 60): the guidelines' *indicative* criterion is that a modifier whose change exceeds one third of the model's training compute is treated as the resulting model's provider. The rule reports a recorded modification above that share that the document does not record as a provider record; it quotes the criterion as indicative and never judges. Paragraph 115, which paragraph 60 defers to for how training compute is understood, is not among the registry's sources in this edition, and the rule cites paragraph 60 alone.
- **`record.completeness`**: the fields a notification record must carry to be evaluable (Art. 52(1); paragraph 31), and the description a modification record must carry (paragraph 60).

The engine is a small rule catalogue over a validated document, and the rules stay silent where their inputs are absent or beyond representable precision: the linter declines rather than guesses. Renders carry the element citation, the rule bases as quoted lines, and the Form rows as named lines, and the run closes with the evidence-not-verdict footer. The exit contract is the pipeline's handle, not a verdict: 0 for no findings, 1 for findings, and 2 for input it cannot read at all.

One real transcript shows the shape. Linting a copy of the project's example document - whose training compute stands above 10^25 FLOP - with its notification record removed yields exactly one finding:

```
[INCONSISTENT] XI.1.2.d - Computational resources used to train the model
  Reason: training compute 2.5e+25 FLOP is greater than 10^25 and the document carries no Art. 52(1) notification record
  Key: annex_xi.computational_resources
  Annex XI, Section 1, point 2(d) - owed to: AI Office, NCAs
  Form rows: computational-resources/training-time, computational-resources/training-time-wall-clock-and-hardware-days, computational-resources/amount-of-computation-used-for-training, computational-resources/amount-of-computation-used-for-training-two-significant-figures, computational-resources/measurement-methodology
  Form audience flags: ai_office, nca
  "the computational resources used to train the model (e.g. number of floating point operations), training time, and other relevant details related to the training;"
  Guidance: State the computational resources used to train the model (e.g. number of floating point operations), the training time, and other relevant details related to the training.
  Basis:
  Article 51(1), point (a)
  "it has high impact capabilities evaluated on the basis of appropriate technical tools and methodologies, including indicators and benchmarks;"
  Article 51(2)
  "A general-purpose AI model shall be presumed to have high impact capabilities pursuant to paragraph 1, point (a), when the cumulative amount of computation used for its training measured in floating point operations is greater than 10^25."
  Article 52(1)
  "Where a general-purpose AI model meets the condition referred to in Article 51(1), point (a), the relevant provider shall notify the Commission without delay and in any event within two weeks after that requirement is met or it becomes known that it will be met. That notification shall include the information necessary to demonstrate that the relevant requirement has been met. If the Commission becomes aware of a general-purpose AI model presenting systemic risks of which it has not been notified, it may decide to designate it as a model with systemic risk."
1 findings - engineering evidence, not a compliance verdict
```

## 5. Verification pipeline and drift

Verification re-hashes the registry's stored texts offline on every CI run. Online, it re-fetches each source and compares it through the same normalisation the authoring used, and it classifies every failure: integrity, text changed, artifact changed, new consolidation, could-not-verify and extraction failed. CI never writes. A weekly scheduled workflow runs the online pass; the schedule is newly armed, and its history becomes the record of when verification last happened. During development, the resolver endpoint for the undated consolidation proved unreachable from constrained networks (a web application firewall challenge); the watch reported this honestly as could-not-verify until we implemented the RDF-based resolver that now ships.

## 6. The corpus

The project maintains a corpus of twelve documents, authored here to represent real, public provider documentation (system cards, model cards and technical reports) as native documents. Each value restates the provider's published facts, written in this project's own words from a source fetched and read at authoring time, and some values are instrument derivations where the provider publishes none - a compute figure from the provider's GPU-hours at a stated peak, a notification record the document itself supplies. Each document carries expected findings derived by hand from the registry and re-derived in a review pass that does not run the tool. The findings are concentrated deliberately: the corpus spans a document that is clean by construction (Llama 3.3 70B; the corpus tests the tool, not the provider), gap documents, typing faults, provenance-thin documentation, all three consistency scenarios, an Annex XII-only downstream subset, and a validation-failing chaotic case. The current lint of the twelve yields 47 missing, 7 inconsistent, 4 malformed and 4 unknown findings, alongside the one document that is clean by construction. The corpus is a regression suite over documents we authored, not an evaluation: it shows the rules firing and staying silent on known inputs, and it measures nothing about detection quality on documentation the project did not write. The documents are not distributed while the providers' redistribution terms are unsettled; the provenance record is what ships.

Two properties matter for credibility. First, the expectations are authored before the tool runs - a corpus that merely restates tool output tests nothing - and re-derived in a review pass that does not run the tool; both derivations share the registry the linter reads, so a misreading of the registry would not be caught here. Second, provenance is recorded per document: the source URL, the retrieval date, the byte-hash read at authoring time, and either the published licence or an explicit representation basis where the licence is unclear, with blocked sources recorded as blocked.

## 7. Limitations

- **The English consolidation.** All 24 language versions of the Act are equally authentic, and the registry hashes the English text alone and makes no cross-language comparison.
- **The Form's coarseness.** The Commission's Form does not separate every annex element, and several fields share rows. Import files a shared row's text to every claimant, export writes the first carrying claimant's, and rows the Form gives no response field cannot be carried. We document these corners rather than hiding them.
- **Guidelines are guidance.** Two of the three rules rest on Commission guidelines and the Code's Form, and the third on the Act's own notification provisions. Each source is quoted with its instrument named, and the one-third criterion is labelled indicative wherever it appears.
- **Not legal advice.** The tool is engineering evidence about documents; the authentic texts published in the *Official Journal* govern.
- **Coverage.** The three Annex XI Section 2 elements are checked only for a document that declares systemic risk, and Article 53(1), points (c) and (d) remain out of scope. Annex XI's chapeau asks for its contents as appropriate to the size and risk profile of the model, a proportionality the tool does not judge. The registry and the format are designed to extend to the remaining points.
- **The open-source exemption.** Article 53(2) disapplies Article 53(1), points (a) and (b), for models released under a free and open-source licence with public parameters, unless they carry systemic risk. The registry does not model that exemption, and most of the corpus's documents describe open-weight models; the tool checks such a document as if the duties applied.
- **Hand-authored readings.** The pipeline verifies quoted text and drift; it does not verify judgement. The element decomposition, the recipient sets, the Form mapping and each rule's reading of its instrument are hand-authored in this project and have not been externally audited.

## 8. Related work

A proprietary Node linter validates Hugging Face model cards against Article 53 with closed rules and no annex schema (ReadyStack, 2026). Commercial services generate Annex XI and Annex XII dossier packages rather than validating supplied documents (JurisAI, 2026), and an open package generates Annex XI dossiers (Dümen, 2026). A prototype open validator covers Annex IV and Annex XI Sections 1 and 2 under its own decomposition, without Annex XII, the Commission Form or, to our reading of its published documentation, provenance machinery for cited text (actcheck, 2026). Exchange formats (CycloneDX ML-BOM, SPDX 3.0 AI and OSCAL) address machine-readable exchange rather than traceability to statutory enumerators, and the project's crosswalk connects registry elements to the NIST AI RMF and ISO/IEC targets as navigation, not conformance. The Act has also drawn extensive legal analysis (Veale and Zuiderveen Borgesius, 2021; Hacker, Engel and Mauer, 2023), and the documentation layer we build on is active: Lucaj et al. (2025) publish technical-documentation templates for the Act, and Tao et al. (2026) study twelve AI Act compliance checkers empirically and find that they "currently can only serve as early-stage orientation tools". Our toolchain takes the narrower role still: it checks documentation against the two annexes and issues no verdict at all. No evaluation comparable to the study's has been run on this toolchain; the corpus (Section 6) is a regression suite over documents we authored, and the study's dimensions are the natural frame for one.

## 9. Reproducibility

The toolchain is pure Python (3.13 or later) with three runtime dependencies. The registry's stored texts and the corpus's provenance record are maintained in the repository; the stored texts carry byte-hashes, all tests run offline, and verification is reproducible through the scheduled workflow. The versions we reference are the consolidated Act, CELEX `02024R1689-20260727`, with its successor watch; the Code of Practice (July 2025); and the Commission guidelines C(2025) 7719.

## 10. Conclusion

We have presented `gpai-docs`, an open toolchain that checks GPAI model documentation against Annex XI and Annex XII, and only against them. The toolchain's contribution is provenance over quoted text: every provision a finding cites is verbatim legal text that a scheduled pipeline re-verifies, while the decomposition and each rule's reading of its instrument are hand-authored and recorded as such. The registry is maintained as hash-pinned project data, and the corpus's
provenance record with it. The tool issues no compliance verdict; it reports what is missing, ill-typed or inconsistent with the cited text, and every report says so. Library, CLI, container, registry and methodology notes are maintained in the project repository, and package publication remains a pending decision.

## References

- actcheck. Prototype validator for Annex IV and Annex XI documentation. npm 0.2.0, 2026. <https://github.com/mreza0100/actcheck>
- CycloneDX. CycloneDX 1.6 machine-learning bill of materials. 2024. <https://cyclonedx.org/docs/1.6/>
- Dümen. Annex XI dossier generator. PyPI 0.8.1, 2026. <https://pypi.org/project/dumen/>
- European Commission. Code of Practice for General-Purpose AI Models, including the Model Documentation Form. July 2025. <https://digital-strategy.ec.europa.eu/en/policies/contents-code-gpai>
- European Commission. Guidelines on the scope of the obligations for providers of general-purpose AI models under the AI Act. C(2025) 7719. <https://digital-strategy.ec.europa.eu/en/library/guidelines-scope-obligations-providers-general-purpose-ai-models-under-ai-act>
- Hacker, P., Engel, A. and Mauer, M. (2023). Regulating ChatGPT and other Large Generative AI Models. arXiv:2302.02337. <https://arxiv.org/abs/2302.02337>
- ISO/IEC 22989:2022. Information technology - Artificial intelligence - Artificial intelligence concepts and terminology.
- JurisAI. Commercial generator of Annex XI and Annex XII documentation packages. 2026. <https://www.getjurisai.com/>
- Lucaj, L., Loosley, A., Jonsson, H., Gasser, U. and van der Smagt, P. (2025). TechOps: Technical Documentation Templates for the AI Act. arXiv:2508.08804. <https://arxiv.org/abs/2508.08804>
- NIST. Artificial Intelligence Risk Management Framework (AI RMF 1.0). NIST AI 100-1, 2023. <https://doi.org/10.6028/NIST.AI.100-1>
- OSCAL. Open Security Controls Assessment Language. NIST. <https://pages.nist.gov/OSCAL/>
- ReadyStack. model-card-lint-gpai. PyPI 1.0.9.post1, 2026. <https://pypi.org/project/readystack-model-card-lint-gpai/>
- Regulation (EU) 2024/1689 of the European Parliament and of the Council of 13 June 2024 laying down harmonised rules on artificial intelligence (Artificial Intelligence Act). Consolidated text, CELEX 02024R1689-20260727. <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727>
- SPDX. SPDX 3.0 specification, including its AI profile. <https://spdx.dev/use/specifications/>
- Tao, Z., Kahraman, A., Pan, S., Xing, Z., Ullstein, C., Grossklags, J. and Chen, C. (2026). An Empirical Study and Assessment of EU AI Act Compliance Checkers. arXiv:2609.36228. <https://arxiv.org/abs/2609.36228>
- Veale, M. and Zuiderveen Borgesius, F. (2021). Demystifying the Draft EU Artificial Intelligence Act: Analysing the good, the bad, and the unclear elements of the proposed approach. arXiv:2107.03721. <https://arxiv.org/abs/2107.03721>

## Appendix: artifact availability

Library, CLI, container, registry and methodology notes are maintained in the project repository. Package publication is a pending decision, and this draft claims no availability that has not been made.
