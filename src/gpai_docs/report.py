"""The Markdown findings report.

One ``###`` section per finding, rendered purely from the findings and the
registry. A blank line before ``**Basis:**`` is load-bearing: a bare line
after a blockquote would be absorbed into it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from gpai_docs.lint.findings import FOOTER, Finding, _headline

if TYPE_CHECKING:
    from gpai_docs.registry import Registry

__all__ = ["findings_markdown"]


def findings_markdown(findings: list[Finding], registry: Registry) -> str:
    """Render a lint run as a Markdown document, closer included.

    A run with no findings renders the closer alone, and the string carries
    no trailing newline: the caller prints it.
    """
    blocks = [_finding_markdown(finding, registry) for finding in findings]
    blocks.append(_closer(findings))
    return "\n\n".join(blocks)


def _finding_markdown(finding: Finding, registry: Registry) -> str:
    """One finding's section: headline, message, citation, bases.

    The headline and wording mirror the text renderer's element form; its
    review aids (key path, annex point, Form inventory, guidance) are dropped,
    leaving the located citations a report stands on.
    """
    field = None if finding.field_id is None else registry.by_id.get(finding.field_id)
    lines = [f"### {_one_line(_headline(finding, field))}"]
    # The one headline form that embeds the message is the field-less unknown
    # key (see _headline); the predicate is structural so a label ending in
    # the message's words cannot swallow the prose line.
    names_itself_by_message = (
        field is None and finding.label is None and finding.kind == "unknown"
    )
    if finding.message is not None and not names_itself_by_message:
        lines.append(finding.message)
    if field is not None:
        source = registry.sources[field.source]
        lines.append(f"> {source.location}")
        lines.append(f'> "{source.text}"')
    if finding.citations or finding.basis_forms:
        lines.append("")
        lines.append("**Basis:**")
        for source_id in finding.citations:
            cited = registry.sources.get(source_id)
            if cited is None:
                raise KeyError(
                    f"unknown source id {source_id!r} cited by the "
                    f"{finding.kind} finding at {finding.location!r}"
                )
            lines.append(f"> {cited.location}")
            lines.append(f'> "{cited.text}"')
        for row, label in finding.basis_forms:
            lines.append(f"- Form: {row} - {label}")
    return "\n".join(lines)


def _one_line(text: str) -> str:
    """Collapse a headline's line breaks to a single space.

    The unknown-key headline embeds author-controlled document text, and a
    line break would split the ``###`` heading and let it inject Markdown
    structure of its own; the key's text is otherwise untouched.
    """
    return re.sub(r"[\r\n]+", " ", text)


def _closer(findings: list[Finding]) -> str:
    """The run's closing line: the count wording and footer, italicised."""
    summary = "no findings" if not findings else f"{len(findings)} findings"
    return f"*{summary} - {FOOTER}*"
