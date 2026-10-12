#!/usr/bin/env bash
#
# Build the paper locally. pdflatex is preferred because it is the engine
# family arXiv runs; tectonic is accepted as a fallback for machines
# without a TeX Live install.
#
# usage: bash paper/build.sh

set -euo pipefail

cd "$(dirname "$0")"

if command -v pdflatex >/dev/null 2>&1; then
  # Two passes so the table of contents and cross-references settle.
  # -halt-on-error stops at the first error and says little on the console;
  # the log's errors are shown instead of losing them in the transcript.
  if ! pdflatex -halt-on-error -interaction=nonstopmode main.tex >/dev/null; then
    echo "pdflatex failed; the log's errors:" >&2
    grep -n "^!" main.log >&2 || tail -20 main.log >&2
    exit 1
  fi
  pdflatex -halt-on-error -interaction=nonstopmode main.tex >/dev/null
  # pdflatex exits 0 on an overfull box; the log check is what fails a layout
  # that runs into the margin.
  bash ../scripts/check-paper-log.sh main.log
elif command -v tectonic >/dev/null 2>&1; then
  # tectonic writes no .log, so the margin check above cannot run here; CI
  # compiles with pdflatex under TeX Live and is the authoritative check.
  tectonic main.tex
else
  echo "neither pdflatex nor tectonic is on PATH" >&2
  exit 1
fi

echo "wrote paper/main.pdf"
