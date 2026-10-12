"""HTML to provision text: the parsing layer of the retrieval pipeline.

Every anchor a caller asked for must exist, so a changed page structure raises
:class:`ExtractionError` rather than yielding partial junk - what lets
verification report "extraction failed", never a silent text change.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser


class ExtractionError(Exception):
    """The fetched HTML does not contain an anchor the caller asked for."""


# Headings and enumerators as the consolidated text renders them. Section
# headings are uppercase in the enacted text and title case in the annexes.
_ANNEX_HEADING = re.compile(r"ANNEX [IVXL]+")
_SECTION_HEADING = re.compile(r"Section (\d+)", re.IGNORECASE)
_ARTICLE_HEADING = re.compile(r"Article (\d+)")
_ITEM_ENUMERATOR = re.compile(r"(\d+)\.")
# A numbered item whose enumerator renders inline with its sentence - Annex XI
# Section 2's letter-less items, "1.\xa0A detailed description ...".
_INLINE_ITEM = re.compile(r"^(\d+)\.\s+")
_LETTER_ENUMERATOR = re.compile(r"\(([a-z])\)")
# Sub-enumerators ("(i)", "(ii)", "(1)"), never provision text; the reason
# ``_LETTER_ENUMERATOR`` stays single-letter is the walker's addressing.
_SUB_ENUMERATOR = re.compile(r"\((?:[ivxlcdm]{1,4}|\d+)\)")
# A change-bar mark ("▼B", "▼M1") in a block of its own, sometimes with a dash
# rule out to the margin; the marks are never provision text.
_CHANGE_BAR = re.compile(r"▼[A-Z0-9]*(?:\s*[\u2014\u2013-]+)?")

# Elements that end a text block when rendered; everything else flows inline.
_BLOCK_TAGS = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_SKIPPED_TAGS = frozenset({"script", "style"})


class _BlockReader(HTMLParser):
    """Render HTML as a line per block-level element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pieces: list[str] = []
        self._skipped = 0
        # Open superscript runs, innermost last; an empty run contributes no
        # caret.
        self._superscripts: list[_SuperscriptRun] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipped += 1
        elif _is_superscript(tag, attrs) and not self._skipped:
            self._superscripts.append(_SuperscriptRun(tag, len(self._pieces)))
        elif tag in _BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipped = max(0, self._skipped - 1)
        elif self._superscripts and self._superscripts[-1].tag == tag:
            run = self._superscripts.pop()
            if run.texted:
                # The caret goes immediately before the run's text: "10" + "^"
                # + "25" gives "10^25".
                self._pieces.insert(run.start, "^")
        elif tag in _BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipped:
            self._pieces.append(data)
            if self._superscripts and data:
                self._superscripts[-1].texted = True

    def blocks(self) -> list[str]:
        text = "".join(self._pieces)
        return [line.strip() for line in text.splitlines() if line.strip()]


def _is_superscript(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    """True for an element that renders its own text as a superscript.

    The consolidated Regulation marks Article 51(2)'s threshold with a
    ``superscript`` span (not ``<sup>``); its rendered ``^`` keeps "10^25"
    from silently concatenating into an untrue "1025".
    """
    if tag == "sup":
        return True
    return any(
        name == "class" and value is not None and "superscript" in value.split()
        for name, value in attrs
    )


@dataclass
class _SuperscriptRun:
    """An open superscript element and where its contribution would go."""

    tag: str
    start: int
    texted: bool = False


@dataclass(frozen=True)
class _Element:
    """One extracted element and the block index of its sentence.

    ``letterless`` marks a numbered item rendered with its enumerator inline
    (Section 2's items), whose enumerator is dropped from the text.
    """

    id: str
    text_index: int
    letterless: bool = False


def normalise(text: str) -> str:
    """Decode entities, collapse whitespace, NFC, trim - and nothing else.

    Minimal by design: no typographic rewriting, so a hash moves
    only when the text itself does; ``\\s`` matches the non-breaking space.
    """
    # To a fixpoint: one pass can reveal a further escape, and normalise must
    # be safe to apply twice.
    while True:
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    text = re.sub(r"\s+", " ", text)
    text = unicodedata.normalize("NFC", text)
    return text.strip()


def sha256_of(text: str) -> str:
    """The hex SHA-256 of the UTF-8 bytes of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_element(
    html: bytes, annex: str, item: int, letter: str | None, section: int | None = None
) -> str:
    """The verbatim text of one published element, without its enumerator.

    ``section`` is the Annex XI section number (``None`` for Annex XII); a
    ``None`` ``letter`` addresses a section's letter-less numbered item.
    """
    blocks = _annex_blocks(html, annex)
    element = _find_element(annex, blocks, _element_id(annex, item, letter, section))
    text = blocks[element.text_index]
    if element.letterless:
        text = _INLINE_ITEM.sub("", text, count=1)
    return normalise(text)


def extract_chapeau(html: bytes, annex: str) -> str:
    """The chapeau sentence introducing an annex's numbered items."""
    blocks = _annex_blocks(html, annex)
    first_item: int | None = None
    for index, block in enumerate(blocks):
        if _ITEM_ENUMERATOR.fullmatch(block):
            first_item = index
            break
    if first_item is None:
        raise ExtractionError(f"no numbered items in ANNEX {annex}")
    # The span starts at the ANNEX heading, so a block always precedes the
    # first item.
    chapeau = blocks[first_item - 1]
    if _is_structural(chapeau):
        raise ExtractionError(f"no chapeau precedes the first item of ANNEX {annex}")
    return normalise(chapeau)


def extract_following_note(
    html: bytes, annex: str, item: int, letter: str, section: int | None = None
) -> str:
    """The paragraph following a point, as its own provision.

    Annex XI point 2(e)'s conditioning note is extracted this way.
    """
    blocks = _annex_blocks(html, annex)
    element = _find_element(annex, blocks, _element_id(annex, item, letter, section))
    index = _next_content_index(blocks, element.text_index)
    if index is None or _is_structural(blocks[index]):
        raise ExtractionError(f"no paragraph follows {element.id} in the fetched HTML")
    return normalise(blocks[index])


def extract_article(
    html: bytes, article: int, paragraph: int | None = None, point: str | None = None
) -> str:
    """The text of one article of the enacted regulation.

    ``paragraph`` addresses a numbered paragraph and ``point`` a lettered one
    within it; with neither, the whole article is joined. A point without its
    paragraph raises :class:`ExtractionError`, as does a missing anchor.
    """
    blocks = _article_blocks(html, article)
    if paragraph is None:
        if point is not None:
            raise ExtractionError(
                f"point ({point}) of Article {article} needs its paragraph"
            )
        return normalise(" ".join(_article_text(article, blocks)))
    start = _enumerator_index(
        blocks, f"{paragraph}.", f"paragraph {paragraph} of Article {article}"
    )
    if point is None:
        index = _next_content_index(blocks, start)
        if index is None or _is_structural(blocks[index]):
            raise ExtractionError(
                f"no text follows paragraph {paragraph} of Article {article} in "
                "the fetched HTML"
            )
        return normalise(blocks[index])
    end = _next_item_index(blocks, start)
    point_index = _point_index(blocks, point, start, end, article, paragraph)
    index = _next_content_index(blocks, point_index)
    if index is None or index >= end or _is_structural(blocks[index]):
        raise ExtractionError(
            f"no text follows point ({point}) of Article {article}({paragraph}) "
            "in the fetched HTML"
        )
    return normalise(blocks[index])


def element_inventory(html: bytes, annex: str) -> list[str]:
    """The ids of an annex's lettered elements and letter-less items, in order."""
    blocks = _annex_blocks(html, annex)
    return [element.id for element in _elements(annex, blocks)]


def _blocks_in(html: bytes) -> list[str]:
    reader = _BlockReader()
    reader.feed(html.decode("utf-8"))
    reader.close()
    return reader.blocks()


def _annex_blocks(html: bytes, annex: str) -> list[str]:
    """The blocks from an annex's heading to the next annex heading."""
    blocks = _blocks_in(html)
    heading = f"ANNEX {annex}"
    if heading not in blocks:
        raise ExtractionError(f"no {heading} heading in the fetched HTML")
    start = blocks.index(heading)
    for end in range(start + 1, len(blocks)):
        if _ANNEX_HEADING.fullmatch(blocks[end]):
            return blocks[start:end]
    return blocks[start:]


def _article_blocks(html: bytes, article: int) -> list[str]:
    """The blocks from an article's heading to the next heading or division."""
    blocks = _blocks_in(html)
    heading = f"Article {article}"
    if heading not in blocks:
        raise ExtractionError(f"no {heading} heading in the fetched HTML")
    start = blocks.index(heading)
    for end in range(start + 1, len(blocks)):
        if _ARTICLE_HEADING.fullmatch(blocks[end]) or _SECTION_HEADING.fullmatch(
            blocks[end]
        ):
            return blocks[start:end]
    return blocks[start:]


def _article_text(article: int, blocks: list[str]) -> list[str]:
    """An article's content blocks: the title line dropped, enumerators never."""
    content = blocks[1:]
    while content and _CHANGE_BAR.fullmatch(content[0]):
        content = content[1:]
    if not content or _is_structural(content[0]):
        raise ExtractionError(
            f"no title line follows Article {article} in the fetched HTML"
        )
    text = [block for block in content[1:] if not _is_structural(block)]
    if not text:
        raise ExtractionError(f"no text follows Article {article} in the fetched HTML")
    return text


def _enumerator_index(blocks: list[str], enumerator: str, what: str) -> int:
    for index, block in enumerate(blocks):
        if block == enumerator:
            return index
    raise ExtractionError(f"{what} not found in the fetched HTML")


def _next_item_index(blocks: list[str], start: int) -> int:
    """The block index of the next numbered paragraph, or the span's end."""
    for index in range(start + 1, len(blocks)):
        if _ITEM_ENUMERATOR.fullmatch(blocks[index]):
            return index
    return len(blocks)


def _point_index(
    blocks: list[str],
    point: str,
    paragraph_start: int,
    paragraph_end: int,
    article: int,
    paragraph: int,
) -> int:
    enumerator = f"({point})"
    for index in range(paragraph_start + 1, paragraph_end):
        if blocks[index] == enumerator:
            return index
    raise ExtractionError(
        f"point ({point}) of Article {article}({paragraph}) not found in the "
        "fetched HTML"
    )


def _element_id(annex: str, item: int, letter: str | None, section: int | None) -> str:
    prefix = annex if section is None else f"{annex}.{section}"
    return f"{prefix}.{item}" if letter is None else f"{prefix}.{item}.{letter}"


def _is_structural(block: str) -> bool:
    """True for blocks that are never provision text."""
    return bool(
        _ANNEX_HEADING.fullmatch(block)
        or _SECTION_HEADING.fullmatch(block)
        or _ITEM_ENUMERATOR.fullmatch(block)
        or _LETTER_ENUMERATOR.fullmatch(block)
        or _SUB_ENUMERATOR.fullmatch(block)
        or _CHANGE_BAR.fullmatch(block)
    )


def _next_content_index(blocks: list[str], index: int) -> int | None:
    """The next block after ``index`` that is not a change-bar mark."""
    for candidate in range(index + 1, len(blocks)):
        if not _CHANGE_BAR.fullmatch(blocks[candidate]):
            return candidate
    return None


def _elements(annex: str, blocks: list[str]) -> list[_Element]:
    """Walk an annex's blocks, joining each enumerator to its sentence.

    The inline-enumerator arm is read for Section 2 alone: the letter-less id
    needs the section, and the locator grammar admits no other letter-less
    address, so a Section 1 block opening with a number never yields one.
    """
    elements: list[_Element] = []
    section: int | None = None
    item: int | None = None
    for index, block in enumerate(blocks):
        section_match = _SECTION_HEADING.fullmatch(block)
        if section_match:
            section = int(section_match.group(1))
            item = None
            continue
        item_match = _ITEM_ENUMERATOR.fullmatch(block)
        if item_match:
            item = int(item_match.group(1))
            continue
        letter_match = _LETTER_ENUMERATOR.fullmatch(block)
        if letter_match:
            letter = letter_match.group(1)
            if item is None:
                raise ExtractionError(
                    f"point ({letter}) appears before any numbered item "
                    f"in ANNEX {annex}"
                )
            text_index = _next_content_index(blocks, index)
            if text_index is None or _is_structural(blocks[text_index]):
                raise ExtractionError(
                    f"no text follows point ({letter}) in ANNEX {annex}"
                )
            elements.append(
                _Element(_element_id(annex, item, letter, section), text_index)
            )
            continue
        if section != 2:
            continue
        numbered = _INLINE_ITEM.match(block)
        if numbered:
            item = int(numbered.group(1))
            elements.append(
                _Element(
                    _element_id(annex, item, None, section),
                    index,
                    letterless=True,
                )
            )
    return elements


def _find_element(annex: str, blocks: list[str], identifier: str) -> _Element:
    for element in _elements(annex, blocks):
        if element.id == identifier:
            return element
    raise ExtractionError(f"{identifier} not found in the fetched HTML")
