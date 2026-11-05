"""Turn a tariff PDF or a product page into plain text, one entry per page.

For each PDF page:
1. pdfplumber: the text layer, plus its tables.
2. Camelot, when pdfplumber finds text but no table on the page (lattice, then stream).
3. Tesseract (vie), when the page has no usable text layer (a scan).

Page numbers are kept (1-based, as in a PDF viewer). An HTML product page is one
"page". The text built here is exactly what the LLM sees, and every quote it
returns is checked against it (verify.py).
"""

import io
import json
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal

import pdfplumber

from pipeline.extract.vietnamese import clean

Method = Literal["pdfplumber", "camelot", "ocr", "html"]
MIN_TEXT_CHARS = 40  # fewer characters than this on a PDF page: treat it as a scan
OCR_RESOLUTION = 300


class DocumentError(Exception):
    """The document can't be read at all (not a PDF, no pages, OCR unavailable...)."""


@dataclass(frozen=True)
class Page:
    number: int  # 1-based
    text: str
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()
    method: Method = "pdfplumber"

    def render(self) -> str:
        """The page as sent to the LLM: text, then each table as ' | '-joined rows."""
        parts = [self.text]
        for i, table in enumerate(self.tables, 1):
            rows = "\n".join(" | ".join(cell for cell in row) for row in table)
            parts.append(f"[Bảng {i}]\n{rows}")
        return "\n\n".join(p for p in parts if p.strip())


def _cell(value: Any) -> str:
    return clean(str(value)) if value is not None else ""


def _tables(raw: list[list[list[Any]]]) -> tuple[tuple[tuple[str, ...], ...], ...]:
    out = []
    for table in raw:
        rows = tuple(tuple(_cell(c) for c in row) for row in table if any(c for c in row))
        if rows:
            out.append(rows)
    return tuple(out)


def _text(raw: str | None) -> str:
    """NFC, non-breaking spaces gone, line structure kept (it helps the LLM)."""
    text = unicodedata.normalize("NFC", raw or "").replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _camelot_tables(content: bytes, number: int) -> tuple[tuple[tuple[str, ...], ...], ...]:
    """Camelot needs a file path; errors (missing backend, no table) mean no tables."""
    import tempfile

    try:
        import camelot
    except ImportError:  # pragma: no cover - camelot is a dependency
        return ()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(content)
        handle.flush()
        for flavor in ("lattice", "stream"):
            try:
                found = camelot.read_pdf(  # type: ignore[attr-defined]
                    handle.name, pages=str(number), flavor=flavor
                )
            except Exception:  # Camelot raises many kinds of errors on odd pages
                continue
            tables = _tables([t.df.values.tolist() for t in found])
            if tables:
                return tables
    return ()


def _ocr(page: Any) -> str:
    import pytesseract

    image = page.to_image(resolution=OCR_RESOLUTION).original
    try:
        return str(pytesseract.image_to_string(image, lang="vie"))
    except pytesseract.TesseractError as exc:
        raise DocumentError(f"OCR failed on page {page.page_number}: {exc}") from exc


# --------------------------------------------------------------------------- column labels

LABEL_X_TOLERANCE = 5  # joins letter-spaced header text ("Trav e l" -> "Travel")
_NUMBERED = re.compile(r"^\d+(\.\d+)*\.?\s")  # "1. Phí phát hành", "2.1. Thẻ chính"


def _crop(page: Any, box: tuple[float, float, float, float]) -> Any:
    """Crop to a box clamped to the page: some tables (e.g. Techcombank's) run past the edge."""
    x0, top, x1, bottom = page.bbox
    return page.crop((max(box[0], x0), max(box[1], top), min(box[2], x1), min(box[3], bottom)))


def _label_rows(page: Any, table: Any) -> tuple[tuple[str, ...], ...] | None:
    """Rows of a cards-as-columns table, each cell prefixed with its column labels:

        2.1. Thẻ chính | [No.1] 299.000/năm | [MC2] 299.000/năm | [Lady, StepUp] 599.000/năm

    The labels come from the header text above each column (by position), so a
    quote carries both the card and the value, and the quote check proves which
    card a value belongs to. None when the table has no such header.

    Header = the rows above the first numbered fee row ("1. Phí ..."), minus title
    rows (one cell spanning the table). A label is read across all header rows,
    since card names often wrap onto two lines.
    """
    page = page.dedupe_chars()  # bold text drawn twice would read "PPhhíí"
    rows = table.rows
    texts = [[_cell(_crop(page, c).extract_text()) if c else None for c in r.cells] for r in rows]
    data_start = next(
        (
            i
            for i, r in enumerate(texts)
            if r and r[0] and _NUMBERED.match(r[0]) and sum(1 for c in rows[i].cells if c) >= 2
        ),
        None,
    )
    if data_start is None or data_start == 0:
        return None
    header_rows = [rows[i] for i in range(data_start) if sum(1 for c in rows[i].cells if c) >= 2]
    if not header_rows:
        return None
    top = min(r.bbox[1] for r in header_rows)
    bottom = max(r.bbox[3] for r in header_rows)
    widest = max(rows[data_start:], key=lambda r: sum(1 for c in r.cells if c))
    columns = [c for c in widest.cells if c][1:]  # first column holds the row labels
    if len(columns) < 2:
        return None
    labels = [
        " ".join(
            (
                _crop(page, (c[0], top, c[2], bottom)).extract_text(x_tolerance=LABEL_X_TOLERANCE)
                or ""
            ).split()
        )
        for c in columns
    ]
    if sum(1 for x in labels if x) < 0.6 * len(columns):
        return None

    out = []
    row_label = ""
    for row, text in zip(rows[data_start:], texts[data_start:], strict=True):
        if text[0]:
            row_label = text[0]
        parts = [row_label]
        for cell, value in zip(row.cells[1:], text[1:], strict=True):
            if not cell or not value:
                continue
            covered = [
                labels[i]
                for i, col in enumerate(columns)
                if cell[0] <= (col[0] + col[2]) / 2 <= cell[2] and labels[i]
            ]
            parts.append(f"[{', '.join(covered)}] {value}" if covered else value)
        if len(parts) > 1:
            out.append(tuple(parts))
    return tuple(out) or None


def read_pdf(
    content: bytes,
    *,
    label_columns: bool = False,
    section: tuple[str, str | None] | None = None,
) -> list[Page]:
    """`label_columns`: render tables with each cell's column labels (cards as columns).
    `section`: keep only the pages from the one containing section[0] up to, not
    including, the one containing section[1] (e.g. the credit card part of a
    tariff that also covers debit cards). Page numbers stay those of the PDF."""
    pages = _read_pdf(content, label_columns)
    if section is None:
        return pages
    start, end = section
    first = next((p.number for p in pages if start in p.text), None)
    if first is None:
        raise DocumentError(f"section start {start!r} not found in the document")
    last = next(
        (p.number - 1 for p in pages if end and p.number > first and end in p.text),
        pages[-1].number,
    )
    return [p for p in pages if first <= p.number <= last]


def _read_pdf(content: bytes, label_columns: bool) -> list[Page]:
    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:  # pdfminer raises several unrelated types
        raise DocumentError(f"not a readable PDF: {exc}") from exc
    pages = []
    with pdf:
        if not pdf.pages:
            raise DocumentError("the PDF has no pages")
        for number, page in enumerate(pdf.pages, 1):
            text = _text(page.extract_text())
            if len(text.replace("\n", "")) < MIN_TEXT_CHARS:
                pages.append(Page(number, _text(_ocr(page)), method="ocr"))
                continue
            tables = _tables(page.extract_tables())
            if label_columns:
                labelled = [_label_rows(page, t) for t in page.find_tables()]
                if any(labelled):
                    tables = tuple(t for t in labelled if t)
            method: Method = "pdfplumber"
            if not tables:
                tables = _camelot_tables(content, number)
                method = "camelot" if tables else "pdfplumber"
            pages.append(Page(number, text, tables, method))
    return pages


# --------------------------------------------------------------------------- HTML

_SKIP = {"script", "style", "noscript", "svg", "template", "head", "nav", "footer", "iframe"}
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "section", "td"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = [""]
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.lines.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.lines.append("")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.lines[-1] += data


_FLIGHT_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_FLIGHT_TEXT = re.compile(rb"[0-9a-f]+:T([0-9a-f]+),")


def _html_lines(markup: str) -> list[str]:
    parser = _Text()
    parser.feed(markup)
    return [" ".join(unicodedata.normalize("NFC", line).split()) for line in parser.lines]


def _embedded_blocks(markup: str) -> list[str]:
    """Text blocks a Next.js page ships as data, not markup (VPBank's tabs:
    "Tính năng nổi bật", "Lợi ích", FAQ). They are streamed in
    self.__next_f.push([1, "..."]) chunks; a text block is "<id>:T<hex byte length>,<html>".
    """
    chunks = _FLIGHT_PUSH.findall(markup)
    if not chunks:
        return []
    try:
        flight = "".join(json.loads(c) for c in chunks).encode("utf-8")
    except ValueError as exc:
        raise DocumentError(f"embedded page data can't be decoded: {exc}") from exc
    blocks = []
    for m in _FLIGHT_TEXT.finditer(flight):
        body = flight[m.end() : m.end() + int(m.group(1), 16)].decode("utf-8", errors="replace")
        blocks.append("\n".join(line for line in _html_lines(body) if line))
    return [b for b in blocks if b]


def read_html(content: bytes, *, until: str | None = None) -> list[Page]:
    """The page's visible text, then any text blocks it embeds as data.

    until: drop everything from this marker on (e.g. a news list under the card
    details); raises if the marker is missing, since the layout has changed.
    """
    markup = content.decode("utf-8", errors="replace")
    text = "\n".join(line for line in _html_lines(markup) if line)
    if until is not None:
        cut = text.find(until)
        if cut < 0:
            raise DocumentError(f"end marker {until!r} not found: the page layout changed")
        text = text[:cut].rstrip()
    embedded = _embedded_blocks(markup)
    if embedded:
        text = "\n\n".join([text, *embedded])
    if not text:
        raise DocumentError("the page has no text")
    return [Page(1, text, method="html")]


def read(
    content: bytes,
    content_type: str = "",
    *,
    label_columns: bool = False,
    section: tuple[str, str | None] | None = None,
    until: str | None = None,
) -> list[Page]:
    if content[:5] == b"%PDF-" or "pdf" in content_type:
        return read_pdf(content, label_columns=label_columns, section=section)
    return read_html(content, until=until)


def normalise_space(text: str) -> str:
    """For quote matching: NFC, one space for any run of whitespace."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()
