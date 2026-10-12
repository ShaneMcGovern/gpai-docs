"""Tests for the paper renderer.

The renderer turns ``docs/paper.md`` into the arXiv LaTeX source. Its
output format is pinned here, rule by rule; the drift check at the end
keeps the committed ``paper/main.tex`` in step with the markdown.
"""

import importlib.util
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Spelled by code point, so this file too stays ASCII.
UDIAERESIS = chr(0xFC)


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_paper", ROOT / "scripts" / "render-paper.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: dataclasses (and pickling) look the module
    # up in sys.modules while the class body is processed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rp = _load()


def _paper(*blocks: str) -> str:
    body = "\n\n".join(blocks)
    if "## " not in body:
        body = "## 1. Introduction\n\n" + body
    return "# A title\n\n" + body + "\n"


def test_title_and_sections() -> None:
    tex = rp.render_paper(
        _paper(
            "## 1. Introduction", "We present a tool.", "## 2. Related work", "We cite."
        )
    )
    title = tex.index("\\title{A title}")
    assert "\\author{Shane McGovern}" in tex
    assert "\\date{October 2026}" in tex
    first = tex.index("\\section{Introduction}")
    second = tex.index("\\section{Related work}")
    assert title < first < second


def test_abstract_environment() -> None:
    tex = rp.render_paper(
        _paper("## Abstract", "We present a tool.", "## 1. Introduction", "Body.")
    )
    start = tex.index("\\begin{abstract}")
    end = tex.index("\\end{abstract}")
    assert start < tex.index("We present a tool.") < end
    assert "\\section{Abstract}" not in tex


def test_inline_emphasis_and_code() -> None:
    tex = rp.render_paper(_paper("a **bold** word, an *italic* one, a `code` span"))
    assert "\\textbf{bold}" in tex
    assert "\\emph{italic}" in tex
    assert "\\texttt{code}" in tex
    nested = rp.render_paper(_paper("**`notification.due`**"))
    assert "\\textbf{\\texttt{notification.due}}" in nested


def test_specials_are_escaped() -> None:
    tex = rp.render_paper(_paper("100% of A & B_1 #2 {4}"))
    for escaped in ("\\%", "\\&", "\\_", "\\#", "\\{", "\\}"):
        assert escaped in tex


def test_tilde_and_caret_escape() -> None:
    tex = rp.render_paper(_paper("a~b and c^d"))
    assert "\\textasciitilde{}" in tex
    assert "\\textasciicircum{}" in tex


def test_compute_power() -> None:
    tex = rp.render_paper(_paper("above 10^25 FLOP with no record"))
    assert "10\\textsuperscript{25} FLOP" in tex


def test_straight_quote_pairs() -> None:
    tex = rp.render_paper(_paper('never says "compliant" to anyone'))
    assert "``compliant''" in tex
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper('one "unpaired quote'))


def test_lists() -> None:
    bullets = rp.render_paper(_paper("- alpha", "- beta"))
    assert "\\begin{itemize}" in bullets
    assert bullets.count("\\item") == 2
    numbered = rp.render_paper(_paper("1. alpha", "2. beta"))
    assert "\\begin{enumerate}" in numbered
    assert numbered.count("\\item") == 2


def test_workflow_lines_dropped() -> None:
    md = _paper(
        "**A draft working paper for the gpai-docs project.**",
        "**Status:** draft, for maintainer review; submission is not made.",
        "## 1. Introduction",
        "Body.",
    )
    tex = rp.render_paper(md)
    assert "draft working paper" not in tex
    assert "Status:" not in tex


def test_diacritics_map_to_escapes() -> None:
    name = f"D{UDIAERESIS}men"
    tex = rp.render_paper(_paper(f"See {name} for the argument."))
    assert 'D\\"umen' in tex
    assert tex.isascii()


def test_unknown_non_ascii_refused() -> None:
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper(f"a caf{chr(0xE9)} in Brussels"))


def test_unsupported_constructs_refused() -> None:
    for line in (
        "| a | b |",
        "see [the guide](https://x.example)",
        "![img](x.png)",
        "math $x$ here",
    ):
        with pytest.raises(rp.RenderError):
            rp.render_paper(_paper(line))


def test_urls_render_as_url_macro() -> None:
    tex = rp.render_paper(
        _paper(
            "## References", "- EUR-Lex, https://eur-lex.europa.eu/x, retrieved 2026."
        )
    )
    assert "\\url{https://eur-lex.europa.eu/x}" in tex
    assert "\\url{https://eur-lex.europa.eu/x}," in tex


def test_references_hanging_paragraphs() -> None:
    tex = rp.render_paper(_paper("## References", "- First entry.", "- Second entry."))
    assert "\\section*{References}" in tex
    assert "\\begin{itemize}" not in tex
    entries = [
        line
        for line in tex.splitlines()
        if line.startswith("\\noindent\\hangindent=1em")
    ]
    assert len(entries) == 2
    # Entries are separate paragraphs: a single newline would let LaTeX run
    # them together into one.
    lines = tex.splitlines()
    second = lines.index(entries[1])
    assert lines[second - 1] == ""


def test_section_numbers_are_stripped_and_checked() -> None:
    tex = rp.render_paper(
        _paper("## 1. Introduction", "Body.", "## 2. Related work", "More.")
    )
    assert "\\section{Introduction}" in tex
    assert "\\section{Related work}" in tex
    assert "1. Introduction" not in tex
    # The markdown's numbering is what the prose's "Section 8" cross-references
    # rely on, so a gap or a repeat stops the render rather than renumbering.
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "a", "## 3. Related work", "b"))
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## Unnumbered", "a", "## 1. Introduction", "b"))


def test_appendix_heading() -> None:
    tex = rp.render_paper(
        _paper("## Appendix: artifact availability", "They live in the repository.")
    )
    assert "\\appendix" in tex
    assert "\\section{Artifact availability}" in tex


def test_check_reports_drift() -> None:
    md = _paper("## 1. Introduction", "Body.")
    tex = rp.render_paper(md)
    assert rp.check(md, tex) == []
    problems = rp.check(md, "something else")
    assert problems


def test_marker_and_no_today() -> None:
    tex = rp.render_paper(_paper("## 1. Introduction", "Body."))
    assert tex.startswith(rp.MARKER)
    assert "\\today" not in tex


# The paper directory's structure: the submission source plus its own
# documentation and build entry point. No compiled artifact is tracked.

PAPER = ROOT / "paper"


def test_paper_directory_holds_the_submission_files() -> None:
    present = {path.name for path in PAPER.iterdir() if path.is_file()}
    assert {"main.tex", "README.md", "build.sh", ".gitignore"} <= present


def test_no_build_output_is_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "paper/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tracked, "the paper directory is not tracked"
    for path in tracked:
        assert path.endswith((".tex", ".md", ".sh", ".gitignore")), path


def test_committed_tex_matches_the_render() -> None:
    result = subprocess.run(
        ["uv", "run", "python", "scripts/render-paper.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_tex_is_ascii_and_has_no_today() -> None:
    raw = (PAPER / "main.tex").read_bytes()
    assert all(byte < 128 for byte in raw)
    assert b"\\today" not in raw


def test_preamble_is_the_allowed_set() -> None:
    tex = (PAPER / "main.tex").read_text(encoding="utf-8")
    assert "\\documentclass[11pt]{article}" in tex
    packages = re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    assert packages == ["geometry", "microtype", "listings", "hyperref"]


def test_paper_file_names_fit_arxiv() -> None:
    # arXiv accepts a-z A-Z 0-9 _ + - . , = in file names, case-sensitive.
    for path in PAPER.rglob("*"):
        for part in path.relative_to(PAPER).parts:
            assert re.fullmatch(r"[A-Za-z0-9_+.,=-]+", part), path


# The prose rules and the claims the paper may not lose. The claims list is
# the inventory of what the text asserts; a later edit that drops one fails
# here rather than passing unnoticed.

CLAIMS = [
    "2 August 2025",
    "2 August 2026",
    "2 August 2027",
    "25 elements",
    "22 checked by default",
    "11 in Annex XI Section 1",
    "11 in Annex XII",
    "39 provisions",
    "Thirty-four are extract-mode",
    "Five are artifact-mode",
    "10^25 FLOP",
    "two-week window",
    "one third",
    "twelve documents",
    "47 missing, 7 inconsistent, 4 malformed and 4 unknown",
    "02024R1689-20260727",
    "C(2025) 7719",
    "SHA-256",
    "notification.due",
    "compute.reporting",
    "modification.one-third",
    "record.completeness",
    "engineering evidence",
    'never says "compliant"',
    "no compliance verdict",
    "YAML 1.2 core number semantics",
    "24 language versions",
    "3.13 or later",
    "three runtime dependencies",
    "51(1)(a)",
    "Article 53(1), points (c) and (d)",
    "A search can never fully exclude prior art",
    "Article 53(2) disapplies Article 53(1), points (a) and (b)",
    "reads presence, never adequacy",
    "regression suite over documents we authored",
    "0 for no findings, 1 for findings, and 2 for input it cannot read at all",
    "import-docx",
    "the provenance record is what ships",
]


def _paper_text() -> str:
    return (ROOT / "docs" / "paper.md").read_text(encoding="utf-8")


def _style_problems(text: str) -> list[str]:
    problems = []
    contractions = (
        r"\b\w+n't\b|\b(?:it|we|they|you|that|there|what|who|he|she)'s\b"
        r"|\b\w+'re\b|\b\w+'ve\b|\b\w+'ll\b|\b\w+'d\b|\bI'm\b"
    )
    for match in re.finditer(contractions, text, re.IGNORECASE):
        problems.append(f"contraction: {match.group(0)}")
    # The lookbehind exempts an author's initial ("M. and Mauer"), which is a
    # period but not a sentence end. It is wrapped in (?-i:) because the
    # pattern is otherwise case-insensitive, which would make [A-Z] match any
    # letter and exempt every sentence.
    excluded = r"(?:^|(?-i:(?<![A-Z]\.))(?<=[.!?])\s+)(?:And|But|Yet|So|Or)\b"
    for match in re.finditer(excluded, text, re.IGNORECASE):
        problems.append(f"sentence-initial conjunction: {match.group(0).strip()}")
    return problems


def test_paper_has_no_contractions_or_initial_conjunctions() -> None:
    assert _style_problems(_paper_text()) == []
    # The checker has teeth: the comma-less forms and mixed case are caught too,
    # mid-paragraph as well as at the file's start.
    assert _style_problems("But, it's done. And, we can't.") != []
    assert _style_problems("But we find otherwise.") != []
    assert _style_problems("The work is done. But we find otherwise.") != []
    assert _style_problems("This holds. Yet there is still room.") != []
    assert _style_problems("It is finished. So the gap remains.") != []
    assert _style_problems("It is finished. And the record shows it.") != []
    assert _style_problems("It's done. That's the rule. We'd agree.") != []


def test_style_conjunction_check_exempts_author_initials() -> None:
    # "Mauer, M. and Engel" ends a fragment with an initial, not a sentence;
    # the exemption must not swallow ordinary sentences ending in a letter.
    assert _style_problems("Engel, A. and Mauer, M.") == []
    assert _style_problems("See Veale, M. and Zuiderveen Borgesius, F.") == []
    assert _style_problems("The work is done. But not everyone agrees.") != []


def test_abstract_within_arxiv_limit() -> None:
    abstract = re.search(r"## Abstract\n\n(.*?)\n\n## ", _paper_text(), re.S)
    assert abstract is not None
    assert len(abstract.group(1)) <= 1920


def _reference_entries(text: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index("## References")
    return [line for line in lines[start + 1 :] if line.startswith("- ")]


def test_references_entries_carry_a_locator() -> None:
    entries = _reference_entries(_paper_text())
    assert len(entries) >= 10
    for entry in entries:
        assert (
            re.search(r"https?://\S+", entry)
            or re.search(r"arXiv:\d{4}\.\d{4,5}", entry)
            or entry.startswith("- ISO/IEC ")
        ), entry


def test_paper_claims_are_pinned() -> None:
    text = _paper_text()
    missing = [claim for claim in CLAIMS if claim not in text]
    assert not missing, f"claims dropped from the paper: {missing}"


def test_autolink_renders_as_a_url_macro() -> None:
    # markdownlint wraps bare URLs in angle brackets (MD034); the pair is
    # markdown autolink syntax and must not reach the LaTeX.
    tex = rp.render_paper(_paper("## References", "- Entry. <https://example.org/x>"))
    assert "\\url{https://example.org/x}" in tex
    assert "<" not in tex and ">" not in tex


def test_angle_brackets_in_prose_are_escaped() -> None:
    tex = rp.render_paper(_paper("a < b and c > d"))
    assert "\\textless{}" in tex
    assert "\\textgreater{}" in tex


# Renderer hardening: inputs a future edit could plausibly introduce that must
# either render correctly or stop the render loudly, never mangle silently.


def test_indented_content_is_refused() -> None:
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "- outer item\n  - nested item"))
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "- outer item\n  continuation"))


def test_numbered_lists_run_from_one_without_gaps() -> None:
    tex = rp.render_paper(_paper("## 1. Introduction", "1. a", "2. b"))
    assert "\\begin{enumerate}" in tex
    with pytest.raises(rp.RenderError):
        rp.render_paper(
            _paper("## 1. Introduction", "2024. The Act entered into force.")
        )
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "1. a", "3. b"))


def test_appendix_heading_preserves_acronyms() -> None:
    tex = rp.render_paper(_paper("## Appendix: ISO/IEC mappings", "Body."))
    assert "\\section{ISO/IEC mappings}" in tex


def test_a_status_note_inside_a_section_is_kept() -> None:
    # Only the title block's workflow notes are dropped; the same words in
    # the body are prose.
    tex = rp.render_paper(_paper("## 1. Introduction", "**Status:** checked in code."))
    assert "checked in code" in tex


def test_url_punctuation_stays_out_of_the_link() -> None:
    paren = rp.render_paper(
        _paper("## 1. Introduction", "See (https://example.org/a) for details.")
    )
    assert "\\url{https://example.org/a}" in paren
    colon = rp.render_paper(
        _paper("## 1. Introduction", "See https://example.org/a: it matters.")
    )
    assert "\\url{https://example.org/a}" in colon


def test_backslash_in_prose_is_escaped() -> None:
    tex = rp.render_paper(
        _paper("## 1. Introduction", "The regex \\d+ matches digits.")
    )
    assert "\\textbackslash{}d+" in tex


def test_footnote_marker_is_refused() -> None:
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "See the note[^1]."))


def test_autolink_requires_a_scheme() -> None:
    tex = rp.render_paper(_paper("## 1. Introduction", "the process <httpd> runs"))
    assert "\\url" not in tex


def test_long_urls_can_break_and_references_are_ragged() -> None:
    # Without break points a reference URL runs into the margin; the preamble
    # carries them, and the entries are ragged right so justification cannot
    # fight an unbreakable line.
    tex = rp.render_paper(
        _paper("## References", "- Entry. <https://example.org/a-very-long-path>")
    )
    assert "\\def\\UrlBreaks" in tex
    assert "\\Urlmuskip" in tex
    assert "{\\raggedright\\sloppy" in tex


def test_paper_log_check_fails_on_errors_and_overfull_boxes(tmp_path: Path) -> None:
    # The pattern must match the log's real spelling ("Overfull \hbox"); a
    # broken pattern reports a permanent false green, which is how the first
    # version of this script shipped.
    script = ROOT / "scripts" / "check-paper-log.sh"

    def run(text: str) -> int:
        log = tmp_path / "main.log"
        log.write_text(text, encoding="utf-8")
        result = subprocess.run(
            ["bash", str(script), str(log)], capture_output=True, text=True, check=False
        )
        return result.returncode

    assert run("Output written on main.pdf (6 pages).\n") == 0
    assert run("! Undefined control sequence.\n") == 1
    assert (
        run("Overfull \\hbox (135.3pt too wide) in paragraph at lines 245--246\n") == 1
    )
    # A hairline overfull is tolerated.
    assert run("Overfull \\hbox (2.1pt too wide) in paragraph at lines 1--2\n") == 0


def test_refusals_cover_list_items_and_headings() -> None:
    for construct in (
        "- see [the guide](https://x.example) here",
        "- an ![img](x.png) here",
        "- a note[^1] here",
        "- | a | b |",
    ):
        with pytest.raises(rp.RenderError):
            rp.render_paper(_paper("## 1. Introduction", construct))
    with pytest.raises(rp.RenderError):
        rp.render_paper("# A [title](x)")
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "Name | Value", "--- | ---"))


def test_numbered_item_refusals() -> None:
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "1. a $x$ here"))


def test_code_block_renders_verbatim_in_a_listing() -> None:
    md = _paper(
        "## 1. Introduction",
        "Before.",
        "```",
        "10^25 *not italic* [not a link] _underscored_",
        "```",
        "After.",
    )
    tex = rp.render_paper(md)
    assert "\\begin{lstlisting}" in tex
    block = tex.split("\\begin{lstlisting}")[1].split("\\end{lstlisting}")[0]
    assert "10^25 *not italic* [not a link] _underscored_" in block
    assert "\\textsuperscript" not in block
    assert "\\emph" not in block
    assert "\\_" not in block


def test_code_block_refuses_non_ascii_and_unclosed_and_end_marker() -> None:
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "```", "caf" + chr(0xE9), "```"))
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "```caf" + chr(0xE9), "x", "```"))
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "```", "text without a close"))
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "```", "\\end{lstlisting}", "```"))


def test_fence_inside_a_list_is_refused() -> None:
    with pytest.raises(rp.RenderError):
        rp.render_paper(_paper("## 1. Introduction", "- item", "```", "x", "```"))
