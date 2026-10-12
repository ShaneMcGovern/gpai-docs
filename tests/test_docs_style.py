"""Pin the plain style rule across the shipped documents.

Only the two allowances in ``ALLOWED`` may carry non-ASCII characters, and
no document may hardcode the release version.
"""

from pathlib import Path

import pytest

# Spelled by code point, so this file too stays ASCII.
ALLOWED = {
    # The Official Journal's change-bar mark (the black down-pointing
    # triangle), as the source prints it and the extractor matches it.
    "docs/methodology.md": chr(0x25BC),
    # The errata log's 2026-10-09 entry quotes a transcript from before the
    # plain-output change; the append-only log keeps that middle dot. Every
    # other character in every shipped document is ASCII.
    "docs/errata.md": chr(0x00B7),
    # A cited tool's published name carries its diaeresis (Dumen with the
    # u-umlaut, the Turkish name the package publishes under); a name is
    # reprinted as published, and the renderer maps it to a LaTeX escape.
    "docs/paper.md": chr(0xFC),
}

DOCUMENTS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/methodology.md",
    "docs/paper.md",
    "docs/form-docx-structure.md",
    "docs/errata.md",
    "docs/authoring.md",
    "corpus/README.md",
)

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("name", DOCUMENTS)
def test_document_is_plain_ascii(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    allowed = ALLOWED.get(name, "")
    unexpected = sorted({c for c in text if ord(c) > 127 and c not in allowed})
    assert not unexpected, f"{name} contains {unexpected}"


def test_exception_list_is_exact() -> None:
    # The exact files and characters, so widening an allowance is a
    # deliberate edit, never a silent one.
    assert {
        "docs/methodology.md": chr(0x25BC),
        "docs/errata.md": chr(0x00B7),
        "docs/paper.md": chr(0xFC),
    } == ALLOWED


def test_shipped_documents_do_not_hardcode_the_release_version() -> None:
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    for name in DOCUMENTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert version not in text, f"{name} hardcodes version {version}"
