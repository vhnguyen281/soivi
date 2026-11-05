"""Techcombank savings adapter, against the PDF and listing saved on 2026-10-26."""

import datetime as dt
import json
from decimal import Decimal

import pytest

from core.enums import Channel
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.techcombank import TechcombankSavings, _section_rows, find_document_url
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import fixture_bytes

PDF = fixture_bytes("techcombank", "savings_2026-10-26.pdf")
LISTING = fixture_bytes("techcombank", "document_list_2026-10-26.json")
B = 1_000_000_000


@pytest.fixture(scope="module")
def records() -> dict[tuple[str, int, int, int], SavingsRateRecord]:
    parsed: list[SavingsRateRecord] = TechcombankSavings.parse_content(PDF)  # type: ignore[assignment]
    return {(r.product_name, r.term_months, r.term_days, r.min_amount_vnd): r for r in parsed}


@pytest.mark.parametrize(
    ("product", "months", "days", "tier", "rate"),
    [
        ("Tiết kiệm Phát Lộc", 1, 0, 0, "4.05"),
        ("Tiết kiệm Phát Lộc", 1, 0, 3 * B, "4.15"),
        ("Tiết kiệm Phát Lộc", 6, 0, 0, "5.55"),
        ("Tiết kiệm Phát Lộc", 12, 0, 0, "5.75"),
        ("Tiết kiệm Phát Lộc", 12, 0, 1 * B, "5.75"),
        ("Tiết kiệm Phát Lộc", 12, 0, 3 * B, "5.85"),
        ("Tiết kiệm Phát Lộc", 36, 0, 0, "4.85"),
        ("Tiền gửi Phát Lộc Online", 0, 0, 0, "0.05"),
        ("Tiền gửi Phát Lộc Online", 0, 7, 0, "0.50"),
        ("Tiền gửi Phát Lộc Online", 12, 0, 0, "6.25"),
        ("Tiền gửi Phát Lộc Online", 25, 0, 0, "5.35"),
        ("Tiền gửi Rút gốc linh hoạt", 12, 0, 0, "5.65"),
        ("Tiền gửi Rút gốc linh hoạt", 15, 0, 3 * B, "4.85"),
        ("Tiền gửi Rút gốc linh hoạt Online", 6, 0, 0, "6.05"),
    ],
)
def test_exact_rates(
    records: dict[tuple[str, int, int, int], SavingsRateRecord],
    product: str,
    months: int,
    days: int,
    tier: int,
    rate: str,
) -> None:
    assert records[(product, months, days, tier)].rate_pct == Decimal(rate)


def test_counts_and_fields(records: dict[tuple[str, int, int, int], SavingsRateRecord]) -> None:
    by_product: dict[str, int] = {}
    for (product, *_), r in records.items():
        by_product[product] = by_product.get(product, 0) + 1
        assert r.effective_from == dt.date(2026, 10, 24)
    # terms x 3 amount tiers (normal customers only)
    assert by_product == {
        "Tiết kiệm Phát Lộc": 36 * 3,  # 1M..36M
        "Tiền gửi Phát Lộc Online": 23 * 3,  # KKH, 1-3W, 1M..15M, 18, 19, 20, 24, 25, 36
        "Tiền gửi Rút gốc linh hoạt": 16 * 3,  # KKH row has no rate
        "Tiền gửi Rút gốc linh hoạt Online": 16 * 3,
    }
    assert records[("Tiền gửi Phát Lộc Online", 0, 7, 0)].conditions_text == (
        "Áp dụng cho kỳ hạn 1-3 tuần"
    )
    assert records[("Tiền gửi Phát Lộc Online", 1, 0, 0)].channel == Channel.ONLINE
    assert records[("Tiết kiệm Phát Lộc", 1, 0, 0)].channel == Channel.COUNTER


def test_finds_current_pdf_in_listing() -> None:
    assert find_document_url(LISTING) == (
        "https://techcombank.com/content/dam/techcombank/public-site/documents/"
        "tcb-bieu-lai-suat-tien-gui-tiet-kiem-tien-gui-co-ky-han-20261024.pdf"
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["data"].pop("listViewDocumentFragmentList"), "unexpected shape"),
        (lambda d: d["data"]["listViewDocumentFragmentList"]["items"].pop(6), "found 0"),
        (
            lambda d: d["data"]["listViewDocumentFragmentList"]["items"].append(
                d["data"]["listViewDocumentFragmentList"]["items"][6]
            ),
            "found 2",
        ),
        (
            lambda d: d["data"]["listViewDocumentFragmentList"]["items"][6]["documentPath"].update(
                _publishUrl="https://evil.example/x.pdf"
            ),
            "no techcombank.com PDF",
        ),
    ],
)
def test_listing_changes_raise(change, message: str) -> None:  # type: ignore[no-untyped-def]
    data = json.loads(LISTING)
    change(data)
    with pytest.raises(AdapterBroken, match=message):
        find_document_url(json.dumps(data).encode())


# --------------------------------------------------------------------------- layout changes


def lines_of(text: str) -> list[str]:
    return text.splitlines()


SECTION = """TIẾT KIỆM PHÁT LỘC TẠI QUẦY
PHAT LOC SAVINGS AT COUNTER
KỲ HẠN
PRIVATE PRIORITY INSPIRE KH THƯỜNG / NORMAL CUSTOMER
≥3B 1 - 3B <1B ≥3B 1 - 3B <1B ≥3B 1 - 3B <1B ≥3B 1 - 3B <1B
1M 4.40 4.30 4.30 4.30 4.20 4.20 4.15 4.05 4.05 4.15 4.05 4.05
12M 6.10 6.00 6.00 6.00 5.90 5.90 5.85 5.75 5.75 5.85 5.75 5.75
NEXT SECTION"""


def test_section_rows_reads_until_next_heading() -> None:
    rows = _section_rows(lines_of(SECTION), "TIẾT KIỆM PHÁT LỘC TẠI QUẦY")
    assert list(rows) == ["1M", "12M"]
    assert rows["12M"][-1] == Decimal("5.75")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            SECTION.replace(
                "≥3B 1 - 3B <1B ≥3B 1 - 3B <1B ≥3B", "≥5B 1 - 5B <1B ≥3B 1 - 3B <1B ≥3B"
            ),
            "amount-tier header",
        ),
        (SECTION.replace("TIẾT KIỆM PHÁT LỘC TẠI QUẦY", "TIẾT KIỆM AN LỘC"), "found 0 times"),
        (
            SECTION.replace(
                "1M 4.40 4.30 4.30 4.30 4.20 4.20 4.15 4.05 4.05 4.15 4.05 4.05", "1M 4,40"
            ),
            "no rate rows",
        ),
        (SECTION.replace("12M 6.10", "1M 6.10"), "appears twice"),
    ],
    ids=["tiers", "heading", "format", "duplicate"],
)
def test_section_changes_raise(text: str, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        _section_rows(lines_of(text), "TIẾT KIỆM PHÁT LỘC TẠI QUẦY")


def test_not_a_pdf_raises() -> None:
    with pytest.raises(AdapterBroken, match="not a PDF"):
        TechcombankSavings.parse_content(b"<html>404</html>")


def test_other_pdf_raises() -> None:
    from tests.adapters.conftest import FIXTURES

    other = (FIXTURES / "techcombank" / "savings_2026-10-26.pdf").read_bytes()
    truncated = other[: len(other) // 3]
    with pytest.raises(AdapterBroken):
        TechcombankSavings.parse_content(truncated)
