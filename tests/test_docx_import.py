"""The Form package reader, row walker and import mapping.

Pins the faithful structural walk (label carry-forward, response and
description cells, ``w14:checked`` state over glyphs) and the mapping layer
that pairs walked rows with ``form.yaml``; the synthetic packages come from
``tests/fixtures/form_docx.py``.
"""

import struct
import sys
import zipfile
from pathlib import Path

import pytest

# tests/fixtures holds the builder as a plain module (no package __init__);
# put its directory on the path so the import below resolves under pytest's
# importlib mode and under mypy alike.
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from form_docx import RESPONSE_ALIAS, Row, write_form_docx, write_package

from gpai_docs.docxform import (
    _ROW_LEAVES,
    _SECTION_BY_HEADING,
    CellAnswer,
    DocxError,
    FormRow,
    MappedSummary,
    _number_literal,
    build_document,
    count_duplicate_rows,
    form_rows_for,
    locate_rows,
    read_rows,
    summarise,
)
from gpai_docs.registry import Registry, load

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
_ALL = {"ai_office": True, "nca": True, "downstream": True}


def _ticked(rows: list[FormRow], label: str) -> FormRow:
    """The first walked row carrying this label (a readable assertion aid)."""
    matches = [row for row in rows if row.label == label]
    assert matches, f"no walked row labelled {label!r}: {[row.label for row in rows]}"
    return matches[0]


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


def _imported(
    tmp_path: Path, rows: list[Row], registry: Registry
) -> tuple[dict[str, str], dict[str, object]]:
    """Walk, locate and build one synthetic form (the importer's own path)."""
    package = write_form_docx(tmp_path / "form.docx", rows)
    located = locate_rows(read_rows(package), registry)
    return located, build_document(located, registry)


def _rewrite_headers(
    path: Path, name: str, *, method: int | None = None, flags: int | None = None
) -> None:
    """Patch one member's headers into the unsupported/encrypted shapes."""
    data = bytearray(path.read_bytes())

    def find(signature: bytes, name_length: int, name_offset: int) -> int:
        start = data.find(signature)
        while start >= 0:
            length = struct.unpack_from("<H", data, start + name_length)[0]
            if bytes(data[start + name_offset : start + name_offset + length]) == (
                name.encode()
            ):
                return start
            start = data.find(signature, start + 1)
        raise AssertionError(f"no member {name!r}")

    local = find(b"PK\x03\x04", 26, 30)
    central = find(b"PK\x01\x02", 28, 46)
    for offset, value in ((local + 6, flags), (central + 8, flags)):
        if value is not None:
            current = struct.unpack_from("<H", data, offset)[0]
            struct.pack_into("<H", data, offset, current | value)
    for offset, value in ((local + 8, method), (central + 10, method)):
        if value is not None:
            struct.pack_into("<H", data, offset, value)
    path.write_bytes(bytes(data))


def test_wrapped_and_plain_rows_and_cells_are_found(tmp_path: Path) -> None:
    # The row-wrapping sdt and the cell-wrapping sdts must unwrap before the
    # walk: a direct-children walk loses both (structure note),
    # and the same package carries the plain shapes, so either fails here.
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(heading="General information"),
            Row(
                label="Wrapped row",
                response="A wrapped response",
                crosses=_ALL,
                wrap_row=True,
                wrap_cells=True,
            ),
            Row(
                label="Plain row",
                response="A plain response",
                crosses={"ai_office": True},
                wrap_row=False,
                wrap_cells=False,
            ),
        ],
    )

    rows = read_rows(package)

    assert [row.label for row in rows] == ["Wrapped row", "Plain row"]
    assert rows[0].response == "A wrapped response"
    assert rows[1].response == "A plain response"
    assert rows[0].crosses == _ALL
    assert rows[1].crosses == {"ai_office": True}


def test_labels_and_responses_join_across_runs_and_paragraphs(
    tmp_path: Path,
) -> None:
    # Runs are fragments: within a paragraph they join with nothing, and
    # paragraphs join with a space, then whitespace normalises; the real
    # form splits "Legal name for" / "the model provider" exactly this way.
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(
                label_runs=["Legal", " name for", " the model"],
                response_runs=["Acme ", "Models", " Ltd"],
            ),
            Row(
                label_paragraphs=["Legal name for", "the model provider:"],
                response="second response",
            ),
        ],
    )

    rows = read_rows(package)

    assert rows[0].label == "Legal name for the model"
    assert rows[0].response == "Acme Models Ltd"
    assert rows[1].label == "Legal name for the model provider:"
    assert rows[1].response == "second response"


def test_crosses_read_w14_checked_not_glyphs(tmp_path: Path) -> None:
    # The audience columns are the row's last three cells; a column the row
    # does not carry has no key, and an unticked control with no rendered
    # character still reads False from its w14:checked state.
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(
                label="All ticked",
                response="first",
                crosses=_ALL,
            ),
            Row(
                label="Silent downstream",
                response="second",
                crosses={"ai_office": True, "nca": False, "downstream": False},
                silent=("downstream",),
            ),
            Row(label="One column", response="third", crosses={"nca": True}),
        ],
    )

    rows = read_rows(package)

    assert rows[0].crosses == _ALL
    assert rows[1].crosses == {
        "ai_office": True,
        "nca": False,
        "downstream": False,
    }
    assert rows[2].crosses == {"nca": True}


def test_a_continuation_row_carries_its_label_forward(tmp_path: Path) -> None:
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(label="License:", response="first response", crosses=_ALL),
            Row(label="", response="continuation response", crosses={"nca": True}),
        ],
    )

    rows = read_rows(package)

    assert [row.label for row in rows] == ["License:", "License:"]
    assert rows[1].response == "continuation response"
    assert rows[1].crosses == {"nca": True}


def test_a_debris_row_is_dropped(tmp_path: Path) -> None:
    # A structurally normal row with empty label and description/response
    # cells is debris, however many crosses it carries (structure note,
    # "Rows and debris to drop").
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(label="Model architecture:", response="a response", crosses=_ALL),
            Row(crosses=_ALL),
            Row(label="Design specifications:", response="another", crosses=_ALL),
        ],
    )

    rows = read_rows(package)

    assert [row.label for row in rows] == [
        "Model architecture:",
        "Design specifications:",
    ]


def test_section_headings_track_and_are_not_rows(tmp_path: Path) -> None:
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(heading="General information"),
            Row(label="Legal name", response="one"),
            Row(heading="Model properties"),
            Row(label="Model architecture", response="two"),
        ],
    )

    rows = read_rows(package)

    assert [row.section for row in rows] == [
        "General information",
        "Model properties",
    ]
    assert [row.label for row in rows] == ["Legal name", "Model architecture"]


def test_the_description_is_the_static_text_beside_the_response(
    tmp_path: Path,
) -> None:
    # The option tick controls' glyphs are never read as text (the state is
    # structured); their printed labels and the static description are, and
    # the response comes from the response field alone.
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(
                label="Input modalities:",
                options=[(True, "Text"), (False, "Images")],
                description="Maximum size:",
                response="1024 tokens",
                crosses=_ALL,
            )
        ],
    )

    row = _ticked(read_rows(package), "Input modalities:")

    assert row.description == "Text Images Maximum size:"
    assert row.response == "1024 tokens"
    assert "☒" not in row.description + row.response
    assert "☐" not in row.description + row.response


def test_a_nested_table_is_walked_as_its_own_rows(tmp_path: Path) -> None:
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(
                label="Data provenance:",
                response="outer response",
                nested=[Row(label="Publicly available datasets", response="inner")],
                crosses=_ALL,
            )
        ],
    )

    rows = read_rows(package)

    assert [row.label for row in rows] == [
        "Data provenance:",
        "Publicly available datasets",
    ]
    assert rows[0].response == "outer response"
    assert rows[1].response == "inner"


def test_a_one_cell_row_walks_without_an_answer_area_or_audience(
    tmp_path: Path,
) -> None:
    # A one-cell row has no answer area and no audience columns; it walks
    # (faithfully) even though no published row looks like this.
    package = write_package(
        tmp_path / "form.docx",
        (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}"><w:body><w:tbl>'
            "<w:tr><w:tc><w:p><w:r><w:t>Survivor</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl></w:body></w:document>"
        ),
    )

    assert read_rows(package) == [
        FormRow(section="", label="Survivor", response="", description="")
    ]


def test_a_row_without_cells_and_controls_without_props_or_content_survive(
    tmp_path: Path,
) -> None:
    # Malformed tolerance: an empty w:tr is skipped, a control without an
    # sdtPr contributes no role, and a control without an sdtContent
    # contributes nothing at all.
    package = write_package(
        tmp_path / "form.docx",
        (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}"><w:body><w:tbl>'
            "<w:tr/>"
            "<w:tr><w:tc>"
            "<w:sdt><w:sdtContent><w:p><w:r><w:t>Bare control label</w:t>"
            "</w:r></w:p></w:sdtContent></w:sdt>"
            "</w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>Label with void control</w:t></w:r></w:p>"
            "<w:sdt><w:sdtPr/></w:sdt></w:tc></w:tr>"
            "</w:tbl></w:body></w:document>"
        ),
    )

    rows = read_rows(package)

    assert [row.label for row in rows] == [
        "Bare control label",
        "Label with void control",
    ]


def test_read_rows_reports_a_file_that_is_not_a_package(tmp_path: Path) -> None:
    path = tmp_path / "form.docx"
    path.write_text("this is not a zip file", encoding="utf-8")

    with pytest.raises(DocxError) as excinfo:
        read_rows(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "not a zip file" in message


def test_read_rows_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DocxError, match="cannot read"):
        read_rows(tmp_path / "absent.docx")


def test_read_rows_requires_word_document_xml(tmp_path: Path) -> None:
    path = tmp_path / "form.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")

    with pytest.raises(DocxError) as excinfo:
        read_rows(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "word/document.xml" in message


def test_read_rows_reports_a_malformed_document_part(tmp_path: Path) -> None:
    path = write_package(tmp_path / "form.docx", "<w:document")

    with pytest.raises(DocxError, match=r"invalid word/document\.xml"):
        read_rows(path)


def test_a_glyph_less_ticked_control_reads_true(tmp_path: Path) -> None:
    # The state is structured, so a ticked control renders nothing and still
    # reads True: a glyph-coupled reader would fail here.
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(
                label="Silent ticked downstream",
                response="an answer",
                crosses={"ai_office": True, "nca": False, "downstream": True},
                silent=("downstream",),
            )
        ],
    )

    row = read_rows(package)[0]

    assert row.crosses == {"ai_office": True, "nca": False, "downstream": True}
    assert "☒" not in row.description + row.response


def test_a_tick_wrapped_cell_contributes_no_text(tmp_path: Path) -> None:
    # A tick-wrapped cell's glyph and text are the control's rendering, not
    # cell text: in a short row they must not leak into the description.
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:w14="{W14}"><w:body><w:tbl><w:tr>'
        "<w:tc><w:p><w:r><w:t>Short row</w:t></w:r></w:p></w:tc>"
        "<w:sdt><w:sdtPr><w14:checkbox>"
        '<w14:checked w14:val="1"/></w14:checkbox></w:sdtPr>'
        "<w:sdtContent><w:tc><w:p><w:r><w:t>☒Tick</w:t></w:r></w:p></w:tc>"
        "</w:sdtContent></w:sdt>"
        "</w:tr></w:tbl></w:body></w:document>"
    )

    row = read_rows(write_package(tmp_path / "form.docx", text))[0]

    assert row.label == "Short row"
    assert row.description == ""
    assert row.response == ""
    assert "☒" not in row.description + row.response


def test_a_tick_control_wrapping_a_plain_control_reads_its_own_state(
    tmp_path: Path,
) -> None:
    # A tick sdt wrapping a nested plain sdt must read the tick's own state,
    # not evaluate the inner control.
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:w14="{W14}"><w:body><w:tbl><w:tr>'
        "<w:tc><w:p><w:r><w:t>Nested tick</w:t></w:r></w:p></w:tc>"
        "<w:sdt><w:sdtPr><w14:checkbox>"
        '<w14:checked w14:val="1"/></w14:checkbox></w:sdtPr><w:sdtContent>'
        "<w:sdt><w:sdtPr/><w:sdtContent><w:tc><w:p><w:r><w:t>☒</w:t></w:r>"
        "</w:p></w:tc></w:sdtContent></w:sdt>"
        "</w:sdtContent></w:sdt>"
        "<w:tc/><w:tc/>"
        "</w:tr></w:tbl></w:body></w:document>"
    )

    row = read_rows(write_package(tmp_path / "form.docx", text))[0]

    assert row.crosses == {"ai_office": True}


def test_a_multi_paragraph_response_joins_with_spaces(tmp_path: Path) -> None:
    package = write_form_docx(
        tmp_path / "form.docx",
        [
            Row(
                label="Model architecture:",
                response_paragraphs=["first paragraph", "second paragraph"],
                crosses=_ALL,
            )
        ],
    )

    row = read_rows(package)[0]

    assert row.response == "first paragraph second paragraph"
    assert row.answers[0].outer == "first paragraph second paragraph"


def _inline_control_package(path: Path, run_xml: str) -> Path:
    """A one-row package whose response area holds an inline control's run.

    ``run_xml`` is the run's content: the ``w:t`` fragments and soft breaks
    the reader joins, in the run-level control shape the Form's five
    soft-break answer rows carry (an ``w:sdt`` inside a paragraph).
    """
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body><w:tbl>'
        '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r>'
        "<w:t>Use</w:t></w:r></w:p></w:tc><w:tc/></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>Acceptable Use Policy</w:t></w:r></w:p></w:tc>"
        '<w:tc><w:p><w:sdt><w:sdtPr><w:alias w:val="an answer"/>'
        f"</w:sdtPr><w:sdtContent><w:r>{run_xml}</w:r></w:sdtContent>"
        "</w:sdt></w:p></w:tc></w:tr></w:tbl></w:body></w:document>"
    )
    return write_package(path, text)


@pytest.mark.parametrize("break_tag", ["w:br", "w:cr"])
def test_a_soft_break_inside_a_response_run_reads_as_a_newline(
    tmp_path: Path, break_tag: str
) -> None:
    # The form's own join: a w:br or w:cr inside a run contributes
    # "\n" beside the w:t fragments, so Word's soft break keeps the line
    # structure it means, and runs still join with nothing around the break.
    package = _inline_control_package(
        tmp_path / "form.docx",
        f"<w:t>line one</w:t><{break_tag}/><w:t>line two</w:t>",
    )

    row = read_rows(package)[0]

    assert row.answers[0].inner == "line one\nline two"


def test_a_blank_soft_break_line_collapses_to_one_newline(tmp_path: Path) -> None:
    # Two breaks in a row are a blank line; the normalisation drops the
    # empty line, so a written value's blank line settles to the single
    # newline the round-trip claim's caveat documents.
    package = _inline_control_package(
        tmp_path / "form.docx",
        "<w:t>a</w:t><w:br/><w:br/><w:t>b</w:t>",
    )

    row = read_rows(package)[0]

    assert row.answers[0].inner == "a\nb"


def test_a_control_in_a_label_cell_leaves_an_empty_row_a_fragment(
    tmp_path: Path,
) -> None:
    # The glyph-less fragment: a row whose only content is an unticked
    # control in the label cell, rendering nothing, drops with no label,
    # description or response (structure note, "Rows and debris to drop").
    package = write_form_docx(
        tmp_path / "form.docx",
        [Row(label="", label_tick=False)],
    )

    assert read_rows(package) == []


def test_read_rows_reports_an_unsupported_compression_method(
    tmp_path: Path,
) -> None:
    path = write_form_docx(tmp_path / "form.docx", [Row(label="Legal name")])
    _rewrite_headers(path, "word/document.xml", method=99)

    with pytest.raises(DocxError) as excinfo:
        read_rows(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "compression" in message


def test_read_rows_reports_an_encrypted_package(tmp_path: Path) -> None:
    path = write_form_docx(tmp_path / "form.docx", [Row(label="Legal name")])
    _rewrite_headers(path, "word/document.xml", flags=1)

    with pytest.raises(DocxError) as excinfo:
        read_rows(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "encrypted" in message


def test_the_heading_map_covers_the_artifacts_headings(registry: Registry) -> None:
    # The map is keyed by the artifact's raw headings (the four unsluggable
    # ones included) and its values are exactly the section parts form.yaml
    # uses, which `slug(heading)` alone cannot derive.
    assert set(_SECTION_BY_HEADING) == {
        "General information",
        "Model properties",
        "Methods of distribution and licenses",
        "Use",
        "Training process",
        "Information on the data used for training, testing, and validation",
        "Computational resources (during training)",
        "Energy consumption (during training and inference)",
    }
    assert set(_SECTION_BY_HEADING.values()) == {
        spec.row.partition("/")[0] for spec in registry.form.rows
    }


def test_form_rows_for_returns_the_published_rows_for_a_label(
    registry: Registry,
) -> None:
    assert [spec.row for spec in form_rows_for("Distribution channels", registry)] == [
        "distribution-and-licenses/distribution-channels",
        "distribution-and-licenses/distribution-channels-downstream-providers",
    ]
    assert form_rows_for("No such published label", registry) == []


def test_a_field_concatenates_its_rows_in_order(
    tmp_path: Path, registry: Registry
) -> None:
    # XI.1.1.a draws on two Form rows; the value is their responses in the
    # field's own row order, joined by a blank line.
    rows = [
        Row(heading="Use"),
        Row(label="Intended uses:", response="the tasks", crosses=_ALL),
        Row(
            label=(
                "Type and nature of AI systems in which the general-purpose AI "
                "model can be integrated:"
            ),
            response="the systems",
            crosses=_ALL,
        ),
    ]

    _, document = _imported(tmp_path, rows, registry)

    assert document == {
        "schema": 1,
        "annex_xi": {"intended_tasks": "the tasks\n\nthe systems"},
        "annex_xii": {"intended_tasks": "the tasks\n\nthe systems"},
    }


def test_a_numeric_literal_becomes_a_number_for_an_amount_leaf(
    tmp_path: Path, registry: Registry
) -> None:
    rows = [
        Row(heading="Computational resources (during training)"),
        Row(
            label="Amount of computation used for training:",
            response="2.3e+25",
            crosses={"nca": True},
        ),
    ]

    _, document = _imported(tmp_path, rows, registry)

    assert document == {
        "schema": 1,
        "annex_xi": {"computational_resources": {"training_flop": 2.3e25}},
    }


def test_a_non_literal_amount_stays_a_verbatim_string(
    tmp_path: Path, registry: Registry
) -> None:
    # No free-text parsing and no unit stripping: anything that is not
    # exactly a numeric literal is written as the string it is, for lint to
    # flag.
    rows = [
        Row(heading="Computational resources (during training)"),
        Row(
            label="Amount of computation used for training:",
            response="approx. 2.3e+25",
            crosses={"nca": True},
        ),
    ]

    _, document = _imported(tmp_path, rows, registry)

    assert document == {
        "schema": 1,
        "annex_xi": {"computational_resources": {"training_flop": "approx. 2.3e+25"}},
    }


def test_time_and_method_rows_write_to_their_text_leaves(
    tmp_path: Path, registry: Registry
) -> None:
    rows = [
        Row(heading="Computational resources (during training)"),
        Row(label="Training time:", response="9 days", crosses={"nca": True}),
        Row(
            label="Measurement methodology:",
            response="hardware counters",
            crosses={"ai_office": True, "nca": True},
        ),
    ]

    _, document = _imported(tmp_path, rows, registry)

    assert document == {
        "schema": 1,
        "annex_xi": {
            "computational_resources": {
                "training_time": "9 days",
                "estimation_method": "hardware counters",
            }
        },
    }


def test_energy_amount_and_method_land_on_their_leaves(
    tmp_path: Path, registry: Registry
) -> None:
    rows = [
        Row(heading="Energy consumption (during training and inference)"),
        Row(
            label="Amount of energy used for training:",
            response="1200",
            crosses={"ai_office": True, "nca": True},
        ),
        Row(
            label="Measurement methodology:",
            response="metered at the wall",
            crosses={"ai_office": True, "nca": True},
        ),
    ]

    _, document = _imported(tmp_path, rows, registry)

    assert document == {
        "schema": 1,
        "annex_xi": {
            "energy_consumption": {
                "training": {"amount": 1200, "method": "metered at the wall"}
            }
        },
    }


def test_the_numeric_reading_is_the_registry_readers_yaml_12_grammar() -> None:
    # The document's number grammar is the YAML 1.2 core set the registry
    # reader constructs (registry/__init__.py); this module's reading must
    # accept exactly the same spellings.
    from gpai_docs.registry import _YAML12_FLOAT, _YAML12_INT

    for spelling in (
        "2.3e+25",
        "9e+24",
        "1.0",
        ".5",
        "-3",
        "017",
        "0o17",
        "0x1F",
        "1_000",
        "12:30",
        "approx. 2.3e+25",
    ):
        from_number = _number_literal(spelling)
        is_number = (
            _YAML12_INT.fullmatch(spelling) is not None
            or _YAML12_FLOAT.fullmatch(spelling) is not None
        )
        assert (from_number is not None) == is_number, spelling
    assert _number_literal("2.3e+25") == 2.3e25
    assert _number_literal("9e+24") == 9.0e24
    assert _number_literal("-3") == -3
    assert _number_literal("017") == 17
    assert _number_literal("0o17") == 15
    assert _number_literal("0x1F") == 31
    assert _number_literal(".5") == 0.5
    # A literal with no finite double is not a number this format can write.
    assert _number_literal("1e400") is None
    assert _number_literal("approx. 2.3e+25") is None


def test_a_row_matching_nothing_is_silent(tmp_path: Path, registry: Registry) -> None:
    rows = [
        Row(heading="Use"),
        Row(label="Not a published row:", response="orphan", crosses=_ALL),
    ]

    located, document = _imported(tmp_path, rows, registry)

    assert located == {}
    assert document == {"schema": 1}
    assert summarise(located, registry) == MappedSummary(
        rows_mapped=0, fields_written=0, rows_skipped=0
    )


def test_same_label_rows_take_their_crosses(tmp_path: Path, registry: Registry) -> None:
    # Two "Distribution channels" rows are told apart by their crosses
    # against the recorded audience_flags.
    rows = [
        Row(heading="Methods of distribution and licenses"),
        Row(
            label="Distribution channels:",
            response="through the API",
            crosses={"ai_office": True, "nca": True},
        ),
        Row(
            label="Distribution channels:",
            response="through downstream providers",
            crosses={"downstream": True},
        ),
    ]

    located, _ = _imported(tmp_path, rows, registry)

    assert located == {
        "distribution-and-licenses/distribution-channels": "through the API",
        "distribution-and-licenses/distribution-channels-downstream-providers": (
            "through downstream providers"
        ),
    }


def test_twin_rows_pair_in_document_order(tmp_path: Path, registry: Registry) -> None:
    # The two Energy "Measurement methodology" rows carry the same section,
    # label and crosses: each form.yaml row takes the next unconsumed walked
    # match, so the training row's answer must not land on the inference row.
    rows = [
        Row(heading="Energy consumption (during training and inference)"),
        Row(
            label="Measurement methodology:",
            response="training methodology",
            crosses={"ai_office": True, "nca": True},
        ),
        Row(
            label="Measurement methodology:",
            response="inference methodology",
            crosses={"ai_office": True, "nca": True},
        ),
    ]

    walked = read_rows(write_form_docx(tmp_path / "form.docx", rows))
    located = locate_rows(walked, registry)

    assert located == {
        "energy-consumption/measurement-methodology-energy": "training methodology",
        "energy-consumption/measurement-methodology-inference": (
            "inference methodology"
        ),
    }


def test_the_split_row_maps_its_own_and_its_inner_answers(
    tmp_path: Path, registry: Registry
) -> None:
    # The output-modalities DOCX row covers two published rows. Its second
    # tick pair (downstream) belongs to the maximum-size row, the per-modality
    # cells carry that row's answers, and the cell-wrapped field after them is
    # the modalities row's own answer (structure note).
    rows = [
        Row(heading="Model properties"),
        Row(
            label_paragraphs=[
                "Output modalities:",
                "For each selected modality please include maximum output size "
                "or write 'N/A' if not defined",
            ],
            split_responses=["1024 tokens", "2048 tokens", "N/A", "512 tokens"],
            response="the other output modalities",
            crosses=_ALL,
            extra_crosses={"ai_office": False, "nca": False, "downstream": True},
        ),
    ]

    walked = read_rows(write_form_docx(tmp_path / "form.docx", rows))
    located = locate_rows(walked, registry)

    assert walked[0].crosses == _ALL
    assert walked[0].cross_pairs == (
        _ALL,
        {"ai_office": False, "nca": False, "downstream": True},
    )
    assert located == {
        "model-properties/output-modalities": "the other output modalities",
        "model-properties/output-modalities-maximum-size": (
            "1024 tokens 2048 tokens N/A 512 tokens"
        ),
    }


def test_the_range_row_reads_the_crosses_that_sit_in_its_options_row(
    tmp_path: Path, registry: Registry
) -> None:
    # The parameter-range row's label sits in one DOCX row and its crosses in
    # the row holding the range options: the inventoried row matches the
    # options row, and the label rows are silent.
    rows = [
        Row(heading="Model properties"),
        Row(label="The range within which the total number of parameters falls"),
        Row(
            label="",
            description="1-500M 500M-5B",
            crosses={"ai_office": False, "nca": True, "downstream": True},
        ),
    ]

    located, _ = _imported(tmp_path, rows, registry)

    assert located == {"model-properties/total-model-size-parameter-range": ""}


def test_a_continuation_row_carries_its_answer_to_its_own_row(
    tmp_path: Path, registry: Registry
) -> None:
    # A continuation row holds no label; carrying it forward lets its answer
    # locate, and its crosses pick which of the repeated "License" rows it is.
    rows = [
        Row(heading="Methods of distribution and licenses"),
        Row(
            label="License:",
            response="a link to the licence",
            crosses={"ai_office": True, "nca": True},
        ),
        Row(
            label="",
            response="the licence category",
            crosses={"downstream": True},
        ),
    ]

    located, _ = _imported(tmp_path, rows, registry)

    assert located == {
        "distribution-and-licenses/license": "a link to the licence",
        "distribution-and-licenses/license-type-or-category": "the licence category",
    }


def test_guidance_rows_read_absent_on_a_blank_fixture(
    tmp_path: Path, registry: Registry
) -> None:
    # The pinned form's response fields carry guidance text in the same
    # shapes the artifact uses: a grey guidance character style, explicit
    # grey runs, a grey control-level colour, the alias itself as the text,
    # and the showingPlcHdr flag. All of it reads absent, so a blank import
    # is the skeleton document.
    rows = [
        Row(heading="Model properties"),
        Row(
            label="Model architecture:",
            response="A general description of the model architecture.",
            crosses=_ALL,
            response_style="Style2",
        ),
        Row(
            label="Total model size:",
            response="The total number of parameters of the model.",
            crosses={"ai_office": True},
            response_color="808080",
        ),
        Row(heading="Use"),
        Row(label="Intended uses:", response=RESPONSE_ALIAS, crosses=_ALL),
        Row(
            label="Acceptable Use Policy:",
            response="Click here to add text.",
            crosses=_ALL,
            response_plchdr=True,
        ),
        Row(
            label=(
                "Type and nature of AI systems in which the general-purpose AI "
                "model can be integrated:"
            ),
            response="Grey through the control's own run properties.",
            crosses=_ALL,
            response_control_color="808080",
        ),
        Row(heading="Training process"),
        Row(
            label="Design specifications of the training process:",
            description="Lead-in:",
            response="Click here to add text.",
            crosses={"ai_office": True, "nca": True},
            response_plchdr=True,
        ),
    ]

    located, document = _imported(tmp_path, rows, registry)

    assert set(located) == {
        "model-properties/model-architecture",
        "model-properties/total-model-size",
        "use/intended-uses",
        "use/acceptable-use-policy",
        "use/type-and-nature-of-ai-systems",
        "training-process/design-specifications-of-the-training-process",
    }
    assert set(located.values()) == {""}
    assert document == {"schema": 1}
    summary = summarise(located, registry)
    assert summary.rows_mapped == 0
    assert summary.fields_written == 0


def test_filled_answers_survive_and_only_the_alias_itself_reads_absent(
    tmp_path: Path, registry: Registry
) -> None:
    # A filled form's answers survive (including a text that is part of the
    # response alias but not equal to it) while the alias itself reads absent.
    rows = [
        Row(heading="Model properties"),
        Row(
            label="Model architecture:",
            response="a transformer architecture",
            crosses=_ALL,
        ),
        Row(
            label="Total model size:",
            response="7.3e10 parameters",
            crosses={"ai_office": True},
        ),
        Row(heading="Use"),
        Row(
            label="Intended uses:",
            response="Replace this with your",
            crosses=_ALL,
        ),
        Row(
            label=(
                "Type and nature of AI systems in which the general-purpose AI "
                "model can be integrated:"
            ),
            response="chat assistants",
            crosses=_ALL,
        ),
        Row(
            label="Acceptable Use Policy:",
            response=RESPONSE_ALIAS,
            crosses=_ALL,
        ),
    ]

    _, document = _imported(tmp_path, rows, registry)

    answers = {
        "intended_tasks": "Replace this with your\n\nchat assistants",
        "architecture_and_parameters": (
            "a transformer architecture\n\n7.3e10 parameters"
        ),
    }
    assert document == {
        "schema": 1,
        "annex_xi": answers,
        "annex_xii": answers,
    }


def test_the_summary_counts_located_mapped_and_skipped_rows(
    tmp_path: Path, registry: Registry
) -> None:
    # "mapped N rows to M fields; skipped K rows": K counts located rows with
    # no field; an unmatched row is silent.
    rows = [
        Row(heading="Use"),
        Row(label="Acceptable Use Policy:", response="serve coffee", crosses=_ALL),
        Row(heading="General information"),
        Row(
            label="Legal name for the model provider:",
            response="Acme Models Ltd",
            crosses=_ALL,
        ),
        Row(heading="Use"),
        Row(label="Not a published row:", response="orphan", crosses=_ALL),
    ]

    located, _ = _imported(tmp_path, rows, registry)

    assert summarise(located, registry) == MappedSummary(
        rows_mapped=1, fields_written=2, rows_skipped=1
    )


def test_a_response_cell_may_hold_property_less_controls(tmp_path: Path) -> None:
    # A bare w:sdt inside a response cell carries no properties at all: it is
    # no control the mapping knows, and its text is part of the response.
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body><w:tbl><w:tr>'
        "<w:tc><w:p><w:r><w:t>Model architecture:</w:t></w:r></w:p></w:tc>"
        "<w:sdt><w:sdtPr>"
        f'<w:alias w:val="{RESPONSE_ALIAS}"/><w:tag w:val="{RESPONSE_ALIAS}"/>'
        "</w:sdtPr><w:sdtContent><w:tc><w:p>"
        "<w:sdt><w:sdtContent><w:p><w:r><w:t>a transformer</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
        "</w:p></w:tc></w:sdtContent></w:sdt>"
        "<w:tc/><w:tc/><w:tc/>"
        "</w:tr></w:tbl></w:body></w:document>"
    )

    walked = read_rows(write_package(tmp_path / "form.docx", text))

    assert walked[0].answers[0].outer == "a transformer"


def test_a_control_style_alone_is_no_guidance_signal(tmp_path: Path) -> None:
    # The control's own rPr carries an rStyle but no colour: the text renders
    # in that style's colour and the mapping reads it as the answer it is, and
    # only the colours and styles the pinned form's guidance states count.
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body><w:tbl><w:tr>'
        "<w:tc><w:p><w:r><w:t>Model architecture:</w:t></w:r></w:p></w:tc>"
        "<w:sdt><w:sdtPr>"
        '<w:rPr><w:rStyle w:val="Style2"/></w:rPr>'
        f'<w:alias w:val="{RESPONSE_ALIAS}"/><w:tag w:val="{RESPONSE_ALIAS}"/>'
        "</w:sdtPr><w:sdtContent><w:tc><w:p><w:r><w:t>a transformer</w:t>"
        "</w:r></w:p></w:tc></w:sdtContent></w:sdt>"
        "<w:tc/><w:tc/><w:tc/>"
        "</w:tr></w:tbl></w:body></w:document>"
    )

    walked = read_rows(write_package(tmp_path / "form.docx", text))

    assert walked[0].answers[0].outer == "a transformer"


def test_a_two_pair_row_that_is_no_split_shape_matches_plainly_or_not_at_all(
    tmp_path: Path, registry: Registry
) -> None:
    # A second tick pair alone proves nothing: an ordinary row carrying one
    # still matches its label and crosses, and a row whose label concatenates
    # two published labels but whose pairs do not carry their crosses is no
    # match at all (the split is only the shape both halves agree on).
    split_label = [
        "Output modalities:",
        "For each selected modality please include maximum output size or "
        "write 'N/A' if not defined",
    ]
    rows = [
        Row(heading="Model properties"),
        Row(
            label="Model architecture:",
            response="a transformer",
            crosses=_ALL,
            extra_crosses={"ai_office": False, "nca": False, "downstream": True},
        ),
        Row(
            label_paragraphs=split_label,
            response="wrong first pair",
            crosses={"downstream": True},
            extra_crosses={"downstream": True},
        ),
        Row(
            label_paragraphs=split_label,
            response="wrong second pair",
            crosses=_ALL,
            extra_crosses=_ALL,
        ),
    ]

    located, _ = _imported(tmp_path, rows, registry)

    assert located == {"model-properties/model-architecture": "a transformer"}


def test_the_structured_routes_cover_every_structured_fields_rows(
    registry: Registry,
) -> None:
    # The two structured elements' rows are exactly the routed set: a row
    # that gained or lost its leaf would silently drop an answer.
    structured = [
        spec
        for spec in registry.fields
        if {"type:compute", "type:energy"} & set(spec.rules)
    ]
    assert {spec.model_field for spec in structured} == {
        "annex_xi.computational_resources",
        "annex_xi.energy_consumption",
    }
    assert {row_id for spec in structured for row_id in spec.form.rows} == set(
        _ROW_LEAVES
    )


def test_a_row_without_crosses_matches_an_inventory_row_without_flags(
    tmp_path: Path, registry: Registry
) -> None:
    # The data-provenance category definitions row carries no crosses at all
    # and invents nothing: it matches the one inventory row whose recorded
    # audience_flags are empty (structure note, wrinkle 4).
    rows = [
        Row(
            heading=(
                "Information on the data used for training, testing, and validation"
            )
        ),
        Row(
            label=(
                "For definitions of each listed category, see the Template for "
                "the Public Summary of the Training Content of General-Purpose "
                "AI models provided by the AI Office"
            ),
            crosses={},
        ),
    ]

    located, _ = _imported(tmp_path, rows, registry)

    (row_id,) = located
    assert row_id.startswith("data-used-for-training-testing-and-validation/")
    assert row_id.endswith("/data-provenance-category-options")
    assert located[row_id] == ""


def test_a_coloured_nested_control_keeps_its_same_frame_siblings(
    tmp_path: Path,
) -> None:
    # The guidance colour a nested response control states is the nested
    # control's own: it must not leak to the runs that follow it in the same
    # frame, or "answer B" reads as guidance and the answer is silently lost.
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body><w:tbl><w:tr>'
        "<w:tc><w:p><w:r><w:t>Model architecture:</w:t></w:r></w:p></w:tc>"
        "<w:sdt><w:sdtPr>"
        f'<w:alias w:val="{RESPONSE_ALIAS}"/><w:tag w:val="{RESPONSE_ALIAS}"/>'
        "</w:sdtPr><w:sdtContent><w:tc><w:p>"
        "<w:r><w:t>answer A</w:t></w:r>"
        '<w:sdt><w:sdtPr><w:rPr><w:color w:val="808080"/></w:rPr>'
        f'<w:alias w:val="{RESPONSE_ALIAS}"/><w:tag w:val="{RESPONSE_ALIAS}"/>'
        "</w:sdtPr><w:sdtContent><w:p><w:r><w:t>guidance</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
        "<w:r><w:t> answer B</w:t></w:r>"
        "</w:p></w:tc></w:sdtContent></w:sdt>"
        "<w:tc/><w:tc/><w:tc/>"
        "</w:tr></w:tbl></w:body></w:document>"
    )

    walked = read_rows(write_package(tmp_path / "form.docx", text))

    assert walked[0].answers[0] == CellAnswer("answer A answer B", "")


def test_a_coloured_nested_control_leaves_the_next_paragraphs_answer(
    tmp_path: Path,
) -> None:
    # The block-level variant of the same leak: the coloured nested control
    # sits in the cell between two answer paragraphs, so with the leak the
    # whole paragraph that follows it reads absent.
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body><w:tbl><w:tr>'
        "<w:tc><w:p><w:r><w:t>Model architecture:</w:t></w:r></w:p></w:tc>"
        "<w:sdt><w:sdtPr>"
        f'<w:alias w:val="{RESPONSE_ALIAS}"/><w:tag w:val="{RESPONSE_ALIAS}"/>'
        "</w:sdtPr><w:sdtContent><w:tc>"
        "<w:p><w:r><w:t>answer A</w:t></w:r></w:p>"
        '<w:sdt><w:sdtPr><w:rPr><w:color w:val="808080"/></w:rPr>'
        f'<w:alias w:val="{RESPONSE_ALIAS}"/><w:tag w:val="{RESPONSE_ALIAS}"/>'
        "</w:sdtPr><w:sdtContent><w:p><w:r><w:t>guidance</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
        "<w:p><w:r><w:t>answer B</w:t></w:r></w:p>"
        "</w:tc></w:sdtContent></w:sdt>"
        "<w:tc/><w:tc/><w:tc/>"
        "</w:tr></w:tbl></w:body></w:document>"
    )

    walked = read_rows(write_package(tmp_path / "form.docx", text))

    assert walked[0].answers[0] == CellAnswer("answer A answer B", "")


def test_a_duplicate_shaped_row_is_the_second_match_and_the_first_wins(
    tmp_path: Path, registry: Registry
) -> None:
    # A shape the document carries twice: the first walked match locates, the
    # second matches a row already taken and is counted as the duplicate
    # shape, neither mapped nor skipped.
    rows = [
        Row(heading="Model properties"),
        Row(label="Model architecture:", response="first answer", crosses=_ALL),
        Row(label="Model architecture:", response="second answer", crosses=_ALL),
    ]

    walked = read_rows(write_form_docx(tmp_path / "form.docx", rows))
    located = locate_rows(walked, registry)

    assert located == {"model-properties/model-architecture": "first answer"}
    assert count_duplicate_rows(walked, registry) == 1
    summary = summarise(located, registry, duplicate_rows=1)
    assert summary == MappedSummary(
        rows_mapped=1, fields_written=2, rows_skipped=0, duplicate_rows=1
    )


def test_duplicate_counting_ignores_the_paired_twins_and_orphans(
    tmp_path: Path, registry: Registry
) -> None:
    # Two rows are a duplicate only when the shape they repeat was already
    # answered by an earlier row. The Energy twins each pair with their own
    # published row, and an unmatched row is silent: neither is a duplicate.
    twins = [
        Row(heading="Energy consumption (during training and inference)"),
        Row(
            label="Measurement methodology:",
            response="training methodology",
            crosses={"ai_office": True, "nca": True},
        ),
        Row(
            label="Measurement methodology:",
            response="inference methodology",
            crosses={"ai_office": True, "nca": True},
        ),
        Row(heading="Use"),
        Row(label="Not a published row:", response="orphan", crosses=_ALL),
    ]

    walked = read_rows(write_form_docx(tmp_path / "twins.docx", twins))

    assert count_duplicate_rows(walked, registry) == 0

    # A third identical row has nothing left to pair with: it repeats a shape
    # an earlier row already answered and is counted once, however many
    # published rows the shape alone would match.
    third = [
        *twins[:3],
        Row(
            label="Measurement methodology:",
            response="a third methodology",
            crosses={"ai_office": True, "nca": True},
        ),
    ]

    walked = read_rows(write_form_docx(tmp_path / "third.docx", third))

    assert count_duplicate_rows(walked, registry) == 1


def test_a_repeated_split_shape_is_a_duplicate_row_too(
    tmp_path: Path, registry: Registry
) -> None:
    # The output-modalities row's split shape repeats: the second split row
    # finds both published rows taken, so it is a duplicate of the shape the
    # first carried.
    split = Row(
        label_paragraphs=[
            "Output modalities:",
            "For each selected modality please include maximum output size or "
            "write 'N/A' if not defined",
        ],
        split_responses=["1024 tokens", "2048 tokens", "N/A", "512 tokens"],
        response="the other output modalities",
        crosses=_ALL,
        extra_crosses={"ai_office": False, "nca": False, "downstream": True},
    )
    rows = [Row(heading="Model properties"), split, split]

    walked = read_rows(write_form_docx(tmp_path / "form.docx", rows))

    assert count_duplicate_rows(walked, registry) == 1


def test_rows_outside_their_inventory_section_are_no_duplicates(
    tmp_path: Path, registry: Registry
) -> None:
    # The location pass consumes a row only in its published row's own
    # section, and the duplicate counter applies the same predicate: a section
    # carrying same-label, same-flags rows the inventory publishes elsewhere
    # matches nothing, and an unmatched row is silent.
    rows = [
        Row(heading="Model properties"),
        Row(label="Model architecture:", response="the real answer", crosses=_ALL),
        Row(heading="Use"),
        Row(label="Model architecture:", response="stray one", crosses=_ALL),
        Row(label="Model architecture:", response="stray two", crosses=_ALL),
    ]

    walked = read_rows(write_form_docx(tmp_path / "form.docx", rows))
    located = locate_rows(walked, registry)

    assert located == {"model-properties/model-architecture": "the real answer"}
    assert count_duplicate_rows(walked, registry) == 0
    assert summarise(located, registry).rows_skipped == 0
