"""The ``lint`` vertical slice: a document in, cited findings out.

The first three passes live in :mod:`gpai_docs.lint.completeness`, the
consistency engine and its rule catalogue in :mod:`gpai_docs.lint.consistency`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gpai_docs.lint.completeness import lint as _first_three_passes
from gpai_docs.lint.consistency import RULES, Rule, RuleContext, run_consistency
from gpai_docs.lint.findings import FOOTER, Finding, FindingKind, render_finding

if TYPE_CHECKING:
    from gpai_docs.documents import Document
    from gpai_docs.registry import Registry

__all__ = [
    "FOOTER",
    "RULES",
    "Finding",
    "FindingKind",
    "Rule",
    "RuleContext",
    "lint",
    "render_finding",
    "run_consistency",
]


def lint(document: Document, registry: Registry) -> list[Finding]:
    """Check ``document``: typed, completeness, unknown, then consistency."""
    return [
        *_first_three_passes(document, registry),
        *run_consistency(document, registry),
    ]
