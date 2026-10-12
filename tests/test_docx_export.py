"""Pin the Form package writer and the document renderer.

The writer fills a copy of a Form-shaped template, rewriting only
``word/document.xml``; the renderer turns a document into the per-row text it
fills. Synthetic packages come from ``tests/fixtures/form_docx.py``.
"""

import hashlib
import re
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from xml.etree import ElementTree as ET

import pytest

# tests/fixtures is a plain module (no package __init__); its directory goes
# on the path so the import below resolves under pytest's importlib mode and
# mypy alike.
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from form_docx import RESPONSE_ALIAS, Row, write_form_docx, write_package

from gpai_docs.documents import Document
from gpai_docs.docxform import (
    DocxError,
    build_document,
    document_values_for_rows,
    locate_rows,
    read_rows,
    write_form,
)
from gpai_docs.registry import Registry, load

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = f"{{{_W}}}p"
_R = f"{{{_W}}}r"
_BR = f"{{{_W}}}br"
_T = f"{{{_W}}}t"
_R_PR = f"{{{_W}}}rPr"
_R_STYLE = f"{{{_W}}}rStyle"
_COLOR = f"{{{_W}}}color"
_P_PR = f"{{{_W}}}pPr"
_P_STYLE = f"{{{_W}}}pStyle"
_VAL = f"{{{_W}}}val"
_ALIAS = f"{{{_W}}}alias"
_SDT = f"{{{_W}}}sdt"
_SDT_PR = f"{{{_W}}}sdtPr"
_SDT_CONTENT = f"{{{_W}}}sdtContent"
_SHOWING_PLC_HDR = f"{{{_W}}}showingPlcHdr"

_ALL = {"ai_office": True, "nca": True, "downstream": True}
_BOTH = {"ai_office": True, "nca": True, "downstream": False}
_NCA = {"ai_office": False, "nca": True, "downstream": False}

# The pinned form's guidance placeholder: a field given one reads ABSENT to
# the reader, so a test can prove a written answer replaced it.
_PLACEHOLDER = "Click here to add text."
_GUIDANCE_STYLE = "Style2"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _members(path: Path) -> list[tuple[str, bytes]]:
    """Every member of the package at ``path``, in member order, as bytes."""
    with zipfile.ZipFile(path) as package:
        return [
            (info.filename, package.read(info.filename)) for info in package.infolist()
        ]


def _part(path: Path) -> ET.Element:
    """The parsed ``word/document.xml`` of the package at ``path``."""
    return ET.fromstring(dict(_members(path))["word/document.xml"])


def _controls(tree: ET.Element) -> list[ET.Element]:
    """Every response control of a parsed part, in document order."""
    return [
        control
        for control in tree.iter(_SDT)
        if any(alias.get(_VAL) == RESPONSE_ALIAS for alias in control.iter(_ALIAS))
    ]


def _paragraph_texts(element: ET.Element) -> list[str]:
    """The text of each ``w:p`` beneath ``element``, in document order."""
    return [
        "".join(text.text or "" for text in paragraph.iter(_T))
        for paragraph in element.iter(_P)
    ]


def _run_texts(element: ET.Element) -> list[str]:
    """The text of each ``w:r`` beneath ``element``, in document order."""
    return [
        "".join(text.text or "" for text in run.iter(_T)) for run in element.iter(_R)
    ]


def _document_text(path: Path) -> str:
    """All text the package's document part holds, to assert what is absent."""
    return "".join(_part(path).itertext())


def _props(paragraph: ET.Element) -> ET.Element:
    """The paragraph's ``w:pPr``, which the writer must preserve."""
    props = paragraph.find(_P_PR)
    assert props is not None
    return props


def _bad_values(values: object) -> Mapping[str, str]:
    """A ``values_by_row`` of the wrong runtime shape (refusal matrix only)."""
    return cast("Mapping[str, str]", values)


def _template_row(path: Path, label: str) -> Path:
    """A one-row template whose response field is guidance-styled."""
    return write_form_docx(
        path,
        [
            Row(heading="Model properties"),
            Row(
                label=label,
                response_runs=["Click here to add text", "."],
                response_style=_GUIDANCE_STYLE,
                crosses=_ALL,
            ),
        ],
    )


def test_a_value_replaces_the_placeholder_runs_in_place(
    tmp_path: Path, registry: Registry
) -> None:
    # A written answer arrives as plain runs in the placeholder's own
    # paragraph, inside the cell's control, so the walk reads it back as the
    # answer and the control still wraps the row's cell.
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    out = tmp_path / "filled.docx"
    assert locate_rows(read_rows(template), registry) == {
        "model-properties/model-architecture": ""
    }

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }
    (control,) = _controls(_part(out))
    assert _paragraph_texts(control) == ["a transformer"]
    (run,) = list(control.iter(_R))
    # The guidance formatting is gone: the run states an automatic colour and
    # no style, so it reads (and renders) as the answer.
    props = run.find(_R_PR)
    assert props is not None
    assert props.find(_R_STYLE) is None
    colour = props.find(_COLOR)
    assert colour is not None
    assert colour.get(_VAL) == "auto"
    assert _run_texts(run) == ["a transformer"]


def test_a_control_stating_its_own_guidance_colour_still_takes_an_answer(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # The pinned form's answer controls state the placeholder's grey in their
    # own properties, so a bare written run would read as guidance; the
    # answer's explicit colour keeps it the answer.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_control_color="808080",
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"
    assert locate_rows(read_rows(template), registry) == {
        "model-properties/model-architecture": ""
    }

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }


def test_writing_an_answer_clears_the_showing_placeholder_flag(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # A control showing its placeholder reads absent however it is filled: the
    # writer clears the flag as Word does when an answer replaces guidance.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_plchdr=True,
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"
    assert locate_rows(read_rows(template), registry) == {
        "model-properties/model-architecture": ""
    }

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }
    (control,) = _controls(_part(out))
    props = control.find(_SDT_PR)
    assert props is not None
    assert props.find(_SHOWING_PLC_HDR) is None


def test_a_multi_line_value_becomes_further_paragraphs_in_the_cell(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # Further lines become further paragraphs in the same cell, carrying the
    # response paragraph's own properties; the walk joins them back with the
    # paragraph boundary, and the cell keeps its control.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_paragraph_style="AnswerBody",
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(
        template,
        {"model-properties/model-architecture": "first line\nsecond line\nthird line"},
        out,
    )

    (control,) = _controls(_part(out))
    assert _paragraph_texts(control) == ["first line", "second line", "third line"]
    serialised = [ET.tostring(props) for props in map(_props, control.iter(_P))]
    assert serialised == [serialised[0]] * 3
    style = _props(next(iter(control.iter(_P)))).find(_P_STYLE)
    assert style is not None
    assert style.get(_VAL) == "AnswerBody"
    content = control.find(_SDT_CONTENT)
    assert content is not None
    assert [child.tag for child in content] == [f"{{{_W}}}tc"]
    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "first line second line third line"
    }


def test_an_inline_response_field_takes_every_line_inside_its_control(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # The published form's run-level controls (its five soft-break rows) keep
    # every line inside the control: the first in its run, each further line
    # after a w:br, so no line lands beside the control as the row's
    # description and the reader maps the break back to the value's "\n".
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_paragraph_style="AnswerBody",
                response_inline=True,
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"
    assert locate_rows(read_rows(template), registry) == {
        "model-properties/model-architecture": ""
    }

    write_form(template, {"model-properties/model-architecture": "one\ntwo"}, out)

    tree = _part(out)
    (control,) = _controls(tree)
    content = control.find(_SDT_CONTENT)
    assert content is not None
    (run,) = list(content)
    assert run.tag == _R
    assert [child.tag for child in run] == [_R_PR, _T, _BR, _T]
    assert [child.text for child in run.iter(_T)] == ["one", "two"]
    holder = next(
        paragraph
        for paragraph in tree.iter(_P)
        if any(child is control for child in paragraph)
    )
    cell = next(
        element for element in tree.iter() if any(node is holder for node in element)
    )
    assert [child.tag for child in cell if child.tag == _P] == [_P]
    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "one\ntwo"
    }
    assert read_rows(out)[0].description == ""


def test_a_run_level_multi_line_value_round_trips_both_lines(
    tmp_path: Path, registry: Registry
) -> None:
    # A plain "a\nb" value on a Form run-level row survives export and import
    # whole: both lines are the answer, byte-exactly, and neither is filed as
    # the row's description. A blank line inside the value is the documented
    # normalisation, so "a\n\nb" settles to "a\nb".
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_inline=True,
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a\nb"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a\nb"
    }
    assert read_rows(out)[0].description == ""

    blank = tmp_path / "blank.docx"
    write_form(template, {"model-properties/model-architecture": "a\n\nb"}, blank)

    assert locate_rows(read_rows(blank), registry) == {
        "model-properties/model-architecture": "a\nb"
    }


def test_the_writer_finds_rows_through_every_wrapper_the_reader_walks(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # The walker unwraps row- and cell-wrapping controls and finds a plain
    # cell's inner response field; the writer locates its rows through the
    # same walk, so all three shapes fill.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                crosses=_ALL,
                wrap_row=True,
                wrap_cells=True,
            ),
            Row(
                label="Input modalities",
                response=_PLACEHOLDER,
                crosses=_ALL,
                wrap_row=False,
                wrap_cells=False,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(
        template,
        {
            "model-properties/model-architecture": "a transformer",
            "model-properties/input-modalities": "text and images",
        },
        out,
    )

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer",
        "model-properties/input-modalities": "text and images",
    }


def test_a_value_for_a_row_without_a_response_field_is_written_nowhere(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # A published row can carry no response field at all (an option row, or a
    # date control); the value has nowhere to go and the template's shapes are
    # left untouched.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                options=[(True, "Text")],
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": ""
    }
    assert "a transformer" not in _document_text(out)


_LABEL = (
    "For definitions of each listed category, see the Template for the "
    "Public Summary of the Training Content of General-Purpose AI models "
    "provided by the AI Office"
)


def _bare_control_package(path: Path, control: str) -> Path:
    """A package whose published row carries ``control`` as its whole area."""
    text = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body><w:tbl>'
        '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r>'
        "<w:t>Information on the data used for training, testing, and "
        "validation</w:t></w:r></w:p></w:tc><w:tc/></w:tr>"
        f"<w:tr><w:tc><w:p><w:r><w:t>{_LABEL}</w:t></w:r></w:p></w:tc>"
        f"<w:tc>{control}</w:tc></w:tr></w:tbl></w:body></w:document>"
    )
    return write_package(path, text)


def test_a_control_holding_its_own_runs_takes_the_lines_as_paragraphs(
    tmp_path: Path, registry: Registry
) -> None:
    # A control holding runs directly (no paragraph around them) reads as the
    # row's answer; the value's lines become paragraphs in its content, which
    # the walk reads back joined with the paragraph boundary (a bare run and a
    # paragraph would read back concatenated).
    control = (
        f'<w:sdt><w:sdtPr><w:alias w:val="{RESPONSE_ALIAS}"/>'
        f'<w:tag w:val="{RESPONSE_ALIAS}"/></w:sdtPr>'
        "<w:sdtContent><w:r><w:t>a placeholder</w:t></w:r></w:sdtContent></w:sdt>"
    )
    template = _bare_control_package(tmp_path / "template.docx", control)
    out = tmp_path / "filled.docx"
    row_id = (
        "data-used-for-training-testing-and-validation/data-provenance-category-options"
    )

    write_form(template, {row_id: "first\nsecond"}, out)

    assert locate_rows(read_rows(out), registry) == {row_id: "first second"}
    (control_element,) = _controls(_part(out))
    content = control_element.find(_SDT_CONTENT)
    assert content is not None
    assert _paragraph_texts(content) == ["first", "second"]


def test_a_control_with_no_content_is_written_nowhere(
    tmp_path: Path, registry: Registry
) -> None:
    # A control with nothing inside has no paragraph and no runs to take a
    # value: the write is skipped rather than crashing, and the row still
    # reads as the empty answer it is.
    control = (
        f'<w:sdt><w:sdtPr><w:alias w:val="{RESPONSE_ALIAS}"/>'
        f'<w:tag w:val="{RESPONSE_ALIAS}"/></w:sdtPr></w:sdt>'
    )
    template = _bare_control_package(tmp_path / "template.docx", control)
    out = tmp_path / "filled.docx"
    row_id = (
        "data-used-for-training-testing-and-validation/data-provenance-category-options"
    )

    write_form(template, {row_id: "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {row_id: ""}
    assert "a transformer" not in _document_text(out)


@pytest.mark.parametrize("inline", [True, False], ids=["run-level", "cell-level"])
def test_a_row_with_a_nested_table_and_its_own_field_writes_its_own_field(
    tmp_path: Path,
    registry: Registry,
    inline: bool,
) -> None:
    # The nested table is out of scope, its sibling response field is not: a
    # row carrying both writes the field it owns and leaves the nested rows as
    # they were.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                description="A description",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_inline=inline,
                nested=[Row(label="A nested row", response="the nested text")],
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }
    assert read_rows(out)[1].response == "the nested text"


@pytest.mark.parametrize("inline", [True, False], ids=["run-level", "cell-level"])
def test_a_nested_tables_response_control_is_out_of_the_writers_scope(
    tmp_path: Path,
    registry: Registry,
    inline: bool,
) -> None:
    # A response control inside a nested table is no field of the containing
    # row: the reader never reads that table as the row's answer, so the
    # value is written nowhere. Writing into it would clobber the nested row
    # where the reader never looks.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                description="A description",
                nested=[
                    Row(
                        label="A nested row",
                        response="the nested text",
                        response_inline=inline,
                    )
                ],
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": ""
    }
    assert "a transformer" not in _document_text(out)
    assert read_rows(out)[1].response == "the nested text"


def test_a_value_lands_in_the_split_rows_requested_half(
    tmp_path: Path, registry: Registry
) -> None:
    # The Output modalities row covers two published rows: the row's own
    # (cell-wrapped) answer is the first, the per-modality fields inside it the
    # maximum-size row's. A value for either half lands in that half's cell,
    # and in a sole cell when the row maps one.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label_paragraphs=[
                    "Output modalities:",
                    "For each selected modality please include maximum output "
                    "size or write 'N/A' if not defined",
                ],
                split_responses=["", ""],
                response="the row's own answer",
                crosses=_ALL,
                extra_crosses={"ai_office": False, "nca": False, "downstream": True},
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(
        template,
        {
            "model-properties/output-modalities": "text and images",
            "model-properties/output-modalities-maximum-size": "4096 tokens",
        },
        out,
    )

    located = locate_rows(read_rows(out), registry)
    assert located["model-properties/output-modalities"] == "text and images"
    assert located["model-properties/output-modalities-maximum-size"] == "4096 tokens"
    inner_one, inner_two, outer = _controls(_part(out))
    assert _run_texts(inner_one) == ["4096 tokens"]
    assert _run_texts(inner_two) == [""]  # the other maximum-size cell
    assert _run_texts(outer) == ["text and images"]


def test_a_value_with_no_lines_leaves_the_placeholder_alone(
    tmp_path: Path, registry: Registry
) -> None:
    # An empty value carries no line to write, so the template's guidance stays.
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": ""}, out)

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": ""
    }
    assert _document_text(out).count(_PLACEHOLDER) == 1


def test_a_line_surrounding_whitespace_is_preserved_in_the_run(
    tmp_path: Path,
) -> None:
    # A run whose text has leading or trailing whitespace states
    # xml:space="preserve", so Word keeps the spaces the value carries.
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": " padded "}, out)

    (text,) = [text for text in _part(out).iter(_T) if text.text == " padded "]
    assert text.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"


def test_a_multi_line_value_into_a_bare_paragraph_gains_no_properties(
    tmp_path: Path,
) -> None:
    # The template's response paragraph need not carry properties; the
    # further paragraphs then carry none either.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "one\ntwo"}, out)

    (control,) = _controls(_part(out))
    paragraphs = list(control.iter(_P))
    assert _paragraph_texts(control) == ["one", "two"]
    assert all(paragraph.find(_P_PR) is None for paragraph in paragraphs)


def _without_cell_controls(source: Path, target: Path) -> Path:
    """Rewrite a template's part with the response control wrapping a cell gone."""
    tree = _part(source)
    for control in list(tree.iter(_SDT)):
        if not any(alias.get(_VAL) == RESPONSE_ALIAS for alias in control.iter(_ALIAS)):
            continue
        content = control.find(_SDT_CONTENT)
        if content is None or len(content) != 1 or content[0].tag != f"{{{_W}}}tc":
            continue
        parent = next(
            node for node in tree.iter() if any(child is control for child in node)
        )
        parent[list(parent).index(control)] = content[0]
    return write_package(target, ET.tostring(tree, encoding="utf-8"))


def test_a_split_half_without_a_cell_to_fill_is_written_nowhere(
    tmp_path: Path, registry: Registry
) -> None:
    # The first half of a split row takes the cell its own control wraps; a
    # row of that shape without the cell has nowhere to put the value and
    # writes nothing rather than somewhere else.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label_paragraphs=[
                    "Output modalities:",
                    "For each selected modality please include maximum output "
                    "size or write 'N/A' if not defined",
                ],
                split_responses=[""],
                response="the row's own answer",
                crosses=_ALL,
                extra_crosses={"ai_office": False, "nca": False, "downstream": True},
            ),
        ],
    )
    unwrapped = _without_cell_controls(template, tmp_path / "unwrapped.docx")
    out = tmp_path / "filled.docx"

    write_form(
        unwrapped,
        {
            "model-properties/output-modalities": "text and images",
            "model-properties/output-modalities-maximum-size": "4096 tokens",
        },
        out,
    )

    located = locate_rows(read_rows(out), registry)
    assert located["model-properties/output-modalities"] == ""
    assert located["model-properties/output-modalities-maximum-size"] == "4096 tokens"
    assert "text and images" not in _document_text(out)


_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_W16 = "http://schemas.microsoft.com/office/word/2018/wordml"
_DECLARED = f'xmlns:mc="{_MC}" xmlns:w16="{_W16}" mc:Ignorable="w16"'


def _spliced_root(source: Path, target: Path, declaration: str) -> Path:
    """A template whose root declares a prefix its rows never use."""
    part = dict(_members(source))["word/document.xml"].decode("utf-8")
    return write_package(
        target, part.replace("<w:document ", f"<w:document {declaration} ", 1)
    )


def _root_tag(path: Path) -> str:
    """The document part's root start tag, as text."""
    text = dict(_members(path))["word/document.xml"].decode("utf-8")
    start = text.index("<w:document")
    return text[start : text.index(">", start) + 1]


def test_the_written_part_keeps_the_templates_own_declarations(
    tmp_path: Path,
    registry: Registry,
) -> None:
    # ElementTree declares only the namespaces the rewritten tree uses; the
    # Form declares more (several named in mc:Ignorable), so the unwritten
    # declarations are carried over or their tokens would be unbound.
    template = _spliced_root(
        _template_row(tmp_path / "plain.docx", "Model architecture"),
        tmp_path / "template.docx",
        _DECLARED,
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    head = _root_tag(out)
    assert f'xmlns:w16="{_W16}"' in head
    (ignorable,) = re.findall(r'Ignorable="([^"]*)"', head)
    prefixes = set(re.findall(r'xmlns:([A-Za-z_][\w.-]*)="', head))
    assert set(ignorable.split()) <= prefixes
    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }


def test_a_declaration_shaped_response_is_not_hoisted_into_the_root(
    tmp_path: Path, registry: Registry
) -> None:
    # Declarations come from the root start tag alone: a declaration-shaped
    # string in the response being replaced would spell xmlns:w16 twice and
    # leave the part unparsable if hoisted into the root.
    template = _spliced_root(
        write_form_docx(
            tmp_path / "plain.docx",
            [
                Row(heading="Model properties"),
                Row(
                    label="Model architecture",
                    response='xmlns:w16="http://not-a-declaration"',
                    response_style=_GUIDANCE_STYLE,
                    crosses=_ALL,
                ),
            ],
        ),
        tmp_path / "template.docx",
        _DECLARED,
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    head = _root_tag(out)
    assert head.count("xmlns:w16=") == 1
    assert "not-a-declaration" not in head
    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }


def test_an_answer_mentioning_a_prefix_does_not_mute_its_declaration(
    tmp_path: Path, registry: Registry
) -> None:
    # An answer spelling ``xmlns:w16="http://elsewhere"`` must not be read as
    # the template's declaration: the written part still needs the real one.
    template = _spliced_root(
        _template_row(tmp_path / "plain.docx", "Model architecture"),
        tmp_path / "template.docx",
        _DECLARED,
    )
    out = tmp_path / "filled.docx"
    answer = 'xmlns:w16="http://elsewhere" mc:Ignorable="w16"'

    write_form(template, {"model-properties/model-architecture": answer}, out)

    head = _root_tag(out)
    assert f'xmlns:w16="{_W16}"' in head
    assert "elsewhere" not in head
    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": answer
    }


def test_every_other_member_is_copied_through_byte_for_byte(tmp_path: Path) -> None:
    # Only word/document.xml is rewritten: every other member keeps its name,
    # its position and its bytes.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                crosses=_ALL,
            ),
        ],
        extra={"word/styles.xml": "<w:styles/>", "docProps/thumb.bin": b"\x00\xff"},
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    source, filled = _members(template), _members(out)
    assert [name for name, _ in filled] == [name for name, _ in source]
    for (name, data), (_, original) in zip(filled, source, strict=True):
        if name != "word/document.xml":
            assert data == original
    assert dict(filled)["word/document.xml"] != dict(source)["word/document.xml"]


def _restamp(path: Path, date_time: tuple[int, int, int, int, int, int]) -> None:
    """Rewrite a package with every member timestamp set to ``date_time``."""
    members = _members(path)
    with zipfile.ZipFile(path, "w") as package:
        for name, data in members:
            package.writestr(zipfile.ZipInfo(name, date_time=date_time), data)


def test_the_written_package_is_byte_stable(tmp_path: Path) -> None:
    # Same template bytes and document, same output bytes: every member
    # timestamp is the fixed 1980-01-01 value (determinism). The
    # template is restamped first, because the shipped fixture's own members
    # already read 1980 and the pin would be vacuous against them.
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    _restamp(template, (2020, 6, 1, 12, 30, 0))
    first, second = tmp_path / "one.docx", tmp_path / "two.docx"
    values = {"model-properties/model-architecture": "a transformer"}

    with zipfile.ZipFile(template) as package:
        assert {info.date_time for info in package.infolist()} == {
            (2020, 6, 1, 12, 30, 0)
        }
    write_form(template, values, first)
    write_form(template, values, second)

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as package:
        assert {info.date_time for info in package.infolist()} == {
            (1980, 1, 1, 0, 0, 0)
        }


def test_the_template_is_never_modified(tmp_path: Path) -> None:
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    before = _sha256(template)

    write_form(
        template,
        {"model-properties/model-architecture": "a transformer"},
        tmp_path / "filled.docx",
    )

    assert _sha256(template) == before


def test_the_member_headers_are_carried_over(
    tmp_path: Path, registry: Registry
) -> None:
    # zipfile's writer computes its own flag bits and defaults the member
    # attributes, so the template's own are restamped: every flag bit but the
    # data-descriptor one, which describes a layout this writer builds itself.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(label="Model architecture", response=_PLACEHOLDER, crosses=_ALL),
        ],
        extra={"word/styles.xml": "<w:styles/>"},
        flag_bits=0x0E,
        external_attr=0x81A40000,
    )
    out = tmp_path / "filled.docx"

    write_form(template, {"model-properties/model-architecture": "a transformer"}, out)

    with zipfile.ZipFile(template) as package:
        assert {info.flag_bits for info in package.infolist()} == {0x0E}
        assert {info.external_attr for info in package.infolist()} == {0x81A40000}
    with zipfile.ZipFile(out) as package:
        assert [info.filename for info in package.infolist()] == [
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
            "word/styles.xml",
        ]
        assert {info.flag_bits for info in package.infolist()} == {0x06}
        assert {info.external_attr for info in package.infolist()} == {0x81A40000}
        assert package.testzip() is None
    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }
    # A template stating no attributes keeps none: zipfile's writer would
    # default them to its own permissions.
    plain = _template_row(tmp_path / "plain.docx", "Model architecture")
    plain_out = tmp_path / "plain-filled.docx"
    write_form(
        plain, {"model-properties/model-architecture": "a transformer"}, plain_out
    )
    with zipfile.ZipFile(plain) as package:
        assert {info.external_attr for info in package.infolist()} == {0}
    with zipfile.ZipFile(plain_out) as package:
        assert {info.external_attr for info in package.infolist()} == {0}


def test_write_form_refuses_to_write_over_the_template(tmp_path: Path) -> None:
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    before = _sha256(template)

    with pytest.raises(DocxError, match="template"):
        write_form(
            template, {"model-properties/model-architecture": "a transformer"}, template
        )

    assert _sha256(template) == before


def test_a_filled_copy_re_reads_the_answers_it_was_given(
    tmp_path: Path, registry: Registry
) -> None:
    # The wiring half of the round trip: the renderer's values, written into a
    # template, re-read through read_rows + locate_rows and rebuilt into the
    # document, render again to the same rows.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_ALL,
            ),
            Row(heading="Computational resources (during training)"),
            Row(
                label="Training time",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_NCA,
            ),
            Row(
                label="Amount of computation used for training",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_NCA,
            ),
            Row(
                label="Measurement methodology",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_BOTH,
            ),
        ],
    )
    out = tmp_path / "filled.docx"
    document = Document(
        values={
            "annex_xi": {
                "architecture_and_parameters": "a transformer",
                "computational_resources": {
                    "training_time": "3 days",
                    "training_flop": 2.3e25,
                    "estimation_method": "benchmark extrapolation",
                },
            }
        }
    )

    values = document_values_for_rows(document, registry)
    write_form(template, values, out, registry=registry)

    located = locate_rows(read_rows(out), registry)
    assert located["model-properties/model-architecture"] == "a transformer"
    assert located["computational-resources/training-time"] == "3 days"
    assert (
        located["computational-resources/amount-of-computation-used-for-training"]
        == "2.3e+25 FLOP (estimated: benchmark extrapolation)"
    )
    assert (
        located["computational-resources/measurement-methodology"]
        == "benchmark extrapolation"
    )
    rebuilt = build_document(located, registry)
    assert rebuilt["annex_xi"] == {
        "architecture_and_parameters": "a transformer",
        "computational_resources": {
            "training_time": "3 days",
            "training_flop": "2.3e+25 FLOP (estimated: benchmark extrapolation)",
            "estimation_method": "benchmark extrapolation",
        },
    }
    assert document_values_for_rows(Document(values=rebuilt), registry) == values


def test_a_field_the_document_does_not_carry_keeps_its_placeholder(
    tmp_path: Path, registry: Registry
) -> None:
    # Export fills what the document carries and nothing more: a field absent
    # from the document contributes no row, so the template's placeholder
    # stays.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Model properties"),
            Row(
                label="Model architecture",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_ALL,
            ),
            Row(
                label="Input modalities",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_ALL,
            ),
        ],
    )
    out = tmp_path / "filled.docx"
    document = Document(
        values={"annex_xi": {"architecture_and_parameters": "a transformer"}}
    )

    write_form(template, document_values_for_rows(document, registry), out)

    located = locate_rows(read_rows(out), registry)
    assert located["model-properties/model-architecture"] == "a transformer"
    assert located["model-properties/input-modalities"] == ""


def test_values_for_rows_the_template_does_not_carry_are_left_out(
    tmp_path: Path, registry: Registry
) -> None:
    # A row id no walked row of the template answers to is written nowhere: an
    # unknown id and a known row of another section are both silent.
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    out = tmp_path / "filled.docx"

    write_form(
        template,
        {
            "model-properties/model-architecture": "a transformer",
            "general-information/release-date": "2026-10-10",
            "model-properties/no-such-row": "dropped",
        },
        out,
    )

    assert locate_rows(read_rows(out), registry) == {
        "model-properties/model-architecture": "a transformer"
    }


def test_write_form_refuses_a_template_it_cannot_read(tmp_path: Path) -> None:
    out = tmp_path / "filled.docx"

    with pytest.raises(DocxError, match="cannot read"):
        write_form(tmp_path / "absent.docx", {}, out)

    assert not out.exists()


def test_write_form_refuses_a_package_without_the_document_part(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template.docx"
    with zipfile.ZipFile(template, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")

    with pytest.raises(DocxError, match=r"word/document\.xml"):
        write_form(template, {}, tmp_path / "filled.docx")


def test_write_form_refuses_a_malformed_document_part(tmp_path: Path) -> None:
    template = write_package(tmp_path / "template.docx", "<w:document")

    with pytest.raises(DocxError, match=r"invalid word/document\.xml"):
        write_form(template, {}, tmp_path / "filled.docx")


def test_write_form_refuses_a_package_that_is_no_form(tmp_path: Path) -> None:
    # A well-formed package whose rows carry no published label is not the
    # Form: the walk locates nothing the registry knows.
    template = write_form_docx(
        tmp_path / "template.docx",
        [Row(label="Some other form row", response="a response")],
    )
    out = tmp_path / "filled.docx"

    with pytest.raises(DocxError, match="Model Documentation Form"):
        write_form(template, {}, out)

    assert not out.exists()


def test_write_form_refuses_values_that_are_not_row_id_to_text(
    tmp_path: Path,
) -> None:
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    out = tmp_path / "filled.docx"

    with pytest.raises(DocxError, match="mapping"):
        write_form(template, _bad_values(["not", "a", "mapping"]), out)
    with pytest.raises(DocxError, match="row id"):
        write_form(template, _bad_values({1: "an answer"}), out)
    with pytest.raises(DocxError, match="string"):
        write_form(
            template, _bad_values({"model-properties/model-architecture": 42}), out
        )

    assert not out.exists()


def test_write_form_refuses_a_value_the_document_part_cannot_carry(
    tmp_path: Path,
) -> None:
    # A control character or a lone surrogate would make word/document.xml
    # unparsable; the writer refuses rather than writing a broken package.
    template = _template_row(tmp_path / "template.docx", "Model architecture")
    out = tmp_path / "filled.docx"
    row_id = "model-properties/model-architecture"

    with pytest.raises(DocxError, match="character"):
        write_form(template, {row_id: "a\x00b"}, out)
    with pytest.raises(DocxError, match="character"):
        write_form(template, {row_id: "a\ud800b"}, out)

    assert not out.exists()


def test_an_absent_or_empty_field_renders_no_row(registry: Registry) -> None:
    assert document_values_for_rows(Document(values={}), registry) == {}
    assert document_values_for_rows(Document(values={"annex_xi": {}}), registry) == {}
    for empty in (None, "", "   "):
        values = Document(values={"annex_xi": {"licence": empty}})
        assert document_values_for_rows(values, registry) == {}


def test_a_text_value_renders_verbatim_on_its_first_row(registry: Registry) -> None:
    # A field mapping several rows writes its text once, on its first row in
    # the field's own order; the other rows stay untouched.
    document = Document(
        values={"annex_xi": {"input_output_modalities": "first\nsecond"}}
    )

    values = document_values_for_rows(document, registry)

    assert values == {"model-properties/input-modalities": "first\nsecond"}


def test_a_non_text_scalar_renders_as_its_text(registry: Registry) -> None:
    document = Document(values={"annex_xi": {"licence": 42, "intended_tasks": True}})

    values = document_values_for_rows(document, registry)

    assert values == {
        "distribution-and-licenses/license": "42",
        "use/intended-uses": "true",
    }


def test_the_rows_the_two_annexes_share_render_once(registry: Registry) -> None:
    # The Form's rows serve elements of both annexes; when both are present,
    # the first in registry order wins the row (the Form expects them to
    # agree).
    document = Document(
        values={
            "annex_xi": {"architecture_and_parameters": "the XI text"},
            "annex_xii": {"architecture_and_parameters": "the XII text"},
        }
    )

    values = document_values_for_rows(document, registry)

    assert values == {"model-properties/model-architecture": "the XI text"}


def test_the_compute_element_renders_its_leaves(registry: Registry) -> None:
    document = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": 2.3e25,
                    "estimation_method": "benchmark extrapolation",
                    "training_time": "3 days",
                }
            }
        }
    )

    values = document_values_for_rows(document, registry)

    assert list(values) == [
        "computational-resources/training-time",
        "computational-resources/amount-of-computation-used-for-training",
        "computational-resources/measurement-methodology",
    ]
    assert values == {
        "computational-resources/training-time": "3 days",
        "computational-resources/amount-of-computation-used-for-training": (
            "2.3e+25 FLOP (estimated: benchmark extrapolation)"
        ),
        "computational-resources/measurement-methodology": "benchmark extrapolation",
    }


def test_a_compute_amount_without_a_method_renders_alone(registry: Registry) -> None:
    # The estimation method rides the amount only when the document carries
    # text for it; an absent and an empty method both say nothing.
    for method in (None, ""):
        document = Document(
            values={
                "annex_xi": {
                    "computational_resources": {
                        "training_flop": 1e25,
                        "estimation_method": method,
                    }
                }
            }
        )

        values = document_values_for_rows(document, registry)

        assert values == {
            "computational-resources/amount-of-computation-used-for-training": (
                "1e+25 FLOP"
            )
        }


def test_a_structured_leaf_carried_as_empty_text_adds_no_row(
    registry: Registry,
) -> None:
    document = Document(
        values={
            "annex_xi": {
                "computational_resources": {"training_time": "", "training_flop": 2.5}
            }
        }
    )

    values = document_values_for_rows(document, registry)

    assert values == {
        "computational-resources/amount-of-computation-used-for-training": "2.5 FLOP"
    }


def test_a_string_amount_renders_verbatim_and_never_idempotence_breaks(
    registry: Registry,
) -> None:
    # A string amount the numeric reading left alone is already the
    # spelled-out form, so exporting it again writes it as it is: the round
    # trip's rendered text is stable.
    spelled = "2.3e+25 FLOP (estimated: benchmark extrapolation)"
    document = Document(
        values={
            "annex_xi": {
                "computational_resources": {
                    "training_flop": spelled,
                    "estimation_method": "benchmark extrapolation",
                }
            }
        }
    )

    values = document_values_for_rows(document, registry)

    assert values == {
        "computational-resources/amount-of-computation-used-for-training": spelled,
        "computational-resources/measurement-methodology": "benchmark extrapolation",
    }


def test_the_energy_element_renders_amounts_with_units_and_methods(
    registry: Registry,
) -> None:
    document = Document(
        values={
            "annex_xi": {
                "energy_consumption": {
                    "training": {"amount": 1234, "unit": "kWh", "method": "metered"},
                    "inference": {
                        "amount": 56.7,
                        "unit": "kWh",
                        "method": "extrapolated",
                    },
                }
            }
        }
    )

    values = document_values_for_rows(document, registry)

    assert values == {
        "energy-consumption/amount-of-energy-used-for-training": "1234 kWh",
        "energy-consumption/measurement-methodology-energy": "metered",
        "energy-consumption/benchmarked-amount-of-computation-used-for-inference": (
            "56.7 kWh"
        ),
        "energy-consumption/measurement-methodology-inference": "extrapolated",
    }


def test_an_energy_amount_without_a_unit_renders_alone(registry: Registry) -> None:
    document = Document(
        values={"annex_xi": {"energy_consumption": {"training": {"amount": 1234}}}}
    )

    values = document_values_for_rows(document, registry)

    assert values == {"energy-consumption/amount-of-energy-used-for-training": "1234"}


@pytest.mark.parametrize(
    ("annex", "field"),
    [
        ({"licence": ["a"]}, "annex_xi.licence"),
        (
            {"computational_resources": "not a mapping"},
            "annex_xi.computational_resources",
        ),
        (
            {"computational_resources": {"training_flop": float("inf")}},
            "annex_xi.computational_resources.training_flop",
        ),
        (
            {"energy_consumption": {"training": {"amount": ["a"]}}},
            "annex_xi.energy_consumption.training.amount",
        ),
        (
            {"energy_consumption": {"training": "not a mapping"}},
            "annex_xi.energy_consumption",
        ),
    ],
)
def test_an_unreadable_document_value_is_refused(
    annex: dict[str, object], field: str, registry: Registry
) -> None:
    document = Document(values={"annex_xi": annex})

    with pytest.raises(DocxError) as excinfo:
        document_values_for_rows(document, registry)

    assert field in str(excinfo.value)


def test_a_non_mapping_annex_section_is_refused(registry: Registry) -> None:
    document = Document(values={"annex_xi": "not a mapping"})

    with pytest.raises(DocxError) as excinfo:
        document_values_for_rows(document, registry)

    assert "annex_xi" in str(excinfo.value)


def test_an_unknown_key_in_the_document_is_silent(registry: Registry) -> None:
    document = Document(values={"annex_xi": {"not_a_field": "x", "licence": "MIT"}})

    values = document_values_for_rows(document, registry)

    assert values == {"distribution-and-licenses/license": "MIT"}


# The shared-row ownership rule and the round trip.

# The audience crosses of the Form's downstream-only rows.
_DOWNSTREAM = {"downstream": True}


def _text(value: object) -> str:
    """A document value as its compared text, whitespace-normalised."""
    assert isinstance(value, str), value
    return " ".join(value.split())


def _mapping(document: Document, section: str) -> dict[str, object]:
    """A loaded document's annex section, for the per-field reads below."""
    value = document.values[section]
    assert isinstance(value, dict), value
    return value


def test_a_shared_row_is_written_by_the_first_carrying_claimant(
    registry: Registry,
) -> None:
    # use/required-software carries two annex XII elements; the export's owner
    # is the first claimant in registry order that carries a value, and a
    # later claimant skips the shared row, so no second text can be
    # re-absorbed on the next import.
    document = Document(
        values={
            "annex_xii": {
                "hardware_software_interaction": "the hardware and software",
                "software_versions": "the versions",
            }
        }
    )

    assert document_values_for_rows(document, registry) == {
        "use/required-hardware": "the hardware and software"
    }

    # A later claimant carrying the value alone owns the row: an Annex
    # XII-only document is not silenced.
    later_only = Document(values={"annex_xii": {"software_versions": "the versions"}})

    assert document_values_for_rows(later_only, registry) == {
        "use/required-software": "the versions"
    }

    xii_only = Document(values={"annex_xii": {"intended_tasks": "the tasks"}})

    assert document_values_for_rows(xii_only, registry) == {
        "use/intended-uses": "the tasks"
    }

    # Empty and blank values carry nothing, so nothing is written.
    empty = Document(
        values={
            "annex_xii": {
                "hardware_software_interaction": "",
                "software_versions": "   ",
            }
        }
    )

    assert document_values_for_rows(empty, registry) == {}


def test_export_import_cycles_stop_compounding(
    tmp_path: Path, registry: Registry
) -> None:
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Use"),
            Row(
                label="Required hardware",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_DOWNSTREAM,
            ),
            Row(
                label="Required software",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_DOWNSTREAM,
            ),
        ],
    )

    def cycles(
        start: Document, prefix: str
    ) -> tuple[list[Path], list[dict[str, object]]]:
        """Three export-import cycles from ``start``: (forms, documents)."""
        forms: list[Path] = []
        documents: list[dict[str, object]] = []
        current = start
        for index in range(3):
            form = tmp_path / f"{prefix}-{index}.docx"
            write_form(template, document_values_for_rows(current, registry), form)
            current = Document(
                values=build_document(locate_rows(read_rows(form), registry), registry)
            )
            forms.append(form)
            documents.append(current.values)
        return forms, documents

    # With both claimants carrying a value, only the owner is written and the
    # later claimant's text is dropped: every cycle is byte-stable (the
    # second's document and form bytes equal the first's).
    coherent = Document(
        values={
            "annex_xii": {
                "hardware_software_interaction": "HW-A SW-B",
                "software_versions": "SW-B",
            }
        }
    )
    forms, documents = cycles(coherent, "coherent")

    assert documents[0] == {
        "schema": 1,
        "annex_xii": {"hardware_software_interaction": "HW-A SW-B"},
    }
    assert documents[1] == documents[0]
    assert forms[1].read_bytes() == forms[0].read_bytes()

    # The shape the import itself produces: the first cycle settles the text
    # (the export encodes the blank line as an empty paragraph, which the
    # import reads back as the join's space), and the cycles after it are
    # byte-stable; the growth does not continue.
    imported = Document(
        values={
            "annex_xii": {
                "hardware_software_interaction": "HW-A\n\nSW-B",
                "software_versions": "SW-B",
            }
        }
    )
    forms, documents = cycles(imported, "imported")

    assert documents[0] == documents[1] == documents[2]
    assert documents[0] == {
        "schema": 1,
        "annex_xii": {"hardware_software_interaction": "HW-A SW-B"},
    }
    assert forms[1].read_bytes() == forms[2].read_bytes()

    # A document carrying only the later claimant writes its text on the
    # shared row; the import files that row back to both claimants and the
    # owner rewrites it next export, so the text relocates once and never
    # grows.
    later = Document(values={"annex_xii": {"software_versions": "SW-B"}})
    forms, documents = cycles(later, "later")

    assert documents[0] == {
        "schema": 1,
        "annex_xii": {
            "hardware_software_interaction": "SW-B",
            "software_versions": "SW-B",
        },
    }
    assert (
        documents[1]
        == documents[2]
        == {
            "schema": 1,
            "annex_xii": {"hardware_software_interaction": "SW-B"},
        }
    )
    assert forms[1].read_bytes() == forms[2].read_bytes()


def test_the_round_trip_through_the_exported_form(
    tmp_path: Path, registry: Registry
) -> None:
    # Export writes the document into the synthetic Form and the CLI's import
    # mapping (read_rows, locate_rows, build_document) re-imports it: every
    # field compares equal, whitespace-normalised, with structured leaves
    # compared by the renderer's spelled-out text.
    template = write_form_docx(
        tmp_path / "template.docx",
        [
            Row(heading="Use"),
            Row(
                label="Intended uses",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_ALL,
            ),
            Row(
                label=(
                    "Type and nature of AI systems in which the "
                    "general-purpose AI model can be integrated"
                ),
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_ALL,
            ),
            Row(
                label="Acceptable Use Policy",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                response_inline=True,
                crosses=_ALL,
            ),
            Row(
                label="Required hardware",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_DOWNSTREAM,
            ),
            Row(
                label="Required software",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_DOWNSTREAM,
            ),
            Row(heading="Computational resources (during training)"),
            Row(
                label="Training time",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_NCA,
            ),
            Row(
                label="Amount of computation used for training",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_NCA,
            ),
            Row(
                label="Measurement methodology",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_BOTH,
            ),
            Row(heading="Energy consumption (during training and inference)"),
            Row(
                label="Amount of energy used for training",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_BOTH,
            ),
            Row(
                label="Measurement methodology",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_BOTH,
            ),
            Row(
                label="Benchmarked amount of computation used for inference",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_BOTH,
            ),
            Row(
                label="Measurement methodology",
                response=_PLACEHOLDER,
                response_style=_GUIDANCE_STYLE,
                crosses=_BOTH,
            ),
        ],
    )
    document = Document(
        values={
            "annex_xi": {
                "intended_tasks": "the intended tasks",
                "acceptable_use_policies": "first line\nsecond line",
                "computational_resources": {
                    "training_time": "3 days",
                    "training_flop": 2.3e25,
                    "estimation_method": "benchmark extrapolation",
                },
                "energy_consumption": {
                    "training": {"amount": 1234, "unit": "kWh", "method": "metered"},
                    "inference": {
                        "amount": 56.7,
                        "unit": "kWh",
                        "method": "extrapolated",
                    },
                },
            },
            "annex_xii": {
                "intended_tasks": "the intended tasks",
                "hardware_software_interaction": "HW-A\n\nSW-B",
                "software_versions": "SW-B",
            },
        }
    )
    out = tmp_path / "filled.docx"

    values = document_values_for_rows(document, registry)
    write_form(template, values, out, registry=registry)
    imported = Document(
        values=build_document(locate_rows(read_rows(out), registry), registry)
    )
    xi = _mapping(imported, "annex_xi")
    xii = _mapping(imported, "annex_xii")

    # Text fields are whitespace-normalised; the shared rows of the two
    # annexes fill BOTH claimants from the owner's text, so
    # annex_xii.intended_tasks reads the answer annex_xi's row carried.
    assert _text(xi["intended_tasks"]) == "the intended tasks"
    assert _text(xii["intended_tasks"]) == "the intended tasks"

    # The run-level shape is in the gate too: a plain multi-line value on the
    # Form's acceptable-use-policy row reads back both lines, byte-exactly,
    # with nothing beside the control as the row's description.
    assert xi["acceptable_use_policies"] == "first line\nsecond line"
    assert xii["acceptable_use_policies"] == "first line\nsecond line"

    # The structured leaves compare per the renderer's spelled-out text: the
    # compute amount as "<amount> FLOP (estimated: ...)", the energy amounts
    # with their units, the methods verbatim.
    assert values["computational-resources/training-time"] == "3 days"
    assert (
        values["computational-resources/amount-of-computation-used-for-training"]
        == "2.3e+25 FLOP (estimated: benchmark extrapolation)"
    )
    assert values["energy-consumption/amount-of-energy-used-for-training"] == "1234 kWh"
    assert xi["computational_resources"] == {
        "training_time": "3 days",
        "training_flop": "2.3e+25 FLOP (estimated: benchmark extrapolation)",
        "estimation_method": "benchmark extrapolation",
    }
    assert xi["energy_consumption"] == {
        "training": {"amount": "1234 kWh", "method": "metered"},
        "inference": {"amount": "56.7 kWh", "method": "extrapolated"},
    }

    # The shared-row pair's stable outcome: the owner's text is written, the
    # shared software row carries nothing, and the later claimant's distinct
    # text is not recoverable from the Form.
    assert _text(xii["hardware_software_interaction"]) == "HW-A SW-B"
    assert "software_versions" not in xii
    assert "use/required-software" not in values
