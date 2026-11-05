"""Read <table>s out of HTML with the standard library (no lxml/bs4 needed).

    tables = extract_tables(html)          # list[Table]
    for row in tables[0].rows: ...         # list[str] of cleaned cell texts

Cell text is cleaned (NFC, single spaces). colspan and rowspan are expanded by
repeating the cell, so every row of a rectangular table has the same length and
values stay under their real column.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from pipeline.extract.vietnamese import clean


@dataclass
class _Pending:
    text: str
    rows_left: int


@dataclass
class Table:
    rows: list[list[str]] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)
    caption: str = ""  # text just before the table (heading), for picking the right one

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self._stack: list[Table] = []  # nested tables
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._colspan = 1
        self._rowspan = 1
        # Per table: column index -> cell text still spanning down from a row above.
        self._spans: list[dict[int, _Pending]] = []
        self._skip = 0
        self._recent_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag == "table":
            caption = clean(" ".join(self._recent_text[-5:]))
            self._stack.append(Table(attrs=a, caption=caption))
            self._spans.append({})
        elif tag == "tr" and self._stack:
            self._row = []
            self._fill_spans()
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._colspan = _span(a.get("colspan"))
            self._rowspan = _span(a.get("rowspan"))
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif tag in {"thead", "tbody", "tfoot"} and self._spans:
            self._spans[-1].clear()  # a rowspan never crosses a row group

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = clean("".join(self._cell))
            spans = self._spans[-1]
            for _ in range(self._colspan):
                if self._rowspan > 1:
                    spans[len(self._row)] = _Pending(text, self._rowspan - 1)
                self._row.append(text)
                self._fill_spans()
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            self._fill_spans()
            if self._row:
                self._stack[-1].rows.append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())
            self._spans.pop()
            self._recent_text = []

    def _fill_spans(self) -> None:
        """Insert cells that span down from earlier rows at the current position."""
        if self._row is None or not self._spans:
            return
        spans = self._spans[-1]
        while len(self._row) in spans and spans[len(self._row)].rows_left > 0:
            pending = spans[len(self._row)]
            pending.rows_left -= 1
            self._row.append(pending.text)
            if pending.rows_left == 0:
                del spans[len(self._row) - 1]

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif data.strip():
            self._recent_text.append(data)
            del self._recent_text[:-20]


def _span(value: str | None) -> int:
    return int(value) if value and value.isdigit() and int(value) > 0 else 1


def extract_tables(html: str) -> list[Table]:
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    return parser.tables
