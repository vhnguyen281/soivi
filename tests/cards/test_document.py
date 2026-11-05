"""Document text: pdfplumber per page, Camelot and OCR fallbacks, HTML product page."""

from typing import Any

import pytest

from pipeline.cards import document
from pipeline.cards.document import DocumentError, read, read_html, read_pdf
from tests.cards.conftest import PRODUCTS_HTML, TARIFF_PDF


def test_tariff_pdf_pages() -> None:
    pages = read_pdf(TARIFF_PDF.read_bytes())
    assert [p.number for p in pages] == list(range(1, 9))
    assert {p.method for p in pages} == {"pdfplumber"}
    first = pages[0].render()
    assert "PHỤ LỤC 1.6: BIỂU PHÍ DỊCH VỤ THẺ TÍN DỤNG CHO KHÁCH HÀNG THƯỜNG" in first
    assert "4.1 | | Thẻ tín dụng Visa Signature | 1.499.000 VND/thẻ" in first.replace("|  |", "| |")
    assert "Thẻ tín dụng Techcombank Style | 2.59%*số tiền giao dịch" in pages[1].render()
    assert "Thẻ tín dụng Visa Chuẩn & Visa VNA chuẩn | 80.000.000 VNĐ" in pages[7].render()


def test_camelot_when_pdfplumber_finds_no_table(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_camelot(content: bytes, number: int) -> Any:
        calls.append(number)
        return ((("Loại thẻ", "Phí"), ("Visa", "1.000.000 VND")),)

    monkeypatch.setattr(document, "_camelot_tables", fake_camelot)
    monkeypatch.setattr("pdfplumber.page.Page.extract_tables", lambda self, *a, **k: [])
    pages = read_pdf(TARIFF_PDF.read_bytes())
    assert calls == list(range(1, 9))
    assert {p.method for p in pages} == {"camelot"}
    assert "Visa | 1.000.000 VND" in pages[0].render()


def test_ocr_for_pages_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pdfplumber.page.Page.extract_text", lambda self, *a, **k: "")
    monkeypatch.setattr(document, "_ocr", lambda page: f"Trang quét {page.page_number}")
    pages = read_pdf(TARIFF_PDF.read_bytes())
    assert [(p.number, p.method, p.text) for p in pages][:2] == [
        (1, "ocr", "Trang quét 1"),
        (2, "ocr", "Trang quét 2"),
    ]


@pytest.mark.ocr
def test_real_ocr_reads_vietnamese() -> None:  # pragma: no cover - slow, needs Tesseract
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(TARIFF_PDF.read_bytes())) as pdf:
        text = document._ocr(pdf.pages[0])
    assert "THẺ TÍN DỤNG" in text.upper()


def test_product_page_is_one_page_of_text() -> None:
    [page] = read_html(PRODUCTS_HTML.read_bytes())
    assert page.number == 1 and page.method == "html"
    assert "Thẻ tín dụng Techcombank Visa Signature" in page.text
    assert "Hoàn tiền lên tới 5 triệu/tháng, tới 10%" in page.text
    assert "<script" not in page.text and len(page.text) < 20_000


def test_read_dispatches_and_rejects_garbage() -> None:
    assert read(TARIFF_PDF.read_bytes())[0].method == "pdfplumber"
    assert read(PRODUCTS_HTML.read_bytes(), "text/html")[0].method == "html"
    with pytest.raises(DocumentError):
        read(b"%PDF-1.7 broken")
    with pytest.raises(DocumentError):
        read(b"<html><script>x</script></html>")


VPB_PDF = TARIFF_PDF.parent.parent / "vpbank" / "card_tariff_2026-10-19.pdf"
BIDV_PDF = TARIFF_PDF.parent.parent / "bidv" / "card_tariff_2026-10-29.pdf"


def test_column_labels_name_the_card_of_every_value() -> None:
    pages = read_pdf(VPB_PDF.read_bytes(), label_columns=True)
    rows = {r[0]: r for p in pages[1:2] for t in p.tables for r in t}
    supp = rows["2.2. Thẻ phụ"]
    assert supp[1:4] == ("[No.1] Không thu phí", "[MC2] 150.000 VND", "[Lady] Không thu phí")
    # a merged cell lists every card column it covers
    late = rows["12. Phí phạt trả chậm"]
    assert late[2].startswith("[Lady, StepUp, Gold Travel Miles/ Titanium Cashback] 6%")
    # letter-spaced and two-line headers come out whole; bold text isn't doubled
    page3 = " ".join(" | ".join(r) for t in pages[2].tables for r in t)
    assert "[Signature Travel Miles] 1.200.000 VND" in page3
    assert "[Diamond World/Diamond World Lady]" in page3
    assert "PPhhíí" not in page3


def test_tables_without_card_columns_are_left_alone() -> None:
    # Techcombank: cards are rows; labelling finds no card header and changes nothing
    plain = read_pdf(TARIFF_PDF.read_bytes())
    labelled = read_pdf(TARIFF_PDF.read_bytes(), label_columns=True)
    assert [p.render() for p in plain][:1] == [p.render() for p in labelled][:1]


def test_section_keeps_only_its_pages() -> None:
    pages = read_pdf(
        BIDV_PDF.read_bytes(),
        section=("1. BIỂU PHÍ DỊCH VỤ THẺ TÍN DỤNG", "2. BIỂU PHÍ DỊCH VỤ THẺ GHI NỢ"),
    )
    assert [p.number for p in pages] == [1, 2, 3, 4, 5, 6]
    with pytest.raises(DocumentError, match="not found"):
        read_pdf(BIDV_PDF.read_bytes(), section=("NO SUCH HEADING", None))
