"""The public registry surface: ``load()`` and its models.

The reader is shared with the document loader and the number rules are the
YAML 1.2 core set; fetching and hashing live in the
verification pipeline, not here.
"""

import re
from collections.abc import Hashable
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from gpai_docs.registry.models import (
    CrosswalkFile,
    Field,
    FieldsFile,
    FormFile,
    RegistryError,
    Source,
    SourcesFile,
)

__all__ = [
    "FindingKind",
    "Registry",
    "RegistryError",
    "VerifyFinding",
    "VerifyReport",
    "exit_code",
    "load",
    "load_yaml_mapping",
    "verify",
]


@dataclass
class Registry:
    """The parsed registry: the four files plus the id-keyed lookups."""

    fields: list[Field]
    by_id: dict[str, Field]
    sources: dict[str, Source]
    form: FormFile
    crosswalk: CrosswalkFile


class _UniqueKeyLoader(yaml.SafeLoader):
    """A SafeLoader that refuses duplicate keys in one mapping.

    PyYAML keeps the last of a repeated key; in registry data that would
    silently change a stored text and its hash. Non-hashable keys are refused
    as constructor errors, the way stock PyYAML refuses them.
    """

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        self.flatten_mapping(node)
        mapping: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                )
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping

    def construct_yaml_int(self, node: yaml.ScalarNode) -> int:
        """Construct a YAML 1.2 core int (PyYAML's 1.1 reading is replaced below)."""
        text = self.construct_scalar(node)
        sign = -1 if text.startswith("-") else 1
        unsigned = text[1:] if text[:1] in "+-" else text
        if unsigned.startswith("0o"):
            return sign * int(unsigned[2:], 8)
        if unsigned.startswith("0x"):
            return sign * int(unsigned[2:], 16)
        return sign * int(unsigned)


# The YAML 1.2 core number spellings. PyYAML's 1.1
# resolvers (sexagesimal `12:30`, `1_000`, `017` as octal, unquoted
# timestamps) are replaced below; the bool lexemes stay 1.1 so a bool in a
# text slot still reaches the models as a bool.
_YAML12_INT = re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$")
_YAML12_FLOAT = re.compile(
    r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?)$"
)
_REPLACED_RESOLVERS = (
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:timestamp",
)


def _use_yaml12_numbers() -> None:
    """Install the 1.2 core resolvers on this subclass only (stock PyYAML keeps 1.1).

    Int registers before float: both match a plain decimal, and the document
    marker must stay the integer 1.
    """
    _UniqueKeyLoader.yaml_implicit_resolvers = {
        first: [
            (tag, pattern) for tag, pattern in entries if tag not in _REPLACED_RESOLVERS
        ]
        for first, entries in _UniqueKeyLoader.yaml_implicit_resolvers.items()
    }
    _UniqueKeyLoader.add_implicit_resolver(
        "tag:yaml.org,2002:int", _YAML12_INT, list("-+0123456789")
    )
    _UniqueKeyLoader.add_implicit_resolver(
        "tag:yaml.org,2002:float", _YAML12_FLOAT, list("-+0123456789.")
    )
    _UniqueKeyLoader.add_constructor(
        "tag:yaml.org,2002:int", _UniqueKeyLoader.construct_yaml_int
    )


_use_yaml12_numbers()


def _read_mapping(location: Traversable) -> dict[str, Any]:
    """Read one YAML mapping; every parse failure becomes ``RegistryError``.

    Nothing may escape as a traceback.
    """
    try:
        text = location.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RegistryError(f"cannot read {location}: {error}") from error
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, ValueError) as error:
        raise RegistryError(f"invalid YAML in {location}: {error}") from error
    except RecursionError:
        raise RegistryError(
            f"invalid YAML in {location}: too deeply nested to parse"
        ) from None
    if not isinstance(data, dict):
        raise RegistryError(f"{location} must contain a YAML mapping")
    return data


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load one YAML mapping; the document loader shares this reader."""
    return _read_mapping(path)


def _load_model[ModelT: BaseModel](
    directory: Traversable, name: str, model: type[ModelT]
) -> ModelT:
    location = directory.joinpath(name)
    try:
        return model.model_validate(_read_mapping(location))
    except ValidationError as error:
        raise RegistryError(f"{location}: {error}") from error


def load(path: Path | None = None) -> Registry:
    """Load the four data files from package data; ``path`` is the test seam."""
    directory: Traversable = (
        resources.files("gpai_docs.registry") if path is None else path
    )
    fields_file = _load_model(directory, "fields.yaml", FieldsFile)
    sources_file = _load_model(directory, "sources.yaml", SourcesFile)
    form_file = _load_model(directory, "form.yaml", FormFile)
    crosswalk_file = _load_model(directory, "crosswalk.yaml", CrosswalkFile)
    return Registry(
        fields=fields_file.fields,
        by_id={field.id: field for field in fields_file.fields},
        sources={source.id: source for source in sources_file.sources},
        form=form_file,
        crosswalk=crosswalk_file,
    )


# Last: verify imports this module, so these names cannot bind earlier.
from gpai_docs.registry.verify import (  # noqa: E402
    FindingKind,
    VerifyFinding,
    VerifyReport,
    exit_code,
    verify,
)
