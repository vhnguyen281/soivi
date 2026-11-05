"""Matching institutions by name and alias (data/seeds/institution_aliases.csv)."""

import csv
from pathlib import Path

import pytest

from pipeline.news.institutions import (
    ALIASES_FILE,
    InstitutionMatcher,
    normalize,
    read_alias_file,
)

SEEDS = Path(__file__).resolve().parents[2] / "data" / "seeds"


def institutions() -> list[tuple[str, str]]:
    with (SEEDS / "institutions.csv").open(encoding="utf-8", newline="") as f:
        return [(r["short_name"], r["legal_name_vi"]) for r in csv.DictReader(f)]


@pytest.fixture(scope="module")
def matcher() -> InstitutionMatcher:
    return InstitutionMatcher.from_institutions(institutions(), read_alias_file())


def test_alias_file_only_names_seeded_institutions() -> None:
    known = {s for s, _ in institutions()}
    rows = read_alias_file(ALIASES_FILE)
    assert rows and {s for s, _ in rows} <= known
    assert len(rows) == len(set(rows))  # no duplicates


@pytest.mark.parametrize(
    "text", ["VCB", "Vietcombank", "Ngân hàng TMCP Ngoại thương", "NGÂN HÀNG TMCP NGOẠI THƯƠNG"]
)
def test_brief_examples_find_vietcombank(matcher: InstitutionMatcher, text: str) -> None:
    assert matcher.find(f"{text} điều chỉnh lãi suất") == ["VIETCOMBANK"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ngân hàng TMCP Ngoại thương Việt Nam tăng lãi suất", ["VIETCOMBANK"]),
        ("SACOMBANK củng cố nền tảng", ["SACOMBANK"]),
        ("Fitch nâng xếp hạng tín nhiệm TCB lên BB", ["TECHCOMBANK"]),
        ("Nam A Bank ghi dấu ấn tại AEF 2026", ["NAMABANK"]),
        ("Nam Á Bank tăng lãi suất", ["NAMABANK"]),
        ("VCB Neo ra mắt thẻ mới", ["VCBNEO"]),  # the longer name wins
        ("Ngân hàng Sài Gòn - Hà Nội giảm lãi suất", ["SHB"]),  # not SCB
        ("Ngân hàng Sài Gòn Công Thương", ["SAIGONBANK"]),
        ("Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm", ["SCB"]),
        ("Shinhan Finance và Shinhan Bank", ["SHINHANFINANCE", "SHINHANBANK"]),
        ("tại MB, VPBank, Techcombank, Sacombank", ["MB", "VPBANK", "TECHCOMBANK", "SACOMBANK"]),
        ("HSBC (Việt Nam)", ["HSBC"]),
    ],
)
def test_names_and_aliases(matcher: InstitutionMatcher, text: str, expected: list[str]) -> None:
    assert matcher.find(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "vcb tăng lãi suất",  # tickers only in capitals
        "Giám đốc tăng trưởng nói về thị trường",
        "ABB và EIB ký thoả thuận",  # ABB (the company), EIB (European Investment Bank)
        "Mbappé ghi bàn",
        "MBVX không phải là ngân hàng",
        "Ngân hàng nhà nước điều hành lãi suất",
    ],
)
def test_no_false_matches(matcher: InstitutionMatcher, text: str) -> None:
    assert matcher.find(text) == []


def test_order_of_first_mention_across_title_and_summary(matcher: InstitutionMatcher) -> None:
    assert matcher.find("BIDV và ACB", "Trong khi đó Vietcombank và BIDV...") == [
        "BIDV",
        "ACB",
        "VIETCOMBANK",
    ]


def test_normalize() -> None:
    assert normalize("Ngân hàng TMCP Đông Á (DongA Bank)") == "Ngan hang TMCP Dong A DongA Bank"
    assert normalize(None) == ""


def test_names_for_prompt(matcher: InstitutionMatcher) -> None:
    names = matcher.names_for("VIETCOMBANK")
    assert "Vietcombank" in names and "VCB" in names
    assert names[0] == "Ngân hàng TMCP Ngoại thương Việt Nam"
    assert "Ngân hàng TMCP Ngoại thương" in names and "VIETCOMBANK" not in names
