#!/usr/bin/env python3
"""Fetch the corpus's recorded sources and verify their SHA-256 hashes.

The provider sources behind the corpus's twelve documents are fetched at
authoring time, hashed, and never committed, and the authored documents
themselves are not distributed while their redistribution question is open.
This script is what a reader gets instead: it re-fetches every source the
provenance record names, checks the bytes against the recorded hash, and
prints what it found, so the record can be re-verified without anything
being redistributed.

Sources recorded as not re-verifiable (the Falcon 180B model page varies
per request) are reported and skipped, never counted as failures.

usage:
    uv run python scripts/verify-corpus-sources.py [--save DIR] [--only SLUG]

exit codes: 0 every re-verifiable source matched; 1 any mismatch or fetch
failure.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# The lock sits beside the human record it mirrors.
DEFAULT_LOCK = Path(__file__).resolve().parent.parent / "corpus" / "sources.lock.yaml"

# Some hosts refuse urllib's default agent; name the tool and the project.
USER_AGENT = (
    "gpai-docs-corpus-source-verification/1.0 "
    "(+https://github.com/ShaneMcGovern/gpai-docs)"
)

EXTENSIONS = {".md": ".md", ".pdf": ".pdf"}


def fetch(url: str, timeout: float) -> bytes:
    """The URL's bytes, following redirects, with a named user agent."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def extension_for(url: str) -> str:
    """The saved file's suffix: HTML pages land as .html, files keep theirs."""
    suffix = Path(url.split("?")[0]).suffix.lower()
    return EXTENSIONS.get(suffix, ".html")


def save(directory: Path, slug: str, url: str, body: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}{extension_for(url)}"
    path.write_bytes(body)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        metavar="DIR",
        help="keep each fetched source in DIR",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="SLUG",
        help="verify only this slug (repeatable)",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    arguments = parser.parse_args()

    record = yaml.safe_load(arguments.lock.read_text(encoding="utf-8"))
    failures = 0
    checked = 0
    for entry in record["entries"]:
        slug = entry["slug"]
        if arguments.only and slug not in arguments.only:
            continue
        if entry.get("reverifiable", True) is False:
            print(f"skip     {slug:<32} {entry.get('note', 'not re-verifiable')}")
            continue
        try:
            body = fetch(entry["url"], arguments.timeout)
        except (urllib.error.URLError, TimeoutError) as error:
            failures += 1
            print(f"FETCH    {slug:<32} {error}")
            continue
        checked += 1
        digest = hashlib.sha256(body).hexdigest()
        if digest == entry["sha256"]:
            kept = (
                save(arguments.save, slug, entry["url"], body)
                if arguments.save
                else None
            )
            suffix = f"  -> {kept}" if kept else ""
            print(f"ok       {slug:<32} {entry['licence']}{suffix}")
        else:
            failures += 1
            print(
                f"MISMATCH {slug:<32} expected {entry['sha256'][:16]}... "
                f"got {digest[:16]}...  {entry['url']}"
            )
    print(f"\n{checked} source(s) checked, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
