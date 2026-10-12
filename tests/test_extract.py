"""Annex and article extraction and normalisation.

The two committed EUR-Lex excerpts under tests/fixtures are the only inputs;
the tests never touch the network.
"""

import hashlib
import re
from pathlib import Path

import pytest

from gpai_docs.registry.extract import (
    ExtractionError,
    element_inventory,
    extract_article,
    extract_chapeau,
    extract_element,
    extract_following_note,
    normalise,
    sha256_of,
)

# The ANNEX XI to ANNEX XII span of consolidated Regulation (EU) 2024/1689
# (CELEX 02024R1689-20260727, as at 27 July 2026), fetched on 8 October 2026
# from
# <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02024R1689-20260727>
# and byte-identical to the Publications Office Cellar copy of the same CELEX.
FIXTURE = Path(__file__).parent / "fixtures" / "eurlex_annex_excerpt.html"
# The Article 51 to Article 53 span of the same consolidation, taken from the
# Publications Office Cellar copy
# (<https://publications.europa.eu/resource/celex/02024R1689-20260727>)
# because EUR-Lex serves the AWS WAF challenge (HTTP 202,
# empty body) at the pinned URL; it extracts to the same Annex provision
# texts the first fixture pins.
ARTICLES_FIXTURE = Path(__file__).parent / "fixtures" / "eurlex_articles_excerpt.html"

# The two annexes' inventories in document order: Annex
# XI's eleven lettered Section 1 elements followed by its three letter-less
# Section 2 items, and Annex XII's eleven elements.
XI_INVENTORY = [
    "XI.1.1.a",
    "XI.1.1.b",
    "XI.1.1.c",
    "XI.1.1.d",
    "XI.1.1.e",
    "XI.1.1.f",
    "XI.1.2.a",
    "XI.1.2.b",
    "XI.1.2.c",
    "XI.1.2.d",
    "XI.1.2.e",
    "XI.2.1",
    "XI.2.2",
    "XI.2.3",
]
XII_INVENTORY = [
    "XII.1.a",
    "XII.1.b",
    "XII.1.c",
    "XII.1.d",
    "XII.1.e",
    "XII.1.f",
    "XII.1.g",
    "XII.1.h",
    "XII.2.a",
    "XII.2.b",
    "XII.2.c",
]

XI_1_1_A = (
    "the tasks that the model is intended to perform and the type and nature of "
    "AI systems in which it can be integrated;"
)
XII_1_1_A = (
    "the tasks that the model is intended to perform and the type and nature of "
    "AI systems into which it can be integrated;"
)
XI_CHAPEAU = (
    "The technical documentation referred to in Article 53(1), point (a) shall "
    "contain at least the following information as appropriate to the size and "
    "risk profile of the model:"
)
XII_CHAPEAU = (
    "The information referred to in Article 53(1), point (b) shall contain at "
    "least the following:"
)
XI_2_E = "known or estimated energy consumption of the model."
XI_2_E_NOTE = (
    "With regard to point (e), where the energy consumption of the model is "
    "unknown, the energy consumption may be based on information about "
    "computational resources used."
)
XII_2_C = (
    "information on the data used for training, testing and validation, where "
    "applicable, including the type and provenance of data and curation "
    "methodologies."
)

# Annex XI Section 2's three letter-less items. The consolidated text renders
# each as one paragraph with the item enumerator inline ("1.\xa0A detailed
# description ...", the enumerator a span of its own); extraction returns the
# sentence without it, as for every other element.
XI_2_1 = (
    "A detailed description of the evaluation strategies, including evaluation "
    "results, on the basis of available public evaluation protocols and tools "
    "or otherwise of other evaluation methodologies. Evaluation strategies "
    "shall include evaluation criteria, metrics and the methodology on the "
    "identification of limitations."
)
XI_2_2 = (
    "Where applicable, a detailed description of the measures put in place for "
    "the purpose of conducting internal and/or external adversarial testing "
    "(e.g. red teaming), model adaptations, including alignment and fine-tuning."
)
XI_2_3 = (
    "Where applicable, a detailed description of the system architecture "
    "explaining how software components build or feed into each other and "
    "integrate into the overall processing."
)

# The Article 51-53 provisions the rule-provenance sources pin,
# extracted from the articles fixture.
A51_1_CHAPEAU = (
    "A general-purpose AI model shall be classified as a general-purpose AI "
    "model with systemic risk if it meets any of the following conditions:"
)
A51_1_A = (
    "it has high impact capabilities evaluated on the basis of appropriate "
    "technical tools and methodologies, including indicators and benchmarks;"
)
# The threshold is a superscript in the consolidated HTML
# (10<span class="superscript">25</span>); the extracted text renders it 10^25.
A51_2 = (
    "A general-purpose AI model shall be presumed to have high impact "
    "capabilities pursuant to paragraph 1, point (a), when the cumulative "
    "amount of computation used for its training measured in floating point "
    "operations is greater than 10^25."
)
A52_1 = (
    "Where a general-purpose AI model meets the condition referred to in "
    "Article 51(1), point (a), the relevant provider shall notify the "
    "Commission without delay and in any event within two weeks after that "
    "requirement is met or it becomes known that it will be met. That "
    "notification shall include the information necessary to demonstrate that "
    "the relevant requirement has been met. If the Commission becomes aware of "
    "a general-purpose AI model presenting systemic risks of which it has not "
    "been notified, it may decide to designate it as a model with systemic "
    "risk."
)
A53_1 = "Providers of general-purpose AI models shall:"
A53_1_A = (
    "draw up and keep up-to-date the technical documentation of the model, "
    "including its training and testing process and the results of its "
    "evaluation, which shall contain, at a minimum, the information set out in "
    "Annex XI for the purpose of providing it, upon request, to the AI Office "
    "and the national competent authorities;"
)
A53_1_B = (
    "draw up, keep up-to-date and make available information and documentation "
    "to providers of AI systems who intend to integrate the general-purpose AI "
    "model into their AI systems. Without prejudice to the need to observe and "
    "protect intellectual property rights and confidential business "
    "information or trade secrets in accordance with Union and national law, "
    "the information and documentation shall:"
)
A53_4 = (
    "Providers of general-purpose AI models may rely on codes of practice "
    "within the meaning of Article 56 to demonstrate compliance with the "
    "obligations set out in paragraph 1 of this Article, until a harmonised "
    "standard is published. Compliance with European harmonised standards "
    "grants providers the presumption of conformity to the extent that those "
    "standards cover those obligations. Providers of general-purpose AI models "
    "who do not adhere to an approved code of practice or do not comply with a "
    "European harmonised standard shall demonstrate alternative adequate means "
    "of compliance for assessment by the Commission."
)

# A change-bar block as the consolidated text renders it (the mark links to
# the amending act). Four of the pinned document's 130 change bars are also
# followed by a dash rule (U+2014) out to the margin; the repository
# fixture's span contains none, so the tolerance tests inject both forms.
CHANGE_BAR_MARKS = [
    pytest.param("\u25bcM1", id="mark"),
    pytest.param("\u25bcM1\u00a0\u2014\u2014\u2014\u2014\u2014", id="mark-and-rule"),
]


def _change_bar(mark: str) -> bytes:
    return f'<p class="modref"><a href="#">{mark}</a></p>'.encode()


@pytest.fixture(scope="module")
def html() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def articles() -> bytes:
    return ARTICLES_FIXTURE.read_bytes()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  The\u00a0EU \t AI\n\nAct  ", "The EU AI Act"),
        ("a\u00a0\u00a0b", "a b"),
        ("collapsed\n\tby\u00a0runs", "collapsed by runs"),
        ("runs    of     spaces", "runs of spaces"),
        ("Marks &amp; Spencer", "Marks & Spencer"),
        ("a&nbsp;b", "a b"),
        ("&lt;tag&gt;", "<tag>"),
    ],
)
def test_normalise_decodes_entities_and_collapses_whitespace(
    raw: str, expected: str
) -> None:
    assert normalise(raw) == expected


def test_normalise_applies_nfc() -> None:
    # The input is decomposed (e + combining acute), the expected value NFC.
    assert normalise("Café") == "Café"


def test_normalise_leaves_typography_alone() -> None:
    typographic = "\u2018quoted\u2019 \u2014 dashed \u2026"
    assert normalise(f"  {typographic}  ") == typographic


@pytest.mark.parametrize(
    "raw",
    [
        "  The\u00a0EU &amp; AI   Act\n\n",
        "&amp;nbsp;",
        "Café",
        "already normal",
        "10^25 FLOP",
        "",
    ],
)
def test_normalise_is_idempotent(raw: str) -> None:
    once = normalise(raw)
    assert normalise(once) == once


def test_sha256_of_hashes_the_utf8_bytes() -> None:
    # Digest computed once with hashlib and pinned here.
    assert (
        sha256_of(XI_1_1_A)
        == "71e8da87f97eba0ea100ccc9450ef3ed78f007353df2e821264ff67fd8af3024"
    )
    # UTF-8 is hashed, whatever the interpreter's preferred encoding.
    assert sha256_of("é") == hashlib.sha256(b"\xc3\xa9").hexdigest()


def test_extract_element_returns_the_verbatim_provision_without_its_enumerator(
    html: bytes,
) -> None:
    text = extract_element(html, "XI", 1, "a", 1)
    assert text == XI_1_1_A
    assert not text.startswith("(a)")
    assert "(a)" not in text


def test_extract_element_reads_both_annexes_independently(html: bytes) -> None:
    # The same point in Annex XII reads "into which", not Annex XI's "in which".
    assert extract_element(html, "XII", 1, "a") == XII_1_1_A
    assert extract_element(html, "XI", 2, "e", 1) == XI_2_E
    assert extract_element(html, "XII", 2, "c") == XII_2_C


def test_extract_element_raises_for_a_point_that_is_not_published(
    html: bytes,
) -> None:
    with pytest.raises(ExtractionError, match=r"XI\.1\.1\.g"):
        extract_element(html, "XI", 1, "g", 1)


def test_extract_element_reads_a_letterless_section_2_item(html: bytes) -> None:
    # Section 2's items carry no letter: the address is the section and the
    # numbered item, and the inline enumerator never enters the text.
    text = extract_element(html, "XI", 1, None, 2)
    assert text == XI_2_1
    assert not text.startswith("1.")
    assert extract_element(html, "XI", 2, None, 2) == XI_2_2
    assert extract_element(html, "XI", 3, None, 2) == XI_2_3


def test_a_section_2_item_renders_its_enumerator_inline() -> None:
    # The minimal shape of the rendering the fixture carries: a numbered item
    # whose enumerator sits inside its own paragraph, unlike Section 1's grid
    # where the enumerator is a block of its own.
    document = (
        "<p>ANNEX XI</p><p>Section 2</p>"
        '<div><p class="norm">1.\u00a0An inline numbered item.</p></div>'
        '<div><p class="norm">2.\u00a0A second inline item.</p></div>'
    ).encode()
    assert element_inventory(document, "XI") == ["XI.2.1", "XI.2.2"]
    assert extract_element(document, "XI", 1, None, 2) == "An inline numbered item."
    assert extract_element(document, "XI", 2, None, 2) == "A second inline item."


def test_a_numbered_item_without_a_section_is_not_an_element() -> None:
    # The letter-less arm needs a section: an inline enumerator in a
    # section-less annex (Annex XII's shape) names no element.
    document = (
        "<p>ANNEX XII</p><p>A chapeau sentence:</p>"
        '<div><p class="norm">1.\u00a0An inline numbered item.</p></div>'
    ).encode()
    assert element_inventory(document, "XII") == []
    with pytest.raises(ExtractionError, match=r"XII\.1"):
        extract_element(document, "XII", 1, None)


def test_a_section_1_content_block_beginning_with_a_number_is_not_an_element() -> None:
    # The letter-less address is Section 2's alone (the locator grammar
    # admits no other): a Section 1 content block that opens with "N. "
    # mints no element, and its number perturbs no item counter, so a later
    # letter still binds to its own numbered item.
    document = (
        b"<p>ANNEX XI</p><p>Section 1</p>"
        b"<p>1.</p>"
        b"<p>(a)</p>"
        b'<div><p class="norm">The provider shall document the model.</p></div>'
        b'<div><p class="norm">2. A number-led content block.</p></div>'
        b"<p>(b)</p>"
        b'<div><p class="norm">The second point.</p></div>'
    )
    assert element_inventory(document, "XI") == ["XI.1.1.a", "XI.1.1.b"]
    with pytest.raises(ExtractionError, match=r"XI\.1\.2"):
        extract_element(document, "XI", 2, None, 1)


def test_extract_element_raises_for_a_section_2_item_that_is_not_published(
    html: bytes,
) -> None:
    with pytest.raises(ExtractionError, match=r"XI\.2\.4"):
        extract_element(html, "XI", 4, None, 2)


def test_a_letter_does_not_address_a_section_2_item(html: bytes) -> None:
    # The Section 2 items are letter-less: a lettered address names no
    # published element there.
    with pytest.raises(ExtractionError, match=r"XI\.2\.1\.a"):
        extract_element(html, "XI", 1, "a", 2)


def test_a_document_without_an_annex_marker_raises(html: bytes) -> None:
    other = b"<html><body><p>No annexes in this document.</p></body></html>"
    with pytest.raises(ExtractionError, match="ANNEX XI"):
        extract_element(other, "XI", 1, "a", 1)
    with pytest.raises(ExtractionError, match="ANNEX XI"):
        extract_chapeau(other, "XI")
    with pytest.raises(ExtractionError, match="ANNEX XI"):
        element_inventory(other, "XI")
    # The fixture itself has no ANNEX XIII, so the same holds for annexes
    # outside the excerpt.
    with pytest.raises(ExtractionError, match="ANNEX XIII"):
        element_inventory(html, "XIII")


def test_extract_chapeau_returns_the_annex_chapeau_sentence(html: bytes) -> None:
    assert extract_chapeau(html, "XI") == XI_CHAPEAU
    assert extract_chapeau(html, "XII") == XII_CHAPEAU


def test_extract_chapeau_raises_when_no_item_follows(html: bytes) -> None:
    no_items = b"<p>ANNEX XI</p><p>Section 1</p><p>A chapeau with no items.</p>"
    with pytest.raises(ExtractionError, match="ANNEX XI"):
        extract_chapeau(no_items, "XI")


def test_extract_chapeau_raises_when_a_heading_precedes_the_first_item() -> None:
    document = (
        b"<p>ANNEX XI</p><p>Section 1</p><div><span>1.&nbsp;</span></div>"
        b"<p>An item with no chapeau.</p>"
    )
    with pytest.raises(ExtractionError):
        extract_chapeau(document, "XI")


def test_extract_following_note_returns_the_2e_conditioning_note(
    html: bytes,
) -> None:
    assert extract_following_note(html, "XI", 2, "e", 1) == XI_2_E_NOTE


def test_extract_following_note_raises_when_no_paragraph_follows(
    html: bytes,
) -> None:
    # XI 1(a) is followed by the "(b)" enumerator, not a note...
    with pytest.raises(ExtractionError):
        extract_following_note(html, "XI", 1, "a", 1)
    # ...and XII 2(c) ends its annex.
    with pytest.raises(ExtractionError):
        extract_following_note(html, "XII", 2, "c")
    # An unpublished point has no note either.
    with pytest.raises(ExtractionError, match=r"XI\.1\.1\.g"):
        extract_following_note(html, "XI", 1, "g", 1)


def test_element_inventory_lists_the_annex_elements_in_document_order(
    html: bytes,
) -> None:
    assert element_inventory(html, "XI") == XI_INVENTORY
    assert element_inventory(html, "XII") == XII_INVENTORY


@pytest.mark.parametrize("annex", ["XI", "XII"])
def test_every_listed_element_extracts_a_sentence_without_its_enumerator(
    html: bytes, annex: str
) -> None:
    inventory = element_inventory(html, annex)
    for identifier in inventory:
        parts = identifier.split(".")
        if len(parts) == 4:
            _, section, item, letter = parts
            text = extract_element(html, annex, int(item), letter, int(section))
        elif annex == "XI":
            # A letter-less Section 2 item: XI.<section>.<item>.
            _, section, item = parts
            text = extract_element(html, annex, int(item), None, int(section))
        else:
            _, item, letter = parts
            text = extract_element(html, annex, int(item), letter)
        assert text
        assert re.match(r"^(?:\d+\.|\([a-z]\))", text) is None


@pytest.mark.parametrize("mark", CHANGE_BAR_MARKS)
def test_extraction_tolerates_a_change_bar_before_a_provision_sentence(
    html: bytes, mark: str
) -> None:
    sentence = (
        b'<p class="norm">the tasks that the model is intended to perform and '
        b"the type and nature of AI systems in which it can be integrated;</p>"
    )
    assert html.count(sentence) == 1
    marked = html.replace(sentence, _change_bar(mark) + sentence)
    assert extract_element(marked, "XI", 1, "a", 1) == XI_1_1_A
    assert element_inventory(marked, "XI") == XI_INVENTORY


@pytest.mark.parametrize("mark", CHANGE_BAR_MARKS)
def test_extraction_tolerates_a_change_bar_before_the_conditioning_note(
    html: bytes, mark: str
) -> None:
    sentence = b"known or estimated energy consumption of the model.</p>"
    assert html.count(sentence) == 1
    marked = html.replace(sentence, sentence + _change_bar(mark))
    # The mark stays out of the 2(e) text and out of the note.
    assert extract_element(marked, "XI", 2, "e", 1) == XI_2_E
    assert extract_following_note(marked, "XI", 2, "e", 1) == XI_2_E_NOTE


def test_script_and_style_content_is_ignored() -> None:
    # If the style leaked, its "(z)" would be read as a lettered point with no
    # item; if the script leaked, its "ANNEX XII" would end the Annex XI span.
    document = (
        b"<html><head><title>T</title></head><body>"
        b"<p>ANNEX XI</p>"
        b"<p>A chapeau sentence:</p>"
        b"<style>(z)</style>"
        b"<script>ANNEX XII</script>"
        b"<div><span>1.&nbsp;</span></div>"
        b"<div><span>(a)&nbsp;</span></div>"
        b"<p>A lettered sentence.</p>"
        b"<p>A note follows.</p>"
        b"</body></html>"
    )
    assert element_inventory(document, "XI") == ["XI.1.a"]
    assert extract_element(document, "XI", 1, "a") == "A lettered sentence."
    assert extract_chapeau(document, "XI") == "A chapeau sentence:"
    assert extract_following_note(document, "XI", 1, "a") == "A note follows."


def test_a_lettered_point_before_any_item_raises() -> None:
    document = (
        b"<p>ANNEX XI</p><p>A chapeau sentence:</p>"
        b"<div><span>(a)&nbsp;</span></div><p>A lettered sentence.</p>"
    )
    with pytest.raises(ExtractionError):
        element_inventory(document, "XI")


def test_an_enumerator_with_no_following_block_raises() -> None:
    document = (
        b"<p>ANNEX XI</p><p>A chapeau sentence:</p>"
        b"<div><span>1.&nbsp;</span></div><div><span>(a)&nbsp;</span></div>"
    )
    with pytest.raises(ExtractionError, match=r"no text follows point \(a\)"):
        extract_element(document, "XI", 1, "a")


def test_another_enumerator_is_not_a_points_text() -> None:
    document = (
        b"<p>ANNEX XI</p><p>A chapeau sentence:</p>"
        b"<div><span>1.&nbsp;</span></div>"
        b"<div><span>(a)&nbsp;</span></div>"
        b"<div><span>(b)&nbsp;</span></div>"
        b"<p>A lettered sentence.</p>"
    )
    with pytest.raises(ExtractionError, match=r"no text follows point \(a\)"):
        element_inventory(document, "XI")


def test_extract_article_returns_the_lettered_point_of_a_paragraph(
    articles: bytes,
) -> None:
    assert extract_article(articles, 51, 1, "a") == A51_1_A
    assert extract_article(articles, 53, 1, "a") == A53_1_A
    assert extract_article(articles, 53, 1, "b") == A53_1_B


def test_extract_article_returns_a_numbered_paragraph(articles: bytes) -> None:
    assert extract_article(articles, 51, 1) == A51_1_CHAPEAU
    assert extract_article(articles, 52, 1) == A52_1
    assert extract_article(articles, 53, 1) == A53_1
    assert extract_article(articles, 53, 4) == A53_4


def test_extract_article_renders_a_superscript_run_with_a_caret(
    articles: bytes,
) -> None:
    # Article 51(2)'s threshold is served as 10<span class="superscript">25
    # </span>; the provision reads 10^25, never a silently concatenated 1025.
    assert extract_article(articles, 51, 2) == A51_2
    assert normalise(A51_2) == A51_2


def test_sup_elements_render_with_a_caret() -> None:
    # The native HTML superscript element renders the same way, so both
    # markups of the threshold extract alike.
    document = (
        b"<p>Article 1</p><p>A title</p><p>1.</p>"
        b"<p>greater than 10<sup>25</sup> FLOP and CO<sup>2</sup>.</p>"
    )
    text = extract_article(document, 1, 1)
    assert text == "greater than 10^25 FLOP and CO^2."
    assert normalise(text) == text


@pytest.mark.parametrize(
    "markup",
    [
        pytest.param(b'<span class="superscript"></span>', id="span"),
        pytest.param(b"<sup></sup>", id="sup"),
    ],
)
def test_an_empty_superscript_run_renders_nothing(markup: bytes) -> None:
    # A run with no text contributes nothing, never a stray caret baked into
    # a cited provision.
    document = (
        b"<p>Article 1</p><p>A title</p><p>1.</p>"
        b"<p>the suffix" + markup + b" joins nothing.</p>"
    )
    text = extract_article(document, 1, 1)
    assert text == "the suffix joins nothing."
    assert "^" not in text


def test_extract_article_without_a_paragraph_returns_the_whole_article(
    articles: bytes,
) -> None:
    text = extract_article(articles, 52)

    assert text.startswith(A52_1)
    assert text.endswith("in accordance with Union and national law.")
    # The title ("Procedure") is heading material, not provision text, and the
    # next division's heading does not leak into the article.
    assert "Procedure" not in text
    assert "SECTION" not in text


def test_extract_article_without_a_paragraph_drops_the_title() -> None:
    document = (
        b"<p>Article 7</p><p>Miniaturisation</p><p>Chapeau text.</p>"
        b"<p>1.</p><p>First paragraph.</p>"
        b"<p>SECTION 2</p><p>A division</p>"
        b"<p>Article 8</p><p>Next</p><p>Another text.</p>"
    )
    assert extract_article(document, 7) == "Chapeau text. First paragraph."


def test_extract_article_without_a_paragraph_drops_roman_sub_enumerators(
    articles: bytes,
) -> None:
    # Article 53(1)(b) nests (i)/(ii); the whole-article text carries the
    # sub-points' sentences, never their enumerator blocks.
    text = extract_article(articles, 53)

    assert "(i)" not in text
    assert "(ii)" not in text
    assert "enable providers of AI systems to have a good understanding" in text
    assert "contain, at a minimum, the elements set out in Annex XII;" in text


def test_extract_article_without_a_paragraph_drops_numbered_sub_enumerators() -> None:
    # Article 3's definitions are enumerated "(1)", "(2)", not "(a)".
    document = (
        b"<p>Article 3</p><p>Definitions</p>"
        b"<p>For the purposes of this Regulation, the following definitions apply:</p>"
        b"<p>(1)</p><p>First definition.</p>"
        b"<p>(2)</p><p>Second definition.</p>"
    )
    assert extract_article(document, 3) == (
        "For the purposes of this Regulation, the following definitions apply: "
        "First definition. Second definition."
    )


def test_extract_article_raises_for_an_article_the_document_does_not_carry(
    articles: bytes,
) -> None:
    with pytest.raises(ExtractionError, match="Article 99"):
        extract_article(articles, 99, 1)


def test_extract_article_tolerates_a_mark_before_the_title() -> None:
    # Some articles carry a change-bar mark between the heading and the title.
    document = (
        b'<p>Article 7</p><p class="modref">&#9660;M1</p><p>Miniaturisation</p>'
        b"<p>Chapeau text.</p><p>1.</p><p>First paragraph.</p>"
    )
    assert extract_article(document, 7) == "Chapeau text. First paragraph."


def test_extract_article_raises_for_a_paragraph_the_article_does_not_carry(
    articles: bytes,
) -> None:
    with pytest.raises(ExtractionError, match=r"paragraph 9 of Article 52"):
        extract_article(articles, 52, 9)
    with pytest.raises(ExtractionError, match=r"paragraph 9 of Article 52"):
        extract_article(articles, 52, 9, "a")


def test_extract_article_raises_for_a_point_its_paragraph_does_not_carry(
    articles: bytes,
) -> None:
    with pytest.raises(ExtractionError, match=r"point \(z\)"):
        extract_article(articles, 53, 1, "z")


def test_extract_article_point_search_stays_inside_its_paragraph() -> None:
    document = (
        b"<p>Article 1</p><p>A title</p>"
        b"<p>1.</p><p>First paragraph.</p>"
        b"<p>2.</p><p>Second paragraph.</p>"
        b"<p>(a)</p><p>A point of the second paragraph.</p>"
    )
    with pytest.raises(ExtractionError, match=r"point \(a\)"):
        extract_article(document, 1, 1, "a")
    assert extract_article(document, 1, 2, "a") == "A point of the second paragraph."


def test_extract_article_rejects_a_point_without_its_paragraph(
    articles: bytes,
) -> None:
    with pytest.raises(ExtractionError, match="paragraph"):
        extract_article(articles, 53, point="a")


def test_extract_article_without_a_title_line_raises_for_the_whole_article() -> None:
    document = b"<p>Article 3</p><p>1.</p><p>A paragraph.</p>"
    with pytest.raises(ExtractionError, match="title"):
        extract_article(document, 3)
    # A paragraph address needs no title.
    assert extract_article(document, 3, 1) == "A paragraph."


def test_extract_article_raises_when_nothing_follows_the_title() -> None:
    document = b"<p>Article 9</p><p>An empty article</p>"
    with pytest.raises(ExtractionError, match="no text"):
        extract_article(document, 9)


def test_extract_article_raises_when_an_enumerator_precedes_its_text() -> None:
    document = (
        b"<p>Article 1</p><p>A title</p><p>1.</p><p>(a)</p><p>(b)</p><p>A sentence.</p>"
    )
    with pytest.raises(ExtractionError, match="no text follows paragraph 1"):
        extract_article(document, 1, 1)
    with pytest.raises(ExtractionError, match=r"no text follows point \(a\)"):
        extract_article(document, 1, 1, "a")


def test_extract_article_tolerates_a_change_bar_before_a_paragraph(
    articles: bytes,
) -> None:
    anchor = b"Where a general-purpose AI model meets the condition"
    assert articles.count(anchor) == 1
    marked = articles.replace(anchor, b'<p class="modref">&#9660;M1</p>' + anchor)
    assert extract_article(marked, 52, 1) == A52_1
