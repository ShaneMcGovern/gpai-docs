"""Pydantic models for the registry data files.

Every shape the four YAML files may take is declared here and nowhere else.
Field names follow the registry's YAML keys, so ``schema`` is carried as
``schema_`` with the YAML name as its alias.
"""

import datetime
import re
from collections.abc import Iterable
from typing import Annotated, Literal, Self

import pydantic
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
)


class RegistryError(Exception):
    """A registry data file is missing, unreadable, or violates the schema."""


# The published id grammar: XI.1.<item>.<letter>, XI.2.<item>, XII.<item>.<letter>.
_FIELD_ID = re.compile(r"(?:XI\.1\.\d+\.[a-z]|XI\.2\.\d+|XII\.\d+\.[a-z])")
# A dated consolidated CELEX (0<year><act type><number>-YYYYMMDD), e.g. the
# AI Act's 02024R1689-20260727. Every shape-matching ``celex`` gets a watch
# resolver, so a match must carry a real calendar date (see ``Source``).
DATED_CELEX = re.compile(r"0\d{4}[A-Z]\d{4}-\d{8}")
_RULE_TAG = re.compile(
    r"completeness|type:(?:text|text-list|date|number|url|compute|energy)"
    r"|consistency:[a-z0-9][a-z0-9.-]*"
)
# The native document format keys its maps by these paths.
_MODEL_FIELD = re.compile(r"annex_(?:xi|xii)\.[a-z0-9_]+")


def _validate_field_id(value: str) -> str:
    if not _FIELD_ID.fullmatch(value):
        raise ValueError(f"not a field id: {value!r}")
    return value


def _validate_rule_tag(value: str) -> str:
    if not _RULE_TAG.fullmatch(value):
        raise ValueError(f"not a v0 rule tag: {value!r}")
    return value


def _validate_model_field(value: str) -> str:
    if not _MODEL_FIELD.fullmatch(value):
        raise ValueError(f"not a model field path: {value!r}")
    return value


FieldId = Annotated[str, AfterValidator(_validate_field_id)]
RuleTag = Annotated[str, AfterValidator(_validate_rule_tag)]
ModelFieldPath = Annotated[str, AfterValidator(_validate_model_field)]
Recipient = Literal["ai_office", "nca", "downstream"]


def _reject_duplicate_ids(ids: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(f"duplicate {what} id: {identifier!r}")
        seen.add(identifier)


class _Model(BaseModel):
    """Base for the four registry files: an unknown key is a defect."""

    model_config = ConfigDict(extra="forbid")


class _PackFile(_Model):
    """Base for the four files: format version and pack identity."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: int = pydantic.Field(alias="schema")
    pack: str


class ExtractionLocator(_Model):
    """Where a source's provision text lives in its fetched document.

    ``element`` and ``following_note`` each address one published element,
    ``chapeau`` an annex's introductory sentence, and ``article`` the enacted
    text; the field shapes each kind admits are ``_fields_match_the_kind``'s.
    """

    kind: Literal["element", "chapeau", "following_note", "article"]
    annex: Literal["XI", "XII"] | None = None
    section: int | None = None
    item: int | None = None
    letter: str | None = None
    article: int | None = None
    paragraph: int | None = None
    point: str | None = None

    @model_validator(mode="after")
    def _fields_match_the_kind(self) -> Self:
        if self.kind == "article":
            if self.article is None:
                raise ValueError("article extraction is missing article")
            if (
                self.annex is not None
                or self.section is not None
                or self.item is not None
                or self.letter is not None
            ):
                raise ValueError(
                    f"article extraction for Article {self.article} takes no "
                    "annex, section, item or letter"
                )
            if self.point is not None and self.paragraph is None:
                raise ValueError(
                    f"article extraction for Article {self.article} carries a "
                    "point without its paragraph"
                )
            return self
        if self.annex is None:
            raise ValueError(f"{self.kind} extraction is missing annex")
        if self.kind == "chapeau":
            if (
                self.section is not None
                or self.item is not None
                or self.letter is not None
                or self.article is not None
                or self.paragraph is not None
                or self.point is not None
            ):
                raise ValueError(
                    f"chapeau extraction in ANNEX {self.annex} takes no section, "
                    "item, letter or article fields"
                )
            return self
        # A bad section here is a registry defect at load, not a fetch-time
        # deferral.
        if self.section is not None and self.annex != "XI":
            raise ValueError(
                f"{self.kind} extraction in ANNEX {self.annex} takes no section: "
                "only ANNEX XI is divided into sections"
            )
        if self.kind == "element" and self.section == 2:
            if self.letter is not None:
                raise ValueError(
                    f"element extraction in ANNEX {self.annex} Section 2 takes "
                    "no letter"
                )
            missing = [] if self.item is not None else ["item"]
        else:
            missing = [
                name
                for name, value in (("item", self.item), ("letter", self.letter))
                if value is None
            ]
        if missing:
            raise ValueError(
                f"{self.kind} extraction in ANNEX {self.annex} is missing "
                f"{' and '.join(missing)}"
            )
        if self.article is not None or self.paragraph is not None or self.point:
            raise ValueError(
                f"{self.kind} extraction in ANNEX {self.annex} takes no article fields"
            )
        return self


class Source(_Model):
    """One text-bearing provision, keyed by its catalogue id."""

    id: str
    kind: Literal["regulation", "code_measure", "guidelines"]
    instrument: str
    celex: str | None = None
    location: str
    language: str
    url: str
    # The machine endpoint to fetch when the canonical ``url`` cannot be
    # (a challenge, a redirector); ``url`` stays the human-facing citation.
    fetch_url: str | None = None
    # Present only for verification: extract; the pipeline re-extracts with it.
    extraction: ExtractionLocator | None = None
    # Present only for verification: artifact - the hand-extracted file and
    # the hash of its downloaded bytes.
    artifact_url: str | None = None
    artifact_sha256: str | None = None
    retrieved: datetime.date
    verification: Literal["extract", "artifact"]
    text: str
    sha256: str

    @field_validator("celex")
    @classmethod
    def _dated_celex_carries_a_calendar_date(cls, value: str | None) -> str | None:
        """A shape-matching dated CELEX must parse as a calendar date."""
        if value is not None and DATED_CELEX.fullmatch(value):
            stamp = value[-8:]
            try:
                datetime.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
            except ValueError as error:
                raise ValueError(f"celex {value!r} carries no calendar date") from error
        return value

    @model_validator(mode="after")
    def _fields_match_the_mode(self) -> Self:
        if self.verification == "artifact":
            missing = []
            if self.artifact_url is None:
                missing.append("artifact_url")
            if self.artifact_sha256 is None:
                missing.append("artifact_sha256")
            if missing:
                raise ValueError(
                    f"artifact-verification source {self.id!r} is missing "
                    f"{' and '.join(missing)}"
                )
            if self.extraction is not None:
                raise ValueError(
                    f"artifact-verification source {self.id!r} must not carry "
                    "extraction"
                )
            return self
        if self.artifact_url is not None or self.artifact_sha256 is not None:
            raise ValueError(
                f"extract-verification source {self.id!r} must not carry "
                "artifact_url or artifact_sha256"
            )
        if self.extraction is None:
            raise ValueError(
                f"extract-verification source {self.id!r} is missing extraction"
            )
        return self


class FormMapping(_Model):
    """A field's place in the Model Documentation Form.

    The Form's rows are finer than the element granularity, so ``rows`` lists
    every row carrying the element's information and ``audience_flags`` the
    union of their crosses.
    """

    rows: list[str]
    audience_flags: list[str]
    note: str | None = None

    @model_validator(mode="after")
    def _rows_are_present(self) -> Self:
        if not self.rows and not (self.note or "").strip():
            raise ValueError("a form mapping carries no row")
        return self


class Field(_Model):
    """One published element of Annex XI Section 1 or Section 2, or Annex XII."""

    id: FieldId
    annex: Literal["XI", "XII"]
    section: int | None = None
    point: str
    label: str
    recipients: list[Recipient]
    form: FormMapping
    source: str
    context: list[str] = pydantic.Field(default_factory=list)
    guidance: str | None = None
    model_field: ModelFieldPath
    rules: list[RuleTag]
    # ``systemic_risk`` marks Annex XI Section 2's fields: completeness checks
    # them only when the document's marker asserts systemic risk.
    condition: Literal["systemic_risk"] | None = None


class FormRow(_Model):
    """One row of the Form inventory."""

    row: str
    label: str
    audience_flags: list[str]


class FormMeta(_Model):
    """The pinned Form artefact."""

    name: str
    source_url: str
    retrieved: datetime.date
    artifact_sha256: str


class FormFile(_PackFile):
    form: FormMeta
    rows: list[FormRow]


class CrosswalkTarget(_Model):
    """A connected instrument: mappings navigate, never assert."""

    id: str
    name: str
    version: str
    date: datetime.date
    url: str
    licence: str
    identifier_style: str
    status: Literal["active", "deferred", "optional"]
    provisional: bool


class MappingTarget(_Model):
    target: str
    ref: str
    note: str


class Mapping(_Model):
    field: FieldId
    targets: list[MappingTarget]


class TerminologyAlias(_Model):
    target: str
    term: str
    note: str


class TerminologyEntry(_Model):
    act_term: str
    aliases: list[TerminologyAlias]


class SourcesFile(_PackFile):
    sources: list[Source]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        _reject_duplicate_ids((source.id for source in self.sources), "source")
        return self


class FieldsFile(_PackFile):
    """`fields.yaml` alone carries the full pack manifest."""

    jurisdiction: str
    instrument: str
    covers: list[str]
    fields: list[Field]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        _reject_duplicate_ids((field.id for field in self.fields), "field")
        return self


class CrosswalkFile(_PackFile):
    targets: list[CrosswalkTarget]
    mappings: list[Mapping]
    terminology: list[TerminologyEntry]

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        known = {target.id for target in self.targets}
        for mapping in self.mappings:
            for target in mapping.targets:
                if target.target not in known:
                    raise ValueError(
                        f"mapping for {mapping.field!r} references unknown "
                        f"target {target.target!r}"
                    )
        for entry in self.terminology:
            for alias in entry.aliases:
                if alias.target not in known:
                    raise ValueError(
                        f"terminology entry {entry.act_term!r} references unknown "
                        f"target {alias.target!r}"
                    )
        return self
