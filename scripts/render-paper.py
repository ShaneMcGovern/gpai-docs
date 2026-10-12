#!/usr/bin/env python3
"""Render docs/paper.md as the arXiv LaTeX source, paper/main.tex.

The markdown subset is closed: one title, section headings, paragraphs,
bold, italics, code spans, fenced code blocks (rendered verbatim in a
listing, never reflowed, though like every line they are right-trimmed),
bullet and numbered lists, bare URLs and autolinks. Anything else -
tables and rules, links, images, footnote markers, a dollar sign (math or
currency), indented content (nested or wrapped list items), a
non-contiguous numbered list - stops the render with a message naming the
line, because a silent guess would put unverified prose into the
submission. The checks run over headings, list items and paragraphs
alike.

The output is ASCII. The one attested diacritic in a cited name (the
u-umlaut in Dumen) maps to a LaTeX escape; any other non-ASCII character
is refused the same way, so a newly cited name forces a deliberate edit
here rather than a mojibake'd bibliography.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MARKER = (
    "% Generated from docs/paper.md by scripts/render-paper.py - do not edit by hand."
)
AUTHOR = "Shane McGovern"
DATE = "October 2026"

# Key written by code point so this file stays ASCII. The set mirrors the
# style test's pinned exception for docs/paper.md exactly: a newly cited name
# that needs a new character is a deliberate edit in both places.
DIACRITICS = {chr(0xFC): '\\"u'}

ESCAPES = {
    "%": "\\%",
    "&": "\\&",
    "_": "\\_",
    "#": "\\#",
    "{": "\\{",
    "}": "\\}",
    "~": "\\textasciitilde{}",
    "<": "\\textless{}",
    ">": "\\textgreater{}",
    "\\": "\\textbackslash{}",
}

_NUMBERED = re.compile(r"^\d+\. ")
_SECTION_NUMBER = re.compile(r"^(\d+)\. ")
_SUPERSCRIPT = re.compile(r"\^(\d+)")
_URL = re.compile(r"https?://\S+")
_TRAILING_PUNCTUATION = ".,;:!?>"
_WRAP = 78


class RenderError(ValueError):
    """The markdown uses a construct the renderer does not support."""

    def __init__(self, line_number: int, line: str, reason: str) -> None:
        super().__init__(f"line {line_number}: {reason}: {line.strip()!r}")
        self.line_number = line_number


@dataclass
class _Section:
    """One destination: an ordinary section, the abstract, or References."""

    name: str
    kind: str  # "section" | "abstract" | "references" | "appendix"
    blocks: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


def _escape(char: str, line_number: int, line: str) -> str:
    if char in ESCAPES:
        return ESCAPES[char]
    if char in DIACRITICS:
        return DIACRITICS[char]
    if char == "$":
        raise RenderError(line_number, line, "a dollar sign is not supported")
    if ord(char) > 127:
        raise RenderError(
            line_number,
            line,
            f"non-ASCII character {char!r} is not in the diacritic map",
        )
    return char


def _inline(text: str, line_number: int, line: str) -> str:
    """Render one run of markdown text as LaTeX: code, bold, italics, URLs, escapes."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "`":
            end = text.find("`", index + 1)
            if end == -1:
                raise RenderError(line_number, line, "unclosed code span")
            inner = "".join(
                _escape(c, line_number, line) for c in text[index + 1 : end]
            )
            out.append(f"\\texttt{{{inner}}}")
            index = end + 1
        elif text.startswith("**", index):
            end = text.find("**", index + 2)
            if end == -1:
                raise RenderError(line_number, line, "unclosed bold span")
            inner = _inline(text[index + 2 : end], line_number, line)
            out.append(f"\\textbf{{{inner}}}")
            index = end + 2
        elif char == "*":
            end = text.find("*", index + 1)
            if end == -1:
                raise RenderError(line_number, line, "unclosed emphasis")
            inner = _inline(text[index + 1 : end], line_number, line)
            out.append(f"\\emph{{{inner}}}")
            index = end + 1
        elif char == '"':
            end = text.find('"', index + 1)
            if end == -1:
                raise RenderError(line_number, line, "unpaired double quote")
            inner = _inline(text[index + 1 : end], line_number, line)
            out.append(f"``{inner}''")
            index = end + 1
        elif text.startswith(("<http://", "<https://"), index):
            # markdownlint wraps bare URLs in angle brackets (MD034); the pair
            # is markdown autolink syntax and both brackets are consumed.
            end = text.find(">", index)
            if end == -1:
                raise RenderError(line_number, line, "unclosed autolink")
            out.append(f"\\url{{{text[index + 1 : end]}}}")
            index = end + 1
        elif text.startswith(("http://", "https://"), index):
            token = _URL.match(text, index)
            assert token is not None
            url = _trim_url(token.group(0))
            out.append(f"\\url{{{url}}}")
            index += len(url)
        elif char == "^":
            digits = _SUPERSCRIPT.match(text, index)
            if digits is None:
                out.append("\\textasciicircum{}")
                index += 1
            else:
                out.append(f"\\textsuperscript{{{digits.group(1)}}}")
                index = digits.end()
        else:
            out.append(_escape(char, line_number, line))
            index += 1
    return "".join(out)


def _wrap(text: str) -> str:
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if current and len(current) + 1 + len(word) > _WRAP:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    lines.append(current)
    return "\n".join(lines)


def _trim_url(token: str) -> str:
    """A URL as written: sentence punctuation and an unbalanced bracket are not
    part of it."""
    url = token.rstrip(_TRAILING_PUNCTUATION)
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def _check_constructs(line: str, line_number: int) -> None:
    stripped = line.strip()
    if "[^" in stripped:
        raise RenderError(line_number, line, "a footnote marker is not supported")
    if stripped.startswith("|"):
        raise RenderError(line_number, line, "a table is not supported")
    if stripped.startswith("!["):
        raise RenderError(line_number, line, "an image is not supported")
    if "](" in stripped:
        raise RenderError(line_number, line, "a markdown link is not supported")
    if re.match(r"^-{3,}\s*(\||$)", stripped):
        raise RenderError(
            line_number, line, "a table rule or horizontal rule is not supported"
        )


def _is_workflow_note(text: str) -> bool:
    return text.startswith("**A draft working paper") or text.startswith("**Status:**")


def _parse(markdown: str) -> tuple[str, list[_Section]]:
    """Split the markdown into the title and its sections, rendering as it goes."""
    title: str | None = None
    sections: list[_Section] = []
    current: _Section | None = None
    numbered_sections = 0
    paragraph: list[str] = []
    paragraph_line = 0
    items: list[str] = []
    list_kind: str | None = None
    next_number = 1
    code_lines: list[str] | None = None
    code_line_number = 0

    def emit_paragraph() -> None:
        nonlocal paragraph
        text = " ".join(part.strip() for part in paragraph).strip()
        paragraph = []
        if not text:
            return
        if current is None:
            # The title block's workflow notes are dropped there and nowhere
            # else; anything other than them up there would be lost silently,
            # so it stops the render instead.
            if not _is_workflow_note(text):
                raise RenderError(
                    paragraph_line, text, "content before the first section heading"
                )
            return
        current.blocks.append(_wrap(_inline(text, paragraph_line, text)))

    def emit_list() -> None:
        nonlocal items, list_kind, next_number
        if not items:
            return
        if current is None:
            raise RenderError(
                paragraph_line, items[0], "content before the first section heading"
            )
        if current.kind == "references":
            current.references.extend(items)
        else:
            env = "itemize" if list_kind == "itemize" else "enumerate"
            body = "\n".join(f"\\item {item}" for item in items)
            current.blocks.append(f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}")
        items = []
        list_kind = None
        next_number = 1

    def settle() -> None:
        emit_paragraph()
        emit_list()

    for number, raw in enumerate(markdown.splitlines(), start=1):
        line = raw.rstrip()
        if code_lines is not None:
            if line == "```":
                body = "\n".join(code_lines)
                if not body.isascii():
                    raise RenderError(number, line, "non-ASCII content in a code block")
                if "\\end{lstlisting}" in body:
                    raise RenderError(
                        number, line, "the end marker inside a code block"
                    )
                if current is None:
                    raise RenderError(
                        code_line_number,
                        "```",
                        "content before the first section heading",
                    )
                current.blocks.append(
                    f"\\begin{{lstlisting}}\n{body}\n\\end{{lstlisting}}"
                )
                code_lines = None
            else:
                code_lines.append(line)
            continue
        if not line.strip():
            # A blank line ends a paragraph but not a list: markdown's loose
            # lists put blank lines between items, and they are still one list.
            emit_paragraph()
            continue
        if line[:1] in (" ", "\t"):
            # Indented content means a nested list or a wrapped list item;
            # refusing beats reordering it silently.
            raise RenderError(number, line, "indented content is not supported")
        if line.startswith("# "):
            settle()
            if title is not None:
                raise RenderError(number, line, "a second top-level heading")
            _check_constructs(line[2:].strip(), number)
            title = _inline(line[2:].strip(), number, line)
            continue
        if line.startswith("## "):
            settle()
            heading = line[3:].strip()
            _check_constructs(heading, number)
            if heading == "Abstract":
                current = _Section("Abstract", "abstract")
            elif heading == "References":
                current = _Section("References", "references")
            elif heading.startswith("Appendix:"):
                remainder = heading[len("Appendix:") :].strip()
                remainder = remainder[:1].upper() + remainder[1:]
                current = _Section(remainder, "appendix")
            else:
                number_match = _SECTION_NUMBER.match(heading)
                if number_match is None:
                    raise RenderError(
                        number, line, "a section heading without its number"
                    )
                expected = numbered_sections + 1
                if int(number_match.group(1)) != expected:
                    raise RenderError(
                        number,
                        line,
                        f"section numbering jumps: expected {expected}. "
                        "(the prose's cross-references rely on it)",
                    )
                numbered_sections = expected
                name = heading[number_match.end() :]
                current = _Section(_inline(name, number, line), "section")
            sections.append(current)
            continue
        if line.startswith("```"):
            # A fenced block renders verbatim: no inline markup, no escaping,
            # no reflow - a transcript must read exactly as the tool printed it.
            if list_kind is not None:
                raise RenderError(number, line, "a fenced block inside a list")
            info = line[3:].strip()
            if info and not (info.isascii() and info.isalpha()):
                raise RenderError(number, line, "a fence takes at most an info word")
            emit_paragraph()
            code_lines = []
            code_line_number = number
            continue
        if line.startswith("- "):
            emit_paragraph()
            if list_kind == "enumerate":
                emit_list()
            if not items:
                paragraph_line = number
            list_kind = "itemize"
            item_text = line[2:].strip()
            _check_constructs(item_text, number)
            items.append(_inline(item_text, number, line))
            continue
        if _NUMBERED.match(line):
            emit_paragraph()
            value = int(line.split(".", 1)[0])
            if list_kind == "itemize":
                emit_list()
            if list_kind != "enumerate":
                if value != 1:
                    raise RenderError(number, line, "a numbered list must start at 1.")
                list_kind = "enumerate"
                next_number = 2
            else:
                if value != next_number:
                    raise RenderError(
                        number,
                        line,
                        "numbered items must run in sequence "
                        f"(expected {next_number}.)",
                    )
                next_number += 1
            if not items:
                paragraph_line = number
            item_text = _NUMBERED.sub("", line)
            _check_constructs(item_text, number)
            items.append(_inline(item_text, number, line))
            continue
        emit_list()
        _check_constructs(line, number)
        if not paragraph:
            paragraph_line = number
        paragraph.append(line)

    if code_lines is not None:
        raise RenderError(code_line_number, "```", "a fenced block is never closed")
    settle()
    if title is None:
        raise RenderError(0, "", "no top-level heading")
    return title, sections


def render_paper(markdown: str) -> str:
    """Render the paper's markdown as the submission's LaTeX source."""
    title, sections = _parse(markdown)
    preamble = "\n".join(
        [
            MARKER,
            "\\documentclass[11pt]{article}",
            "\\usepackage[margin=1in]{geometry}",
            "\\usepackage{microtype}",
            "\\usepackage{listings}",
            "\\lstset{basicstyle=\\ttfamily\\small,breaklines=true,"
            "columns=fullflexible,showstringspaces=false}",
            "\\usepackage[hidelinks]{hyperref}",
            # Reference URLs are long and have no spaces; without break points
            # they run into the margin (arXiv's format rules forbid it).
            "\\def\\UrlBreaks{\\do\\/\\do\\-\\do\\_\\do\\.\\do\\=\\do\\?\\do\\&\\do\\#}",
            "\\Urlmuskip=0mu plus 1mu",
            f"\\title{{{title}}}",
            f"\\author{{{AUTHOR}}}",
            f"\\date{{{DATE}}}",
        ]
    )
    parts = [preamble, "\\begin{document}\n\\maketitle"]
    for section in sections:
        blocks = "\n\n".join(section.blocks)
        if section.kind == "abstract":
            parts.append(f"\\begin{{abstract}}\n{blocks}\n\\end{{abstract}}")
        elif section.kind == "references":
            entries = "\n\n".join(
                f"\\noindent\\hangindent=1em\\hangafter=1\\relax {_wrap(entry)}"
                for entry in section.references
            )
            # Ragged right as bibliographies are: justified lines would fight
            # the unbreakable URLs.
            parts.append(
                "\\section*{References}\n\n{\\raggedright\\sloppy\n"
                + entries
                + "\n\\par}"
            )
        elif section.kind == "appendix":
            body = f"\n\n{blocks}" if blocks else ""
            parts.append(f"\\appendix\n\\section{{{section.name}}}{body}")
        else:
            body = f"\n\n{blocks}" if blocks else ""
            parts.append(f"\\section{{{section.name}}}{body}")
    parts.append("\\end{document}")
    return "\n\n".join(parts) + "\n"


def check(markdown: str, tex: str) -> list[str]:
    """Return the problems keeping the committed LaTeX out of step, if any."""
    if render_paper(markdown) == tex:
        return []
    return ["paper/main.tex is stale: run `uv run python scripts/render-paper.py`"]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parent.parent
    markdown = (root / "docs" / "paper.md").read_text(encoding="utf-8")
    tex_path = root / "paper" / "main.tex"
    if args == ["--check"]:
        problems = check(markdown, tex_path.read_text(encoding="utf-8"))
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    if args:
        print(f"usage: {Path(__file__).name} [--check]", file=sys.stderr)
        return 2
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(render_paper(markdown), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
