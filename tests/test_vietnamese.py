import datetime as dt
from decimal import Decimal

import pytest

from pipeline.extract.vietnamese import (
    clean,
    find_effective_date,
    fold,
    parse_date,
    parse_rate,
    parse_term,
    parse_vnd,
)


def test_clean_and_fold() -> None:
    assert clean("  Lãi\xa0suất \n 12  tháng ") == "Lãi suất 12 tháng"
    assert fold("Không Kỳ Hạn") == "khong ky han"
    assert fold("Đồng") == "dong"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6,50%", Decimal("6.50")),
        ("6.5", Decimal("6.5")),
        ("6,5 %/năm", Decimal("6.5")),
        (" 0,1 ", Decimal("0.1")),
        ("5", Decimal("5")),
        ("4,75%/năm", Decimal("4.75")),
        ("-", None),
        ("", None),
        ("—", None),
    ],
)
def test_parse_rate(text: str, expected: Decimal | None) -> None:
    assert parse_rate(text) == expected


@pytest.mark.parametrize("text", ["abc", "6,5,0", "150", "5.12345"])
def test_parse_rate_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Không kỳ hạn", (0, 0)),
        ("KKH", (0, 0)),
        ("1 tuần", (0, 7)),
        ("3 Tuần", (0, 21)),
        ("7 ngày", (0, 7)),
        ("01 tháng", (1, 0)),
        ("1T", (1, 0)),
        ("12 Tháng", (12, 0)),
        ("Kỳ hạn 6 tháng", (6, 0)),
        ("1 năm", (12, 0)),
        ("36 tháng", (36, 0)),
    ],
)
def test_parse_term(text: str, expected: tuple[int, int]) -> None:
    assert parse_term(text) == expected


@pytest.mark.parametrize("text", ["", "dài hạn", "0 tháng", "30 ngày", "tháng 12"])
def test_parse_term_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_term(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500 triệu", 500_000_000),
        ("1 tỷ", 1_000_000_000),
        ("1,5 tỷ", 1_500_000_000),
        ("500.000.000", 500_000_000),
        ("500,000,000 VND", 500_000_000),
        ("100 nghìn", 100_000),
        ("1.000.000 đồng", 1_000_000),
        ("0", 0),
    ],
)
def test_parse_vnd(text: str, expected: int) -> None:
    assert parse_vnd(text) == expected


@pytest.mark.parametrize("text", ["nhiều tiền", "1,2345678 tỷ x", "5.00"])
def test_parse_vnd_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_vnd(text)


def test_parse_date() -> None:
    assert parse_date("01/10/2026") == dt.date(2026, 10, 1)
    assert parse_date("Áp dụng từ 1-10-2026") == dt.date(2026, 10, 1)
    assert parse_date("ngày 05 tháng 9 năm 2026") == dt.date(2026, 9, 5)
    with pytest.raises(ValueError):
        parse_date("không có ngày")


def test_find_effective_date() -> None:
    text = "Biểu lãi suất (Cập nhật 20/10/2026). Hiệu lực từ ngày 15/10/2026. Ghi chú..."
    assert find_effective_date(text) == dt.date(2026, 10, 15)
    assert find_effective_date("Áp dụng từ ngày 01 tháng 11 năm 2026") == dt.date(2026, 11, 1)
    assert find_effective_date("Cập nhật 20/10/2026") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Không kỳ hạn", (0, 0)),
        ("12 tháng", (12, 12)),
        ("Từ 1 tháng đến dưới 2 tháng", (1, 1)),
        ("Từ 24 tháng đến dưới 36 tháng", (24, 35)),
        ("Trên 12 tháng đến 13 tháng", (13, 13)),
        ("Trên 13 tháng đến dưới 18 tháng", (14, 17)),
        ("Từ 6 tháng đến 9 tháng", (6, 9)),
        ("Dưới 1 tháng", (None, 0)),
        ("Trên 36 tháng", (37, None)),
        ("Từ 60 tháng trở lên", (60, None)),
    ],
)
def test_parse_term_band(text: str, expected: tuple[int | None, int | None]) -> None:
    from pipeline.extract.vietnamese import parse_term_band

    assert parse_term_band(text) == expected


@pytest.mark.parametrize("text", ["Trên 12 tháng đến dưới 13 tháng", "Linh hoạt", "1 tuần"])
def test_parse_term_band_rejects(text: str) -> None:
    from pipeline.extract.vietnamese import parse_term_band

    with pytest.raises(ValueError):
        parse_term_band(text)


def test_extract_tables() -> None:
    from pipeline.extract.html_tables import extract_tables

    html = """<h2>LÃI SUẤT</h2><table><thead>
    <tr><th>Kỳ hạn</th><th colspan="2">VND</th></tr></thead>
    <tbody><tr><td>12 tháng</td><td>5,4<!-- --> %</td><td>x</td></tr>
    <tr><td>1&nbsp;tháng<br>online</td><td>2,1 %</td><td></td></tr></tbody></table>
    <script>var t = "<table><tr><td>no</td></tr></table>";</script>"""
    [table] = extract_tables(html)
    assert table.caption == "LÃI SUẤT"
    assert table.rows == [
        ["Kỳ hạn", "VND", "VND"],
        ["12 tháng", "5,4 %", "x"],
        ["1 tháng online", "2,1 %", ""],
    ]


def test_extract_tables_expands_rowspan() -> None:
    from pipeline.extract.html_tables import extract_tables

    html = """<table><thead><tr><th rowspan="2">Kỳ hạn</th><th colspan="2">VND</th></tr>
    <tr><th>Cuối kỳ</th><th>Hàng tháng</th></tr></thead><tbody>
    <tr><td>1T</td><td rowspan="2">4,00</td><td>3,95</td></tr>
    <tr><td>2T</td><td>3,90</td></tr>
    <tr><td>3T</td><td>4,20</td><td>4,15</td></tr></tbody></table>"""
    [table] = extract_tables(html)
    assert table.rows == [
        ["Kỳ hạn", "VND", "VND"],
        ["Kỳ hạn", "Cuối kỳ", "Hàng tháng"],
        ["1T", "4,00", "3,95"],
        ["2T", "4,00", "3,90"],
        ["3T", "4,20", "4,15"],
    ]


def test_rowspan_does_not_cross_row_groups() -> None:
    from pipeline.extract.html_tables import extract_tables

    html = """<table><thead><tr><th rowspan="2">Kỳ hạn</th><th>VND</th></tr></thead>
    <tbody><tr><td>1T</td><td>4,00</td></tr></tbody></table>"""
    [table] = extract_tables(html)
    assert table.rows == [["Kỳ hạn", "VND"], ["1T", "4,00"]]
