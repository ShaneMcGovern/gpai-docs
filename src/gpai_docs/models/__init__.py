"""The v0.1 document models: the validation single-source.

``ModelDocument`` is the document root; the element models live in
:mod:`gpai_docs.models.annex_xi` and :mod:`gpai_docs.models.annex_xii`.
Nothing imports the registry at runtime: the lockstep test binds the two.
"""

from gpai_docs.models.document import ModelDocument
from gpai_docs.models.leaves import (
    DateValue,
    NumberValue,
    TextListValue,
    TextValue,
    UrlValue,
)
from gpai_docs.models.records import ModificationRecord, NotificationRecord

__all__ = [
    "DateValue",
    "ModelDocument",
    "ModificationRecord",
    "NotificationRecord",
    "NumberValue",
    "TextListValue",
    "TextValue",
    "UrlValue",
]
