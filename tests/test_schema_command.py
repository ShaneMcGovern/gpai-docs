"""The ``schema`` command: the document JSON Schema the models project.

The source is ``ModelDocument.model_json_schema()``; the pins are a subset
of that dump (the root shape plus one def per section kind), covering the
projection's content on stdout, byte determinism and ``--out`` parity.
"""

import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from gpai_docs import cli

# The defs the format's shapes hang off: the Annex XI section element, the
# computational-resources object, and the Art. 52(1) notification record.
PINNED_DEFS = ("XI_IntendedTasks", "ComputationalResources", "NotificationRecord")


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["gpai-docs", *argv])
    return cli.main()


def _schema(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    """The parsed schema from a stdout run (exit 0, empty stderr)."""
    assert _run(monkeypatch, ["schema"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return cast("dict[str, Any]", json.loads(captured.out))


def test_schema_stdout_is_the_models_root_projection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The root is ModelDocument itself (pydantic puts it at the top, not in
    # $defs): the v0.1 marker is const 1 and the only required key.
    schema = _schema(monkeypatch, capsys)

    assert set(schema) == {
        "$defs",
        "additionalProperties",
        "description",
        "properties",
        "required",
        "title",
        "type",
    }
    assert schema["title"] == "ModelDocument"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["schema"]
    assert schema["properties"]["schema"] == {
        "const": 1,
        "title": "Schema",
        "type": "integer",
    }
    assert set(schema["properties"]) == {
        "schema",
        "systemic_risk",
        "annex_xi",
        "annex_xii",
        "notifications",
        "modifications",
    }
    # The optional systemic-risk marker: a real boolean, absent
    # meaning false, so the schema carries the default.
    assert schema["properties"]["systemic_risk"] == {
        "default": False,
        "title": "Systemic Risk",
        "type": "boolean",
    }
    assert schema["$defs"]


def test_schema_defs_pin_the_section_and_record_shapes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The two section objects plus one def per kind: an Annex XI element (a
    # string leaf titled with its registry id), the computational-resources
    # object, and the notification record.
    defs = _schema(monkeypatch, capsys)["$defs"]

    assert set(PINNED_DEFS) <= set(defs)
    assert defs["AnnexXI"]["additionalProperties"] is False
    assert defs["AnnexXII"]["additionalProperties"] is False
    assert defs["XI_IntendedTasks"] == {
        "description": "Tasks the model is intended to perform",
        "title": "XI.1.1.a",
        "type": "string",
    }
    resources = defs["ComputationalResources"]
    assert resources["title"] == "XI.1.2.d"
    assert resources["additionalProperties"] is False
    assert set(resources["properties"]) == {
        "training_flop",
        "estimation_method",
        "training_time",
    }
    record = defs["NotificationRecord"]
    assert record["additionalProperties"] is False
    assert set(record["properties"]) == {
        "compute_flop",
        "estimation_method",
        "aware_on",
        "notified_on",
    }
    assert record["properties"]["aware_on"]["anyOf"][0] == {
        "format": "date",
        "type": "string",
    }


def test_schema_prints_indented_json_with_one_trailing_newline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The output discipline: indent 2 and exactly one trailing newline, so a
    # byte diff of two dumps shows format drift.
    assert _run(monkeypatch, ["schema"]) == 0
    out = capsys.readouterr().out

    assert out == json.dumps(json.loads(out), indent=2) + "\n"


def test_schema_is_byte_identical_across_runs(
    monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    assert _run(monkeypatch, ["schema"]) == 0
    first = capsysbinary.readouterr().out
    assert _run(monkeypatch, ["schema"]) == 0
    second = capsysbinary.readouterr().out

    assert first == second
    assert first.startswith(b"{")


def test_schema_out_writes_the_stdout_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    tmp_path: Path,
) -> None:
    # --out moves the dump, it does not change it: the file carries the same
    # bytes the stdout run prints, and stdout stays empty.
    assert _run(monkeypatch, ["schema"]) == 0
    stdout_bytes = capsysbinary.readouterr().out
    path = tmp_path / "schema.json"

    assert _run(monkeypatch, ["schema", "--out", str(path)]) == 0
    captured = capsysbinary.readouterr()

    assert captured.out == b""
    assert captured.err == b""
    assert path.read_bytes() == stdout_bytes
