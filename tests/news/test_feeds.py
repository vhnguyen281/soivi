"""Feed config and parsing, against feeds saved on 2026-10-28 (tests/fixtures/news/)."""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pipeline.news.feeds import (
    Feed,
    FeedError,
    canonical_url,
    load_config,
    parse,
    parse_html,
    title_key,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "news"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CONFIG = load_config()
SAVED = {
    "cafef-tai-chinh-ngan-hang": "cafef_tai-chinh-ngan-hang_2026-10-28.rss",
    "vnexpress-kinh-doanh": "vnexpress_kinh-doanh_2026-10-28.rss",
    "vietstock-ngan-hang": "vietstock_ngan-hang_2026-10-28.rss",
    "thoibaonganhang": "thoibaonganhang_rss-feed_2026-10-28.rss",
}


def entries(name: str) -> list:  # type: ignore[type-arg]
    return parse((FIXTURES / SAVED[name]).read_bytes(), CONFIG.get(name), TZ)


def utc(*args: int) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.UTC)


def test_config_lists_only_the_verified_feeds() -> None:
    assert [f.name for f in CONFIG.feeds] == list(SAVED)
    assert {f.publisher for f in CONFIG.feeds} == {
        "CafeF",
        "VnExpress",
        "Vietstock",
        "Thời báo Ngân hàng",
    }
    assert all(f.kind == "rss" and f.url.startswith("https://") for f in CONFIG.feeds)
    # Blocked by its firewall (403) on 2026-10-28: dropped, not worked around.
    assert not any("thitruongtaichinhtiente" in f.url for f in CONFIG.feeds)
    assert CONFIG.options.recheck_window_hours == 48
    assert CONFIG.options.llm_max_per_run == 30


def test_config_rejects_bad_feeds(tmp_path: Path) -> None:
    bad = tmp_path / "feeds.yaml"
    bad.write_text("feeds:\n  - {name: x, publisher: X, kind: rss, url: 'http://x.vn/rss'}\n")
    with pytest.raises(ValueError, match="https"):
        load_config(bad)
    bad.write_text("feeds:\n  - {name: x, publisher: X, kind: html, url: 'https://x.vn/'}\n")
    with pytest.raises(ValueError, match="link_pattern"):
        load_config(bad)


def test_every_saved_feed_parses_completely() -> None:
    counts = {name: len(entries(name)) for name in SAVED}
    assert counts == {
        "cafef-tai-chinh-ngan-hang": 50,
        "vnexpress-kinh-doanh": 60,
        "vietstock-ngan-hang": 20,
        "thoibaonganhang": 25,
    }
    for name in SAVED:
        for e in entries(name):
            assert e.title and e.url.startswith("http") and e.published_at is not None
            assert e.summary is None or "<" not in e.summary  # markup stripped


def test_vnexpress_item() -> None:
    first = entries("vnexpress-kinh-doanh")[0]
    assert first.title == "Nhà đầu tư cam kết rót hơn 16 tỷ USD vào 12 dự án ở TP HCM"
    assert first.url == (
        "https://vnexpress.net/nha-dau-tu-cam-ket-rot-hon-16-ty-usd-vao-12-du-an-o-tp-hcm-5137947.html"
    )
    assert first.published_at == utc(2026, 10, 28, 9, 35, 57)  # 16:35:57 +0700
    assert first.summary is not None and first.summary.startswith(
        "Các dự án được chấp thuận hoặc cấp phép đầu tư vào TP HCM"
    )


def test_cafef_two_digit_year() -> None:
    first = entries("cafef-tai-chinh-ngan-hang")[0]
    assert first.title.startswith("Techcombank và Masterise Group mang hòa nhạc")
    assert first.published_at == utc(2026, 10, 28, 10, 30)  # "Wed, 28 Oct 26 17:30:00 +0700"


def test_vietstock_escaped_description_and_http_links() -> None:
    first = entries("vietstock-ngan-hang")[0]
    assert first.title.startswith("SACOMBANK củng cố nền tảng")
    assert first.url.startswith("http://vietstock.vn/2026/10/sacombank-cung-co-nen-tang")
    assert first.summary is not None and first.summary.startswith(
        "Trong bối cảnh tập trung xử lý những tồn đọng từ quá khứ"
    )
    assert first.published_at == utc(2026, 10, 28, 9, 58, 32)


def test_thoibaonganhang_local_time_labelled_gmt() -> None:
    first = entries("thoibaonganhang")[0]
    # The feed says "Wed, 28 Oct 2026 17:40:13 GMT" but means Vietnam time.
    assert first.published_at == utc(2026, 10, 28, 10, 40, 13)
    assert first.title == (
        "Vinhomes Star City ra mắt The Victoria nâng tầm thị trường căn hộ cao tầng Thanh Hóa"
    )
    plain = Feed("x", "X", "rss", "https://x.vn/rss")
    raw = parse((FIXTURES / SAVED["thoibaonganhang"]).read_bytes(), plain, TZ)[0]
    assert raw.published_at == utc(2026, 10, 28, 17, 40, 13)  # 7 h in the future


def test_section_page_fallback() -> None:
    feed = Feed(
        "tbnh-ngan-hang",
        "Thời báo Ngân hàng",
        "html",
        "https://thoibaonganhang.vn/ngan-hang",
        link_pattern=r"https://thoibaonganhang\.vn/[a-z0-9-]+-\d+\.html",
    )
    found = parse_html((FIXTURES / "thoibaonganhang_ngan-hang_2026-10-28.html").read_bytes(), feed)
    by_url = {e.url: e.title for e in found}
    assert len(found) >= 25
    assert len(by_url) == len(found)  # one entry per story, though linked twice
    assert by_url[
        "https://thoibaonganhang.vn/ocb-day-manh-phat-trien-so-hoa-gia-tang-loi-nhuan-189771.html"
    ] == ("OCB đẩy mạnh phát triển số hoá, gia tăng lợi nhuận")
    assert all(e.published_at is None and e.summary is None for e in found)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html><body>Access Denied</body></html>", "not valid XML|not an RSS"),
        (b"<rss version='2.0'><channel><title>x</title></channel></rss>", "no items"),
        (b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>", "not an RSS"),
        (
            b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]>'
            b"<rss><channel><item><title>&b;</title></item></channel></rss>",
            "not valid XML",
        ),
    ],
)
def test_unreadable_feeds_raise(body: bytes, message: str) -> None:
    with pytest.raises(FeedError, match=message):
        parse(body, CONFIG.feeds[0], TZ)


def test_items_without_title_or_web_link_are_skipped() -> None:
    body = (
        "<rss><channel>"
        "<item><title>Có link</title><link>https://x.vn/a.html#top</link></item>"
        "<item><title>Không link</title></item>"
        "<item><title>JS</title><link>javascript:alert(1)</link></item>"
        "<item><title></title><link>https://x.vn/b.html</link></item>"
        "<item><title>Chỉ guid</title><guid>https://x.vn/c.html</guid></item>"
        "</channel></rss>"
    ).encode()
    found = parse(body, CONFIG.feeds[0], TZ)
    assert [(e.title, e.url) for e in found] == [
        ("Có link", "https://x.vn/a.html"),
        ("Chỉ guid", "https://x.vn/c.html"),
    ]


def test_canonical_url_and_title_key() -> None:
    assert (
        canonical_url("HTTPS://CafeF.vn/a.chn?utm_source=rss&id=3&fbclid=x#top")
        == "https://cafef.vn/a.chn?id=3"
    )
    assert canonical_url("javascript:alert(1)") is None
    assert canonical_url("/relative") is None
    assert title_key("Lãi suất: VCB “tăng” mạnh!") == "lai suat vcb tang manh"
    assert title_key(" Lãi suất  VCB tăng mạnh ") == "lai suat vcb tang manh"
