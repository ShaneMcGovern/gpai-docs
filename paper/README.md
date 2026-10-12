# The paper source

The arXiv submission source for the working paper at `docs/paper.md`.
`main.tex` is generated from that markdown; the markdown is the one home
of the prose, and a test fails when the two fall out of step.

## Regenerating

```bash
uv run python scripts/render-paper.py           # write paper/main.tex
uv run python scripts/render-paper.py --check   # fail if it is stale
```

Edit `docs/paper.md`, never `main.tex`. The renderer refuses markdown it
does not know (tables, links, images, math, a dollar sign), refuses
non-ASCII characters outside the one mapped diacritic in a cited name,
and checks that the sections are numbered contiguously, because the
prose's cross-references rely on those numbers.

## Building

```bash
bash paper/build.sh
```

The script uses `pdflatex` when it is installed and `tectonic` otherwise,
and writes `main.pdf` beside the source. The build outputs are ignored by
git. CI compiles the same source with TeX Live 2025 (arXiv's default) on
every pull request.

## The submission

The bundle is `main.tex` alone: arXiv compiles from the root of the
upload, strips auxiliary files, and needs no `.bbl` here because the
reference list is rendered, not BibTeX-processed. The remaining
submission decisions - authorship, licence, categories, endorsement,
the status line - are not settled here, and nothing is submitted until
every one of them is.
