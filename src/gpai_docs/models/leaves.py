"""The leaf value vocabulary of the v0.1 document models.

Five aliases implement the shapes the registry's ``type:`` tags name, and
``BooleanValue`` sits outside that table (no tag names a boolean) but refuses
coercion like its siblings; the lockstep test binds the two, not an import.
"""

import datetime
import math
import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict


class Model(BaseModel):
    """Base for every mapping model: an unknown key is a defect, not noise."""

    model_config = ConfigDict(extra="forbid")


def _validate_text(value: object) -> str:
    """Accept a string exactly; nothing is coerced into one."""
    if not isinstance(value, str):
        raise ValueError(f"not a string: {value!r}")
    return value


TextValue = Annotated[str, BeforeValidator(_validate_text)]


def _validate_text_list(value: list[str]) -> list[str]:
    """Every entry must be a non-empty string; the empty list is fine."""
    for index, entry in enumerate(value):
        if not entry:
            raise ValueError(f"empty text-list entry at index {index}")
    return value


TextListValue = Annotated[list[TextValue], AfterValidator(_validate_text_list)]


def _validate_number_shape(value: object) -> object:
    """Refuse bool, str and bytes ahead of pydantic's lax coercion.

    ``True`` would pass as the integer 1, ``"2.3"`` as 2.3 and YAML's
    ``!!binary`` bytes - b"23e25" - as 2.3e+26, but the compute rules need
    the difference to survive validation.
    """
    if isinstance(value, (bool, str, bytes, bytearray)):
        raise ValueError(f"not a number: {value!r}")
    return value


def _validate_number_value(value: int | float) -> int | float:
    """Refuse non-finite floats; a float round-trips exactly."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"not a finite number: {value!r}")
    return value


NumberValue = Annotated[
    int | float,
    BeforeValidator(_validate_number_shape),
    AfterValidator(_validate_number_value),
]


def _validate_boolean(value: object) -> bool:
    """Accept a real boolean only; ``"true"``, ``1`` and bytes are refused.

    The loader's YAML booleans arrive as real booleans, so anything else in
    the slot is malformed, not a boolean to coerce.
    """
    if not isinstance(value, bool):
        raise ValueError(f"not a boolean: {value!r}")
    return value


BooleanValue = Annotated[bool, BeforeValidator(_validate_boolean)]

_DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}")


def _validate_date(value: object) -> datetime.date:
    """Accept a date, or the exact ``YYYY-MM-DD`` string that parses.

    A ``datetime`` is refused before the ``date`` check can admit it:
    ``datetime`` subclasses ``date``, and truncating the time silently would
    report a date the author never wrote.
    """
    if isinstance(value, datetime.datetime):
        raise ValueError(f"a datetime is not a date: {value!r}")
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        if not _DATE_TEXT.fullmatch(value):
            raise ValueError(f"not a YYYY-MM-DD date: {value!r}")
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"not a calendar date: {value!r}") from error
    raise ValueError(f"not a date: {value!r}")


DateValue = Annotated[datetime.date, BeforeValidator(_validate_date)]


def _validate_url(value: str) -> str:
    """Accept http(s) URLs with a host; a bare path is not a URL."""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"not an http or https URL: {value!r}")
    if not parts.hostname:
        raise ValueError(f"URL has no host: {value!r}")
    return value


UrlValue = Annotated[TextValue, AfterValidator(_validate_url)]
