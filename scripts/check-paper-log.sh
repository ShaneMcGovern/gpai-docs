#!/usr/bin/env bash
#
# Fail on a paper log that carries TeX errors or a significant overfull box.
# arXiv's format rules put text inside the margins, and pdflatex exits 0 while
# quietly letting a long reference URL run past them - so the log, not the
# exit code, is the check. A hairline overfull (a few points) is tolerated.
#
# usage: bash scripts/check-paper-log.sh [log]   (default paper/main.log)

set -euo pipefail

log="${1:-paper/main.log}"
if [ ! -f "$log" ]; then
  echo "no TeX log at $log" >&2
  exit 2
fi

status=0

if grep -q "^!" "$log"; then
  echo "the TeX log carries errors:" >&2
  grep -n "^!" "$log" >&2
  status=1
fi

# -F: the log spells it "Overfull \hbox", and in a basic regular expression
# the backslash-h is a literal h, so an unquoted pattern here matches nothing
# and the check silently always passes - which is how this script first
# shipped.
worst="$(grep -F 'Overfull \hbox' "$log" | sed -E 's/.*\(([0-9.]+)pt.*/\1/' | sort -rn | head -1 || true)"
worst="${worst:-0}"
if awk -v worst="$worst" 'BEGIN { exit !(worst > 5) }'; then
  echo "overfull boxes wider than 5pt (text runs into the margin):" >&2
  grep -F 'Overfull \hbox' "$log" >&2
  status=1
fi

if [ "$status" -eq 0 ]; then
  echo "log clean: no errors, worst overfull ${worst}pt"
fi
exit "$status"
