"""HDBank savings adapter, against the listing page and PDF saved on 2026-10-26."""

from decimal import Decimal

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.hdbank import SECTIONS, HdbankSavings, _section, latest_pdf_url
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PDF = fixture_bytes("hdbank", "savings_2026-10-26.pdf")
LISTING = fixture_bytes("hdbank", "savings_2026-10-26.html").decode()
END, UPFRONT, MONTHLY, QUARTERLY = (
    InterestPayment.END,
    InterestPayment.UPFRONT,
    InterestPayment.MONTHLY,
    InterestPayment.QUARTERLY,
)
COUNTER = "Tiết kiệm có kỳ hạn thông thường"
ONLINE = "Tiết kiệm Online"
TERM = "Tiền gửi có kỳ hạn"
CD = "Chứng chỉ tiền gửi"
TY = 1_000_000_000

Key = tuple[str, int, int, int, InterestPayment]


@pytest.fixture(scope="module")
def records() -> dict[Key, SavingsRateRecord]:
    parsed: list[SavingsRateRecord] = HdbankSavings.parse_content(PDF)  # type: ignore[assignment]
    return {
        (r.product_name, r.term_months, r.term_days, r.min_amount_vnd, r.interest_payment): r
        for r in parsed
    }


@pytest.mark.parametrize(
    ("product", "months", "days", "amount", "payment", "rate"),
    [
        (COUNTER, 0, 1, 0, END, "0.50"),  # 01 ngày
        (COUNTER, 0, 21, 0, END, "0.50"),  # 03 tuần
        (COUNTER, 1, 0, 0, END, "3.50"),
        (COUNTER, 1, 0, 0, UPFRONT, "3.40"),
        (COUNTER, 6, 0, 0, QUARTERLY, "4.80"),
        (COUNTER, 12, 0, 0, END, "5.20"),  # LS12 loại 2
        (COUNTER, 12, 0, 500 * TY, END, "7.20"),  # LS12 loại 1
        (COUNTER, 13, 0, 500 * TY, END, "7.10"),  # LS13 loại 1
        (COUNTER, 24, 0, 0, MONTHLY, "4.60"),
        (ONLINE, 1, 0, 0, END, "4.20"),
        (ONLINE, 12, 0, 0, END, "5.30"),
        (ONLINE, 18, 0, 0, END, "5.60"),
        (ONLINE, 36, 0, 0, UPFRONT, "4.10"),
        (TERM, 0, 0, 0, END, "0.40"),  # TK KKH
        (TERM, 12, 0, 0, QUARTERLY, "5.00"),
        (CD, 1, 0, 0, END, "3.45"),
        (CD, 13, 0, 0, END, "5.40"),
    ],
)
def test_exact_rates(
    records: dict[Key, SavingsRateRecord],
    product: str,
    months: int,
    days: int,
    amount: int,
    payment: InterestPayment,
    rate: str,
) -> None:
    assert records[(product, months, days, amount, payment)].rate_pct == Decimal(rate)


def test_fields(records: dict[Key, SavingsRateRecord]) -> None:
    assert len(records) == 178
    for (product, *_), r in records.items():
        assert r.is_cd == (product == CD)
        assert r.channel == (Channel.ONLINE if product == ONLINE else Channel.COUNTER)
        assert r.effective_from is None  # the PDF states no date
    assert "500 tỷ" in (records[(COUNTER, 12, 0, 500 * TY, END)].conditions_text or "")
    # "loại 1" is end-of-term only
    assert (COUNTER, 12, 0, 500 * TY, UPFRONT) not in records
    # "-" cells are not stored: no quarterly option for 1 month
    assert (COUNTER, 1, 0, 0, QUARTERLY) not in records


def test_listing_picks_newest_deposit_pdf() -> None:
    assert latest_pdf_url(LISTING).endswith(
        "20261910BIEULAISUATTIENGUIKHACHHANGCANHANKHCNWEBSITEF2TD_1792402278333.pdf"
    )


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html>Đang tải…</html>", "no 'BIỂU LÃI SUẤT"),
        (
            LISTING.replace(
                "BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN 10-04-2026",
                "BIỂU LÃI SUẤT TIỀN GỬI KHÁCH HÀNG CÁ NHÂN 19-10-2026",
            ),
            "two deposit-rate PDFs",
        ),
        (
            LISTING.replace(
                "https://cdn.hdbank.com.vn/hdbank-file/document/2026191",
                "https://evil.example/2026191",
            ),
            "not an HDBank CDN PDF",
        ),
    ],
    ids=["empty", "same date twice", "foreign link"],
)
def test_listing_changes_raise(html: str, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        latest_pdf_url(html)


# --------------------------------------------------------------------------- layout changes

LINES = [
    "c. Tiết kiệm Online VNĐ:",
    "Cuối kỳ Trả lãi trước Hàng tháng Hàng quý",
    "01 tháng 4,20 4,10 - -",
    "03 tháng 4,30 4,20 4,20 -",
    "06 tháng 5,00 4,80 4,90 4,90",
    "12 tháng 5,30 4,90 5,10 5,10",
    "24 tháng 5,00 4,40 4,70 4,70",
    "36 tháng 5,00 4,10 4,60 4,70",
    "d. Lãi suất Tiền gửi tiết kiệm Online Vikki",
]
ONLINE_SPEC = SECTIONS[1]
TIERS = {12: (500 * TY, "x"), 13: (500 * TY, "x")}


def test_section_parses() -> None:
    assert len(_section(LINES, ONLINE_SPEC, TIERS)) == 2 + 3 + 4 + 4 + 4 + 4  # non-"-" cells


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda ls: ls.__setitem__(4, "06 tháng 5,00 4,80 4,90"), "3 values, expected 4"),
        (lambda ls: ls.__setitem__(5, "06 tháng 5,30 4,90 5,10 5,10"), "appears twice"),
        (lambda ls: ls.pop(5), r"terms missing \[12\]"),
        (lambda ls: ls.pop(0), "section heading missing"),
        (lambda ls: ls.__setitem__(2, "01 tháng 4,20% 4,10 - -"), r"terms missing \[1\]"),
    ],
    ids=["column dropped", "duplicate", "core term", "heading", "unparsed row"],
)
def test_section_changes_raise(change, message: str) -> None:  # type: ignore[no-untyped-def]
    lines = list(LINES)
    change(lines)
    with pytest.raises(AdapterBroken, match=message):
        _section(lines, ONLINE_SPEC, TIERS)


def test_other_documents_raise() -> None:
    with pytest.raises(AdapterBroken, match="not a PDF"):
        HdbankSavings.parse_content(b"<html/>")
    with pytest.raises(AdapterBroken, match="title missing"):
        HdbankSavings.parse_content(fixture_bytes("sacombank", "savings_2026-10-26.pdf"))
