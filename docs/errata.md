# Errata

This log records corrections to the registry, the document format and the
lint rules: what changed, why, and how a reader verifies it. It is
append-only: an entry is never edited or removed once merged, and entries
run newest-first.

A correction lands as its own pull request whose message starts
`fix(registry):` or `fix(format):`, and the errata entry is written in that
same change: a correction without its entry does not merge. The entry shape
is pinned by a test, so a malformed entry fails the build.

The three entries below are backfilled: each correction landed as an ordinary
`docs:` or `fix(documents):` change, before this process existed, and is
recorded here as it happened.

Entries are never edited once merged.

**A note on the Verify lines.** The commit hashes they name belong to the
development history before this repository was published, and do not resolve
here. They are kept as written. Every correction's substance is verifiable
from the files each entry names, all of which are in this repository.

## 2026-10-10 - Dropping leftover rows when reading the Form

**What changed**: Reading the Model Documentation Form drops a leftover row
only when it has no label, no description and no response text; a row that
carries any of the three survives the walk.

**Why**: The rule was previously recorded as dropping a row when its label
and description cells were both empty. Ten walked rows have an empty raw
label while holding response or control text (six) or description text
(four), and the literal rule would have lost six inventory rows
(`license-type-or-category`, `license-additional-assets`,
`number-of-data-points-two-significant-figures`,
`training-time-wall-clock-and-hardware-days`,
`amount-of-computation-used-for-training-two-significant-figures` and
`distribution-and-licenses/distribution-channels-downstream-providers`) from
the Form's 46-row inventory.

**Verify**: commit `2d7ddd7` (`docs: fold the review's drift corrections
into the spec and structure note`) corrected the rule, and commit `74c1f20`
(`docs: correct the erratum's evidence counts`) corrected its evidence counts;
both landed on main in `cac6d0e`. The corrected rule is stated in
`docs/form-docx-structure.md` and implemented in `src/gpai_docs/docxform.py`,
pinned by `tests/test_docx_import.py`.

## 2026-10-09 - Number and date reading in the document reader

**What changed**: The document reader constructs numbers under YAML 1.2's
core schema and never constructs dates from unquoted text. Ints are decimal,
`0o` octal or `0x` hex (`017` reads as seventeen, not as octal fifteen),
floats take an optional dot and a signed exponent (`2.3e25`, `9e+24`), and
YAML 1.1's odd spellings stay strings: `12:30` is not a number and `1_000` is
text, so each is malformed in a number slot rather than guessed. An unquoted
date that is not a real calendar date (`2026-02-30`, `2026-13-01`) is
reported as a malformed value, never a traceback.

**Why**: PyYAML's default 1.1 reading made `12:30` a sexagesimal integer,
`017` an octal one, and an unquoted impossible date crashed below the reader;
each is exactly the kind of misreading the tool exists to report.

**Verify**: commit `c64bd43` (`fix(documents): harden the YAML reader to
1.2-core numbers and safe errors`), ruled and recorded by commit `40be051`
(`docs: rule the YAML reader to 1.2-core numbers and safe errors`); both
landed on main in `661572d`. The readings are pinned in
`tests/test_documents.py`, `tests/test_lint_typed.py` and
`tests/test_cli.py`.

## 2026-10-09 - The demo run's closing line

**What changed**: The first-run demo document (the complete example that
ships with the project) lints clean, and an earlier claim that the demo ends
in a findings exit was corrected: the run-level closing line names the
finding count and the shared footer only, and never prints an exit code.

**Why**: The exit contract is the process's exit status (0 no findings, 1
findings, 2 bad input), not a token in the report, and the shipped demo
answers every element that applies to it, carrying the three Section 2 values
early. The earlier demo output ended `2 findings · exit 1` for a document
that is not the one the project ships; a demo that misstates its own result
misleads the reader it exists for.

**Verify**: commit `692530a` (`docs: fold the recorded rulings into the
spec`), landed on main in `4477aa3`; `gpai-docs lint` over
`tests/fixtures/model-docs-example.yaml` reports `no findings` and exits 0,
pinned by `tests/test_cli.py`.
