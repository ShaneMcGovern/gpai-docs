"""The v0.1 document root and the JSON Schema export source.

``schema_`` carries the format's ``schema`` key under an alias: a field named
``schema`` would shadow the deprecated ``BaseModel.schema`` classmethod. The
``systemic_risk`` marker is the format's assertion, absent meaning false.
"""

from typing import Literal

from pydantic import ConfigDict, Field

from gpai_docs.models.annex_xi import AnnexXI
from gpai_docs.models.annex_xii import AnnexXII
from gpai_docs.models.leaves import BooleanValue, Model
from gpai_docs.models.records import ModificationRecord, NotificationRecord


class ModelDocument(Model):
    """A v0.1 GPAI model documentation document (schema version 1)"""

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, title="ModelDocument"
    )

    schema_: Literal[1] = Field(alias="schema")
    systemic_risk: BooleanValue = False
    annex_xi: AnnexXI | None = None
    annex_xii: AnnexXII | None = None
    notifications: list[NotificationRecord] = Field(default_factory=list)
    modifications: list[ModificationRecord] = Field(default_factory=list)
