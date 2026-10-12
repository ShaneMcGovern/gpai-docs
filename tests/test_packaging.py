"""Pin the packaging metadata to the code it names."""

import importlib
import tomllib
from importlib import resources
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_distribution_name_is_gpai_docs() -> None:
    # The PyPI name and the repository name are the same.
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["name"] == "gpai-docs"


def test_the_console_script_imports_to_a_callable() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        scripts = tomllib.load(handle)["project"]["scripts"]
    (target,) = scripts.values()
    module_name, _, attribute = target.partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute))


def test_the_registry_sources_ship_as_package_data() -> None:
    # The loader reads sources.yaml through importlib.resources, so the wheel
    # must carry it as package data, not only the repository's src tree.
    assert resources.files("gpai_docs.registry").joinpath("sources.yaml").is_file()


def test_the_installed_metadata_exposes_that_script() -> None:
    # Reads the installed distribution, not pyproject.toml, so a broken install
    # (or a renamed package) fails here rather than only in a user's shell.
    scripts = {
        entry.name: entry.value
        for entry in distribution("gpai-docs").entry_points
        if entry.group == "console_scripts"
    }
    assert scripts == {"gpai-docs": "gpai_docs.cli:main"}
