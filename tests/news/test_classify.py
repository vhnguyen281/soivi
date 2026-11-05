"""Keyword classification: on real headlines from the saved feeds, plus edge cases."""

import csv
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.enums import NewsClassification, NewsDirection
from pipeline.news.classify import Classification, classify_keywords, direction_of
from pipeline.news.feeds import load_config, parse
from pipeline.news.institutions import InstitutionMatcher, read_alias_file

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "news"


@pytest.fixture(scope="module")
def matcher() -> InstitutionMatcher:
    with (ROOT / "data" / "seeds" / "institutions.csv").open(encoding="utf-8") as f:
        rows = [(r["short_name"], r["legal_name_vi"]) for r in csv.DictReader(f)]
    return InstitutionMatcher.from_institutions(rows, read_alias_file())


def kw(matcher: InstitutionMatcher, title: str, summary: str | None = None) -> Classification:
    result = classify_keywords(title, summary, matcher)
    assert result is not None, f"ambiguous: {title}"
    return result


def test_clear_rate_cut_from_vnexpress(matcher: InstitutionMatcher) -> None:
    c = kw(matcher, "SCB giảm lãi suất tiết kiệm xuống gần 0%")
    assert (c.category, c.institutions, c.direction) == (
        NewsClassification.RATE_CHANGE,
        ["SCB"],
        NewsDirection.DOWN,
    )
    assert c.about_rates and not c.about_card_fees and c.method == "keywords"
    assert c.triggers_recheck


@pytest.mark.parametrize(
    ("title", "category", "institutions", "direction"),
    [
        (
            "Techcombank tăng lãi suất huy động kỳ hạn 6 tháng",
            NewsClassification.RATE_CHANGE,
            ["TECHCOMBANK"],
            NewsDirection.UP,
        ),
        (
            "VPBank điều chỉnh biểu phí thẻ tín dụng từ 1/12",
            NewsClassification.CARD_CHANGE,
            ["VPBANK"],
            NewsDirection.UNKNOWN,
        ),
        (
            "ACB hạ phí thường niên thẻ tín dụng",
            NewsClassification.CARD_CHANGE,
            ["ACB"],
            NewsDirection.DOWN,
        ),
    ],
)
def test_clear_headlines(
    matcher: InstitutionMatcher,
    title: str,
    category: NewsClassification,
    institutions: list[str],
    direction: NewsDirection,
) -> None:
    c = kw(matcher, title)
    assert (c.category, c.institutions, c.direction) == (category, institutions, direction)


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm", None),  # verb not in the list
        ("Lãi suất ngày 28/10 tại Agribank, Vietcombank, BIDV, VietinBank", None),  # a table
        (  # lending: only the summary mentions rates
            "SACOMBANK giảm biên lợi nhuận cho vay, hỗ trợ doanh nghiệp tiếp cận vốn",
            "Sacombank giảm lãi suất cho vay đối với doanh nghiệp",
        ),
        ("Vietcombank giảm lãi suất tiết kiệm?", None),  # a question
        ("BIDV giảm lãi suất tiết kiệm theo chỉ đạo của NHNN", None),  # policy context
        ("Vietcombank: tăng trưởng tiền gửi, lãi suất tiết kiệm giữ nguyên", None),  # no change
    ],
)
def test_ambiguous_goes_to_llm(
    matcher: InstitutionMatcher, title: str, summary: str | None
) -> None:
    assert classify_keywords(title, summary, matcher) is None


def test_irrelevant_without_topic_words(matcher: InstitutionMatcher) -> None:
    c = kw(matcher, "Techcombank và Masterise Group mang hòa nhạc kinh điển Châu Âu")
    assert c.category is NewsClassification.IRRELEVANT and not c.relevant
    assert not c.triggers_recheck


def test_on_topic_but_no_institution_named(matcher: InstitutionMatcher) -> None:
    c = kw(matcher, "Lãi suất tiết kiệm giảm xuống gần 0% tại một ngân hàng")
    assert c.category is NewsClassification.RATE_CHANGE and c.institutions == []
    assert c.direction is NewsDirection.DOWN and not c.triggers_recheck
    other = kw(matcher, "Giảm lãi suất huy động chỉ là 'bánh vẽ'?")
    assert other.category is NewsClassification.OTHER
    assert other.as_json()["note"] == "no institution named"


def test_summary_alone_makes_it_relevant(matcher: InstitutionMatcher) -> None:
    c = classify_keywords("Ngân hàng ra mắt ứng dụng", "Khách hàng gửi tiết kiệm online", matcher)
    assert c is not None and c.category is NewsClassification.OTHER


@pytest.mark.parametrize(
    ("text", "direction"),
    [
        ("vcb tăng lãi suất", NewsDirection.UP),
        ("vcb giảm lãi suất", NewsDirection.DOWN),
        ("ngân hàng hạ lãi suất", NewsDirection.DOWN),
        ("tăng lãi suất kỳ ngắn, giảm kỳ dài", NewsDirection.UNKNOWN),
        ("tăng trưởng tín dụng, giảm lãi suất", NewsDirection.DOWN),
        ("quà tặng khi gửi tiết kiệm", NewsDirection.UNKNOWN),  # tặng is not tăng
        ("giám đốc nói về lãi suất", NewsDirection.UNKNOWN),  # giám is not giảm
        ("đầu tư hạ tầng", NewsDirection.UNKNOWN),
    ],
)
def test_direction(text: str, direction: NewsDirection) -> None:
    assert direction_of(text) is direction


def test_saved_feeds_keyword_outcome(matcher: InstitutionMatcher) -> None:
    """All 155 saved items: one clear bank rate change, 8 for the LLM (each names a bank)."""
    config = load_config()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    decided_changes, ambiguous = [], []
    for feed, name in [
        ("cafef-tai-chinh-ngan-hang", "cafef_tai-chinh-ngan-hang_2026-10-28.rss"),
        ("vnexpress-kinh-doanh", "vnexpress_kinh-doanh_2026-10-28.rss"),
        ("vietstock-ngan-hang", "vietstock_ngan-hang_2026-10-28.rss"),
        ("thoibaonganhang", "thoibaonganhang_rss-feed_2026-10-28.rss"),
    ]:
        for e in parse((FIXTURES / name).read_bytes(), config.get(feed), tz):
            c = classify_keywords(e.title, e.summary, matcher)
            if c is None:
                ambiguous.append(e.title)
                assert matcher.find(e.title, e.summary), e.title
            elif c.triggers_recheck:
                decided_changes.append((e.title, c.institutions))
    assert decided_changes == [("SCB giảm lãi suất tiết kiệm xuống gần 0%", ["SCB"])]
    assert len(ambiguous) == 8
    assert "Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm" in ambiguous
