# Provider corpus

The corpus is a test instrument for the linter. Each document is a native
document (schema 1) representing one provider model's published facts,
paired with the finding list a correct lint produces for it
(`<slug>.expected.json`). The harness that travels with them discovers
every `corpus/*.yaml`, lints it against the shipped registry, normalises
the findings to kind, location, field id, label and a short message
substring, and compares them exactly, order included (the lint's own
report order).

**The twelve documents are not distributed here.** The provenance record
below, `sources.lock.yaml` beside it, and `scripts/verify-corpus-sources.py`
are what this repository ships: the script re-fetches every recorded source
and checks it against the recorded SHA-256. The documents themselves and the
test that lints them are held back while their redistribution question stays
open, so nothing below should be read as if the files were present.

**Engineering evidence, not a conformance statement.** The corpus is
engineering evidence about this tool, not a conformance statement about any
provider; the documents test the tool, not the models, and a zero-finding
document is not a verdict that any model's real documentation is complete.
Nothing here is a compliance verdict.

## What the documents are

Each value is a representation of the provider's published facts, written in
this project's own words from a source fetched and read at authoring time
(see the provenance table). No long-form provider prose is stored, whatever
a source's licence permits: only short factual spans - names, figure labels,
version numbers - appear verbatim, and the basis is *representation* for
every document, so the corpus never relies on verbatim terms.

Some documents are authored at deliberate completeness levels and some carry
deliberate faults (typing faults, missing methods, unknown keys), all
recorded in the composition table. Those levels and faults are properties of
this test instrument, not findings about any provider.

## Provenance

| Provider | Model | Source title | URL | Retrieved | SHA-256 | Licence as published | Basis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | gpt-oss-120b | gpt-oss-120b model card (Hugging Face README, raw) | <https://huggingface.co/openai/gpt-oss-120b/raw/main/README.md> | 2026-10-10 | `92b0408cf5dce04e4c5e4e5f2be0361da710d3650baefd7d7519badd1c687919` | Apache-2.0 | representation |
| Meta | Llama 3.3 70B Instruct | Llama 3.3 model card (`meta-llama/llama-models`, `models/llama3_3/MODEL_CARD.md`, raw) | <https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_3/MODEL_CARD.md> | 2026-10-10 | `1bad06e0e2feadf6a195fcce4d6a2f7bca48f05b7a25a71f18c2baa88d292adf` | Llama 3.3 Community License Agreement (custom commercial licence) | representation |
| Allen Institute for AI (Ai2) | OLMo 2 13B | OLMo 2 13B model card (Hugging Face README, raw) | <https://huggingface.co/allenai/OLMo-2-1124-13B/raw/main/README.md> | 2026-10-10 | `89a3954d0ca1a8061cd1b228fcfe3336385109c58b63a616a2a873e86bac7e4d` | Apache-2.0 | representation |
| Mistral AI | Mistral Small 24B (2501) | Mistral Small 3 model card (Hugging Face README, raw) | <https://huggingface.co/mistralai/Mistral-Small-24B-Instruct-2501/raw/main/README.md> | 2026-10-10 | `c3889bddcf96969899f867f657f1929f0f66ee9e91cf15870a7b0452a6b5a6ca` | Apache-2.0 | representation |
| Microsoft | Phi-4 | Phi-4 model card (Hugging Face README, raw) | <https://huggingface.co/microsoft/phi-4/raw/main/README.md> | 2026-10-10 | `4cc56faa6a5bcbde6227789b2ef9aedfde481ca660c8a4b686703aae19b00011` | MIT | representation |
| Alibaba | Qwen2.5-72B-Instruct | Qwen2.5-72B-Instruct model card (Hugging Face README, raw) | <https://huggingface.co/Qwen/Qwen2.5-72B-Instruct/raw/main/README.md> | 2026-10-10 | `62d6f2176c0925b7c7e5ec6c5ee06cad83868bb21a8e25d58283e3d7707d3f79` | Qwen licence (custom; the card's `license: other` with `license_name: qwen`) | representation |
| DeepSeek | DeepSeek-V3 | DeepSeek-V3 model card (Hugging Face README, raw) | <https://huggingface.co/deepseek-ai/DeepSeek-V3/raw/main/README.md> | 2026-10-10 | `3739763a851074c810f1565f9823956f3a095231f8c591dd3c254581bdd3cf08` | DeepSeek Model License (Model Agreement) for the weights; MIT for the code repository | representation |
| Meta | Llama 3.1 405B Instruct | Llama 3.1 model card (`meta-llama/llama-models`, `models/llama3_1/MODEL_CARD.md`, raw) | <https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_1/MODEL_CARD.md> | 2026-10-10 | `a37da4be5eb00d97ee0017cadf54c55e8aca84c715fa7d0981d3f2bc13b763ef` | Llama 3.1 Community License (custom commercial licence) | representation |
| BigScience | BLOOM (176B) | BLOOM model card (Hugging Face README, raw) | <https://huggingface.co/bigscience/bloom/raw/main/README.md> | 2026-10-10 | `dfcc25552c185cdba2436f530678b29e39ae542157484d792145126b43d10770` | BigScience BLOOM RAIL 1.0 (the card's `license: bigscience-bloom-rail-1.0`) | representation |
| DeepSeek | DeepSeek-V2 | DeepSeek-V2 model card (Hugging Face README, raw) | <https://huggingface.co/deepseek-ai/DeepSeek-V2/raw/main/README.md> | 2026-10-10 | `8bf7588b4dfe338bfc9fbe544c88a90b9ba659804e739cdfea3418becfbce636` | DeepSeek Model License (Model Agreement) for the weights; MIT for the code repository (the card's `license: other` with `license_name: deepseek`) | representation |
| OpenAI | GPT-4o | GPT-4o System Card (PDF) | <https://cdn.openai.com/gpt-4o-system-card.pdf> | 2026-10-10 | `e2579ecb185cbc13bac39f9dbf25e1917f78e1ea5a3a5023165c6614fb5db724` | unclear (representation basis) | representation |
| TII (Technology Innovation Institute) | Falcon 180B | Falcon 180B model card (Hugging Face model page HTML) | <https://huggingface.co/tiiuae/falcon-180B> | 2026-10-10 | `b1913e0fe6ceac7d9f15626b4c2bc7b5fdd16c05595bdd5ec2595d44fc170f60` | unknown as tagged (the page's `license: unknown`; the card text names the Falcon-180B TII License and Acceptable Use Policy) | representation |

Notes on the fetches:

- Sources are fetched at authoring time through the package's URL fetcher
  into `/tmp` working copies, hashed there, and are never committed; the
  test suite is offline and re-reads no source.
- Meta's Hugging Face copy of the Llama 3.3 card is gated: an unauthenticated
  fetch returns HTTP 401, so the row records the provider's official model
  card in the `meta-llama/llama-models` repository instead. The remaining
  rows record each provider's own published card or documentation, as the
  table names them.
- Mistral AI's Mistral Large 2 card is gated the same way; the planned
  Mistral row therefore uses Mistral Small 24B (2501), whose card fetches
  unauthenticated. The substitution is recorded here, not silently made.
- The four later sources (Mistral Small 24B, Phi-4, Qwen2.5-72B-Instruct and
  DeepSeek-V3) were fetched the same day through the same fetcher, all
  unauthenticated HTTP 200; no substitution was needed for those rows.
- The three sources below (Llama 3.1 405B Instruct, BLOOM and DeepSeek-V2)
  were fetched the same day through the same fetcher, all unauthenticated
  HTTP 200, as were two documents backing their values: the BLOOM paper
  (<https://arxiv.org/html/2211.05100>, retrieved 2026-10-10, SHA-256
  `8d5748a186c178dafed5314b913b08a590e897b8ad9b8b9817d715bc60c10625`,
  CC BY 4.0 per its arXiv page), which corroborates BLOOM's parameter count
  and training figures, and the DeepSeek-Coder-V2 paper
  (<https://arxiv.org/html/2406.11931>, retrieved 2026-10-10, SHA-256
  `6e7918134fb4f3a172c84f909e4470065a80700e4c556b401280d48e3c18238c`,
  CC BY 4.0 per its arXiv page), which is the source of the further
  pretraining the `deepseek-v2` modification record carries. Both are
  fetched at authoring time only and never committed.
- The NVIDIA row (Llama-3.1-Nemotron-70B-Instruct) is substituted by
  DeepSeek-V2, recorded here rather than silently dropped. NVIDIA's model
  card (<https://huggingface.co/nvidia/Llama-3.1-Nemotron-70B-Instruct/raw/main/README.md>,
  retrieved 2026-10-10, SHA-256
  `1f43630164f9377020ab15cff926960aeaaaf8a6435e65b232d0b5a4ca1c6854`) and
  the HelpSteer2-Preference paper
  (<https://arxiv.org/html/2410.01257>, retrieved 2026-10-10, SHA-256
  `91ced148a9ed88c0c06e496e6144459df50814ebf84ddc292eca46ece5783fd1`)
  publish the modification's method but no compute amount: the paper's
  published REINFORCE figure (64 H100-equivalent node-hours, Appendix F) is
  far below one third of Llama 3.1 70B's published training compute, so a
  modification-above-one-third document could not be authored from that
  provider's published facts. DeepSeek's own publications do support it:
  DeepSeek-Coder-V2 is further pretrained from DeepSeek-V2 on 6 trillion
  additional tokens, 74 per cent of the published 8.1-trillion-token
  pretraining.
- The two sources that follow were fetched the same day through the same fetcher,
  all retrieved 2026-10-10: the GPT-4o System Card arrived as a PDF (HTTP
  200, 1,402,648 bytes, read with a PDF text extractor at authoring time)
  and the Falcon 180B model page as HTML (HTTP 200, 294,326 bytes). The
  `gpt-4o` document also draws on the provider's GPT-4o model documentation
  page (<https://platform.openai.com/docs/models/gpt-4o>, retrieved
  2026-10-10, HTTP 200, SHA-256
  `09f3a2170bacf5d847d62b6b3aac333fcbcafb5d701358323b73ae6b6bc09226` of the
  body returned; the fetcher followed the provider's redirect to
  <https://developers.openai.com/api/docs/models/gpt-4o>), which publishes
  the context window, output-token limit, knowledge cutoff and served model
  versions the document's XII.2.b, XII.1.e and XII.2.c values rest on. Like
  the system card, it states no licence, so the GPT-4o row carries the
  representation basis.
- The Falcon 180B card's raw README endpoint is gated: an unauthenticated
  fetch returns HTTP 401 ("Access to model tiiuae/falcon-180B is
  restricted"), so the row records the provider's model page instead, whose
  HTML carries the rendered card text, and the page's own licence metadata
  is `unknown`. The card publishes no release date and no energy figure, so
  the `falcon-180b` document leaves those elements unanswered.
- The Falcon row's hash is of the page as read at authoring time and is not
  re-verifiable: the model page varies per request (request ids and
  sanitizer tokens, a stable byte length), so a fresh fetch hashes
  differently, as a refetch on the authoring day confirmed.
- Where a source's licence is unclear, its row records "unclear
  (representation basis)" instead of a licence; the GPT-4o row is the first
  to need it.

## Composition (twelve documents)

| Slug | Provider | Model | Intended level | Status |
| --- | --- | --- | --- | --- |
| `llama-3-3-70b` | Meta | Llama 3.3 70B Instruct | clean: every element answered, zero findings. Clean by construction at two elements: XI.1.2.d carries the card's published GPU-hour training time and XI.1.2.e a method statement naming its published power and emissions figures, because the card publishes no FLOP and no energy amount | authored |
| `gpt-oss-120b` | OpenAI | gpt-oss-120b | gaps: unanswered elements absent, missing findings only | authored |
| `olmo-2-13b` | Ai2 | OLMo 2 13B | near-complete: three gaps and one compute-reporting finding | authored |
| `mistral-small-24b` | Mistral AI | Mistral Small 24B (2501) | typing faults: a compute amount as prose in the number leaf, a record date as prose ("first quarter 2025"), a misspelt `notified_at`, and five genuinely unanswered elements; the typed pass refuses the document, so no consistency rule runs over it, by design | authored |
| `qwen2-5-72b` | Alibaba | Qwen2.5-72B-Instruct | mid-completeness: eight unanswered elements, no faults | authored |
| `phi-4` | Microsoft | Phi-4 | provenance-thin: compute and energy amounts without their methods, a present-incomplete notification record, and one unanswered element | authored |
| `deepseek-v3` | DeepSeek | DeepSeek-V3 | mid-completeness: five unanswered elements, no faults | authored |
| `llama-3-1-405b` | Meta | Llama 3.1 405B Instruct | compute above 10^25 without a notification record: a complete document whose compute carries this instrument's upper-bound representation of the card's published 30.84-million H100-80GB GPU hours, with no records; the notification-due rule's no-record finding is the only finding | authored |
| `bloom` | BigScience | BLOOM (176B) | compute beyond two significant figures with no estimation method: a complete document whose unrounded six-times-parameters-times-tokens amount draws both element-side compute-reporting findings and nothing else | authored |
| `deepseek-v2` | DeepSeek | DeepSeek-V2 | modification above one third without a provider record: a complete document whose modification record carries DeepSeek-Coder-V2's published further pretraining (six trillion tokens) with no provider record, and whose complete notification record keeps the other rules quiet; the one-third rule's finding is the only finding | authored |
| `gpt-4o` | OpenAI | GPT-4o | Annex XII only: the extract-shaped downstream subset, all eleven Annex XII elements answered from the system card and the API model documentation, four of them stating in the document's own words where the provider publishes nothing; no Annex XI section at all, so the lint is the missing sweep over the eleven Annex XI elements and nothing else | authored |
| `falcon-180b` | TII | Falcon 180B | chaotic: unknown keys at the top level, under the section and under an element, two typing faults (a compute amount as prose, a list where text belongs), and four unanswered elements; the typed pass refuses the document, so no consistency rule runs over it, by design | authored |

The roster is authoritative: substituting a model updates this table in the
same commit - the `deepseek-v2` row stands in for the NVIDIA row, as the
provenance notes above record.
Together the twelve span the composition axes this record sets out: a
clean document and an Annex-XII-only document as the poles, at least one
document per finding kind (missing, malformed, unknown, inconsistent), and
open-weight and closed providers across large and small labs.

Three constructions are worth naming beyond their rows. The `phi-4` card
publishes its training array (1,920 H100-80G GPUs for 21 days) but no FLOP
and no energy figure: the document's compute amount is this instrument's
representation of those published facts - the upper-bound product of
1,920 GPUs for 21 days at the H100's published dense bf16 peak of
989.4 TFLOP/s, rounded to two significant figures (3.4e24 FLOP) - and its
energy amount is the same GPU-hours at 700 W per GPU (about 680 MWh). Both
deliberately carry no method; no shipped consistency rule reads energy
subfields, so the energy amount draws no finding (recorded here per the
rules as shipped). Its notification record is present-incomplete - a
represented compute and both dates, no estimation method - so the records
side of the compute-reporting rule and the records-completeness table both
speak; the record's compute is instrument-authored at ten times the
element's figure (above Art. 51(2)'s threshold by design - no shipped rule
reads a record's compute against that threshold - and the element's
derivation above does not extend to it). The `mistral-small-24b` faults
refuse the document, so its
notification record's above-threshold compute draws no rule finding, by
design.

The three consistency-rule documents are constructed the same recorded way.
The `llama-3-1-405b` document is complete and carries no records; its
compute amount is this instrument's representation of the card's published
facts - the upper-bound product of the card's 30.84 million H100-80GB GPU
hours at the H100's published dense bf16 peak of 989.4 TFLOP/s, rounded to
two significant figures (1.1e26 FLOP) - and its estimation method states
that derivation. The finding does not rest on the peak assumption: the
standard six-times-parameters-times-tokens estimate over the same card's
published figures (405 billion parameters, about 15 trillion tokens) is
3.6e25 FLOP, also above 10^25. The `bloom` document is complete with no
records; its compute amount is six times the card's published 176 billion
parameters times its 366 billion seen tokens, deliberately left unrounded
at 3.86496e23 FLOP - the over-precision its row names as the fault - and it
carries no estimation method, so both element-side compute-reporting
findings and nothing else speak; the card publishes no energy amount, so
its energy element carries a method statement of what the card reports
(forthcoming emissions and electricity estimates) and no amount. The
`deepseek-v2` document is complete; its compute amount is six times the
card's published 21 billion activated parameters times its 8.1 trillion
training tokens, rounded to two significant figures (1.0e24 FLOP), and its
modification record carries the same convention over DeepSeek-Coder-V2's
published 6 trillion further-pretraining tokens (7.6e23 FLOP), 74 per cent
of the element's compute - above one third whether the original is read as
the complete base or as the 4.2-trillion-token intermediate checkpoint the
paper names - with no provider record, so the one-third rule's finding is
the only finding. Its notification record is complete and valid (compute
restated at two significant figures with a method, dates seven days apart)
and is instrument content, as `phi-4`'s is; its energy element states that
the card publishes no figure there, which draws no finding because no
shipped rule reads energy subfields.

The two poles close the roster. The `gpt-4o` document is the extract-shaped
one: a `schema` marker and an `annex_xii` mapping, nothing else - the shape
`gpai-docs extract annex-xii` writes - so its lint is the missing sweep over
every Annex XI element, eleven findings, and nothing else. Its values are
this instrument's representation of the provider's system card and API
model documentation; where the provider publishes nothing for an element's
own subject (a release date, licence terms, hardware or software
interaction, a parameter count), the value says so in the document's own
words, which is instrument wording rather than a provider fact, recorded
here so the composition stays visible. The `falcon-180b` document is the
chaotic pole: unknown keys at the top level (`model_name`), under the
section (a misspelt `license` in place of `licence`, which leaves the
element itself unanswered) and under an element (`flops` beside
`training_flop`), two typing faults (a compute amount as prose, a list of
intended uses where one text belongs) and four unanswered elements. The
pole is one deliberately chaotic document (unknown keys, malformed values
and an inconsistency together); the shipped rule makes that one document
impossible - any malformed value or unknown key
fails whole-document validation, and a refused document runs no consistency
rule - so the chaotic pole implements the validation-failing flavour and
this record states the rule plainly: malformed findings first, then the
missing sweep, then the unknown keys, and no consistency finding at all.
The inconsistency coverage lives in the three consistency-rule documents
above.
