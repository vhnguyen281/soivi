"""Fetch layer tests against a local HTTP server. No real network."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings
from core.enums import FetchMethod, SourceKind
from core.versioning import value_columns
from pipeline.adapters.base import BaseAdapter
from pipeline.fetch.fetchers import BrowserFetcher, Fetchers, HttpFetcher, PdfFetcher
from pipeline.fetch.polite import FetchError, PoliteHttp, RateLimiter, RobotsDisallowed
from pipeline.fetch.storage import MemoryStore, extension_for, snapshot_key
from pipeline.records import (
    CardPerkRecord,
    CardRewardRecord,
    CardTermsRecord,
    SavingsRateRecord,
)
from pipeline.registry import UnknownAdapter, get_adapter, load_adapters, register, unregister
from tests.http_fixture import FakeClock, FixtureServer, Reply

# --------------------------------------------------------------------------- robots.txt


def test_fetch_sends_user_agent(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/rates", body="<p>Lãi suất</p>")
    result = HttpFetcher(polite).fetch(http_server.url("/rates"))

    assert result.status == 200
    assert result.content_type == "text/html"
    assert "Lãi suất".encode() in result.content
    page = next(r for r in http_server.requests if r.path == "/rates")
    assert page.headers["User-Agent"] == "SoiviTest/1.0 (+mailto:test@example.com)"


def test_robots_disallow_blocks_without_requesting(
    http_server: FixtureServer, polite: PoliteHttp
) -> None:
    http_server.route("/private/fees", body="secret")
    with pytest.raises(RobotsDisallowed):
        HttpFetcher(polite).fetch(http_server.url("/private/fees"))
    assert http_server.hits("/private/fees") == 0


def test_robots_is_read_once_per_origin(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/a", body="a")
    http_server.route("/b", body="b")
    fetcher = HttpFetcher(polite)
    fetcher.fetch(http_server.url("/a"))
    fetcher.fetch(http_server.url("/b"))
    assert http_server.hits("/robots.txt") == 1


def test_robots_cache_expires(
    http_server: FixtureServer, polite: PoliteHttp, fake_clock: FakeClock
) -> None:
    http_server.route("/a", body="a")
    polite.allowed(http_server.url("/a"))
    fake_clock.now += polite.robots_ttl + 1
    polite.allowed(http_server.url("/a"))
    assert http_server.hits("/robots.txt") == 2


def test_missing_robots_means_allowed(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/robots.txt", Reply(404))
    assert polite.allowed(http_server.url("/anything"))


def test_broken_robots_means_blocked(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/robots.txt", Reply(500))
    assert not polite.allowed(http_server.url("/anything"))
    assert http_server.hits("/robots.txt") == polite.max_attempts  # it was retried


def test_robots_rules_for_our_agent(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/robots.txt", body="User-agent: SoiviTest\nDisallow: /\n")
    assert not polite.allowed(http_server.url("/rates"))


# --------------------------------------------------------------------------- rate limit


def test_same_host_waits_five_seconds(
    http_server: FixtureServer, polite: PoliteHttp, fake_clock: FakeClock
) -> None:
    http_server.route("/a", body="a")
    http_server.route("/b", body="b")
    fetcher = HttpFetcher(polite)
    fetcher.fetch(http_server.url("/a"))  # robots.txt, then /a: one wait
    fetcher.fetch(http_server.url("/b"))  # another wait

    assert fake_clock.sleeps == [5.0, 5.0]


def test_other_host_does_not_wait(
    http_server: FixtureServer, polite: PoliteHttp, fake_clock: FakeClock
) -> None:
    http_server.route("/a", body="a")
    polite.allowed(http_server.url("/a"))  # robots.txt for 127.0.0.1
    polite.allowed(http_server.url("/a", host="localhost"))  # first request to localhost
    assert fake_clock.sleeps == []


def test_rate_limiter_counts_elapsed_time() -> None:
    clock = FakeClock()
    limiter = RateLimiter(5.0, clock.clock, clock.sleep)
    limiter.wait("bank.vn")
    clock.now += 3.0
    assert limiter.wait("bank.vn") == pytest.approx(2.0)
    clock.now += 10.0
    assert limiter.wait("bank.vn") == 0.0


def test_delay_cannot_go_below_five_seconds() -> None:
    with pytest.raises(ValidationError):
        Settings(crawler_min_delay_seconds=1)


def test_user_agent_must_have_contact() -> None:
    with pytest.raises(ValueError, match="contact email"):
        PoliteHttp(settings=Settings(crawler_user_agent="SoiviBot/0.1"))


# --------------------------------------------------------------------------- retries


def test_retries_server_errors_with_backoff(
    http_server: FixtureServer, polite: PoliteHttp, fake_clock: FakeClock
) -> None:
    http_server.route("/flaky", Reply(503), Reply(502), Reply(200, "ok"))
    result = HttpFetcher(polite).fetch(http_server.url("/flaky"))

    assert result.content == b"ok"
    assert http_server.hits("/flaky") == 3
    # backoff 5 s then 10 s; the rate limiter's own 5 s waits come between them
    assert fake_clock.sleeps == [5.0, 5.0, 10.0]


def test_honours_retry_after(
    http_server: FixtureServer, polite: PoliteHttp, fake_clock: FakeClock
) -> None:
    http_server.route("/busy", Reply(429, headers={"Retry-After": "30"}), Reply(200, "ok"))
    HttpFetcher(polite).fetch(http_server.url("/busy"))
    assert 30.0 in fake_clock.sleeps


def test_gives_up_after_max_attempts(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/down", Reply(503))
    with pytest.raises(FetchError, match="HTTP 503"):
        HttpFetcher(polite).fetch(http_server.url("/down"))
    assert http_server.hits("/down") == 3


def test_client_errors_are_not_retried(http_server: FixtureServer, polite: PoliteHttp) -> None:
    with pytest.raises(FetchError, match="HTTP 404"):
        HttpFetcher(polite).fetch(http_server.url("/missing"))
    assert http_server.hits("/missing") == 1


def test_timeout_is_retried_then_fails(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/slow", Reply(200, "late", delay=1.0))  # client timeout is 0.5 s
    with pytest.raises(FetchError, match="Timeout"):
        HttpFetcher(polite).fetch(http_server.url("/slow"))
    assert http_server.hits("/slow") == 3


def test_follows_redirects(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/old", Reply(301, headers={"Location": "/new"}))
    http_server.route("/new", body="moved")
    result = HttpFetcher(polite).fetch(http_server.url("/old"))
    assert result.final_url.endswith("/new")
    assert result.content == b"moved"


# --------------------------------------------------------------------------- fetchers


PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_pdf_fetcher_accepts_pdf(http_server: FixtureServer, polite: PoliteHttp) -> None:
    # Banks often serve PDFs with a generic content type.
    http_server.route(
        "/fees.pdf", Reply(200, PDF_BYTES, headers={"Content-Type": "application/octet-stream"})
    )
    result = PdfFetcher(polite).fetch(http_server.url("/fees.pdf"))
    assert result.content_type == "application/pdf"


def test_pdf_fetcher_rejects_html(http_server: FixtureServer, polite: PoliteHttp) -> None:
    http_server.route("/fees.pdf", body="<html>Not found</html>")
    with pytest.raises(FetchError, match="did not return a PDF"):
        PdfFetcher(polite).fetch(http_server.url("/fees.pdf"))


def test_fetchers_pick_by_method(polite: PoliteHttp) -> None:
    fetchers = Fetchers(polite)
    assert isinstance(fetchers.for_method(FetchMethod.HTTP), HttpFetcher)
    assert isinstance(fetchers.for_method(FetchMethod.PDF), PdfFetcher)
    assert isinstance(fetchers.for_method(FetchMethod.OCR), HttpFetcher)
    assert isinstance(fetchers.for_method(FetchMethod.BROWSER), BrowserFetcher)
    assert fetchers._browser_fetcher is not None
    assert fetchers._browser_fetcher._browser is None  # nothing launched until used


def _chromium_installed() -> bool:
    """True if the headless Chromium build this Playwright version expects is installed.

    Reads Playwright's browsers.json instead of starting Playwright (which is slow).
    """
    import json
    import os

    import playwright

    manifest = Path(playwright.__file__).parent / "driver/package/browsers.json"
    try:
        browsers = json.loads(manifest.read_text())["browsers"]
        revision = next(b["revision"] for b in browsers if b["name"] == "chromium-headless-shell")
    except (OSError, KeyError, StopIteration, ValueError):
        return False
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")]
    roots += [
        str(Path.home() / "Library/Caches/ms-playwright"),
        str(Path.home() / ".cache/ms-playwright"),
    ]
    return any(
        root and (Path(root) / f"chromium_headless_shell-{revision}").exists() for root in roots
    )


@pytest.mark.skipif(not _chromium_installed(), reason="Playwright Chromium not installed")
def test_browser_fetcher_runs_javascript(
    http_server: FixtureServer, polite: PoliteHttp, fake_clock: FakeClock
) -> None:
    page = (
        "<html><body><div id='t'></div>"
        "<script>document.getElementById('t').textContent = 'Lãi suất 5,90%';</script>"
        "</body></html>"
    )
    http_server.route("/js", body=page)
    fetcher = BrowserFetcher(polite, wait_until="load")
    try:
        result = fetcher.fetch(http_server.url("/js"))
        waited = fetcher.fetch(http_server.url("/js"), wait_for="Lãi suất 5,90%")
        assert "Lãi suất 5,90%" in waited.content.decode()
        with pytest.raises(FetchError, match="did not appear"):
            fetcher.fetch(http_server.url("/js"), wait_for="Lãi suất huy động")
        with pytest.raises(RobotsDisallowed):
            fetcher.fetch(http_server.url("/private/x"))
    finally:
        fetcher.close()

    assert "Lãi suất 5,90%" in result.content.decode()
    assert result.content_type == "text/html"
    page_request = next(r for r in http_server.requests if r.path == "/js")
    assert page_request.headers["User-Agent"].startswith("SoiviTest/1.0")
    assert http_server.hits("/private/x") == 0


# --------------------------------------------------------------------------- storage


def test_snapshot_key_layout() -> None:
    at = dt.datetime(2026, 10, 26, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=7)))
    key = snapshot_key("ACB", "savings_rate_page", at, "ab" * 32, "text/html")
    # 23:30 in Vietnam is 16:30 UTC on the same day
    assert key == f"ACB/savings_rate_page/2026-10-26/{'ab' * 32}.html"


@pytest.mark.parametrize(
    ("content_type", "ext"),
    [("text/html", "html"), ("application/pdf", "pdf"), (None, "bin"), ("IMAGE/PNG", "png")],
)
def test_extension_for(content_type: str | None, ext: str) -> None:
    assert extension_for(content_type) == ext


def test_memory_store_round_trip() -> None:
    store = MemoryStore()
    store.put("k", b"data", "text/plain")
    assert store.exists("k") and store.get("k") == b"data"
    assert not store.exists("other")


# --------------------------------------------------------------------------- records


def test_records_match_db_columns() -> None:
    def fields(model: type) -> set[str]:
        return set(model.model_fields) - set(model.identity_fields) - set(model.provenance_fields)

    assert fields(SavingsRateRecord) == set(SavingsRateRecord.table.__version_key__) - {
        "institution_id"
    } | set(value_columns(SavingsRateRecord.table))
    for record in (CardTermsRecord, CardRewardRecord, CardPerkRecord):
        db = set(record.table.__version_key__) - {"card_product_id"}
        assert fields(record) == db | set(value_columns(record.table)), record.__name__


def savings(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "product_name": "Tiết kiệm Online",
        "channel": "online",
        "term_months": 12,
        "interest_payment": "end",
        "rate_pct": "5.90",
    }
    data.update(overrides)
    return data


def test_savings_record_parses_strings_to_decimal() -> None:
    r = SavingsRateRecord.model_validate(savings())
    assert r.rate_pct == Decimal("5.90")
    assert r.min_amount_vnd == 0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"rate_pct": 5.9}, "not float"),
        ({"rate_pct": "150"}, "less than or equal to 100"),
        ({"term_months": -1}, "greater than or equal to 0"),
        ({"min_amount_vnd": "1000"}, "valid integer"),
        ({"channel": "branch"}, "Input should be"),
        ({"bonus": "1"}, "Extra inputs are not permitted"),
        ({"product_name": "  "}, "at least 1 character"),
    ],
)
def test_savings_record_rejects_bad_values(override: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SavingsRateRecord.model_validate(savings(**override))


def test_reward_record_mirrors_db_check() -> None:
    base = {"card_name": "Ví Dụ Cashback", "network": "visa", "category": "all"}
    CardRewardRecord.model_validate({**base, "reward_type": "cashback", "rate_pct": "1.0"})
    with pytest.raises(ValidationError, match="cashback rewards need rate_pct"):
        CardRewardRecord.model_validate({**base, "reward_type": "cashback"})
    with pytest.raises(ValidationError, match="points_per_spend"):
        CardRewardRecord.model_validate({**base, "reward_type": "points"})


# --------------------------------------------------------------------------- registry


class _Dummy(BaseAdapter):
    name = "dummy_registry_test"
    institution = "X"
    source_kind = SourceKind.SAVINGS_RATE_PAGE

    @classmethod
    def parse_content(cls, content: bytes):  # type: ignore[no-untyped-def]
        return []


def test_registry_round_trip() -> None:
    register(_Dummy)
    try:
        assert get_adapter("dummy_registry_test") is _Dummy
        register(_Dummy)  # registering the same class again is fine

        class Other(_Dummy):
            pass

        with pytest.raises(ValueError, match="is used by"):
            register(Other)
    finally:
        unregister("dummy_registry_test")
    with pytest.raises(UnknownAdapter):
        get_adapter("dummy_registry_test")


def test_load_adapters_imports_package() -> None:
    load_adapters()  # must not fail even with no real adapters yet
