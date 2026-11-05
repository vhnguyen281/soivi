"""News runs end to end: saved feeds on a local HTTP server -> news_item rows ->
classification -> immediate re-check of the bank's own source -> news URL on the
review task. No real network, no API key, no MinIO."""

import datetime as dt
import re
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    FetchMethod,
    InstitutionType,
    NewsClassification,
    NewsDirection,
    SourceKind,
    VersionStatus,
)
from core.models import (
    Institution,
    NewsFetch,
    NewsItem,
    PipelineRun,
    ReviewTask,
    SavingsRate,
    Snapshot,
    Source,
)
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import PoliteHttp
from pipeline.fetch.storage import MemoryStore
from pipeline.monitor import daily_summary
from pipeline.news.classify import Classification
from pipeline.news.feeds import Feed, FeedConfig, NewsOptions
from pipeline.news.institutions import InstitutionMatcher, read_alias_file
from pipeline.news.llm import LLMError
from pipeline.news.service import NewsRunResult, news_due, run_news
from pipeline.notify import PrintNotifier
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register, unregister
from pipeline.scheduler import tick
from tests.http_fixture import FixtureServer, Reply

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "news"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = dt.datetime(2026, 10, 28, 11, 0, tzinfo=dt.UTC)  # 18:00 in Vietnam, after the feeds
VNEXPRESS = (FIXTURES / "vnexpress_kinh-doanh_2026-10-28.rss").read_bytes()
VIETSTOCK = (FIXTURES / "vietstock_ngan-hang_2026-10-28.rss").read_bytes()
RSS = {"Content-Type": "application/xml; charset=utf-8"}
SCB_URL = "https://vnexpress.net/scb-giam-lai-suat-tiet-kiem-xuong-gan-0-5137507.html"
PAGE = "<table id='rates'><tr><td>12</td><td>0,50</td></tr></table>"


class ScbSavings(BaseAdapter):
    """Stands in for a real SCB adapter: <tr><td>term</td><td>rate</td></tr>."""

    name = "test_scb_savings"
    institution = "SCB"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        rows = re.findall(r"<td>(\d+)</td><td>([\d,]+)</td>", content.decode())
        if not rows:
            raise AdapterBroken("rates table not found")
        return [
            SavingsRateRecord(
                product_name="Tiết kiệm thường",
                channel="counter",
                term_months=int(term),
                interest_payment="end",
                rate_pct=Decimal(rate.replace(",", ".")),
            )
            for term, rate in rows
        ]


@pytest.fixture(autouse=True)
def adapter() -> Iterator[None]:
    register(ScbSavings)
    yield
    unregister(ScbSavings.name)


@pytest.fixture
def scb(db: Session) -> Institution:
    inst = Institution(
        legal_name_vi="Ngân hàng TMCP Sài Gòn",
        short_name="SCB",
        type=InstitutionType.JOINT_STOCK_BANK,
    )
    db.add(inst)
    db.flush()
    return inst


@pytest.fixture
def source(db: Session, scb: Institution, http_server: FixtureServer) -> Source:
    http_server.route("/scb/lai-suat", body=PAGE)
    src = Source(
        institution_id=scb.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        url=http_server.url("/scb/lai-suat"),
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name=ScbSavings.name,
    )
    db.add(src)
    db.flush()
    return src


@pytest.fixture
def matcher(scb: Institution) -> InstitutionMatcher:
    return InstitutionMatcher.from_institutions(
        [("SCB", scb.legal_name_vi), ("VIETCOMBANK", "Ngân hàng TMCP Ngoại thương Việt Nam")],
        read_alias_file(),
    )


def feed(server: FixtureServer, name: str, path: str, publisher: str = "VnExpress") -> Feed:
    return Feed(name, publisher, "rss", server.url(path))


@pytest.fixture
def config(http_server: FixtureServer) -> FeedConfig:
    http_server.route("/rss/kinh-doanh.rss", Reply(200, VNEXPRESS, RSS))
    return FeedConfig((feed(http_server, "vnexpress-kinh-doanh", "/rss/kinh-doanh.rss"),))


@pytest.fixture
def factory(db: Session) -> Callable[[], Session]:
    db.commit()  # fixtures visible to the run's own sessions (still inside the test txn)
    conn = db.connection()
    assert isinstance(conn, Connection)
    return lambda: Session(bind=conn, join_transaction_mode="create_savepoint")


def run(
    factory: Callable[[], Session],
    polite: PoliteHttp,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    *,
    now: dt.datetime = NOW,
    **kw: Any,
) -> NewsRunResult:
    return run_news(
        factory,
        Fetchers(polite),
        MemoryStore(),
        config,
        tz=TZ,
        matcher=matcher,
        now=lambda: now,
        **kw,
    )


class FakeLLM:
    """Says 'SCB cut deposit rates' for headlines naming SCB, 'no change' otherwise."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.titles: list[str] = []
        self.fail_after = fail_after

    def __call__(self, title: str, summary: str | None, publisher: str) -> Classification:
        if self.fail_after is not None and len(self.titles) >= self.fail_after:
            raise LLMError("Anthropic API error 529: overloaded")
        self.titles.append(title)
        if "SCB" in title:
            return Classification(True, False, ["SCB"], NewsDirection.DOWN, "llm")
        return Classification(False, False, [], NewsDirection.UNKNOWN, "llm")


# --------------------------------------------------------------------------- tests


def test_news_triggers_recheck_and_lands_on_the_review_task(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    source: Source,
) -> None:
    result = run(factory, polite, config, matcher)

    assert [str(f) for f in result.feeds] == ["[ok] vnexpress-kinh-doanh: 60 items, 60 new"]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(NewsItem)) == 60

    item = db.scalars(select(NewsItem).where(NewsItem.url == SCB_URL)).one()
    assert item.title == "SCB giảm lãi suất tiết kiệm xuống gần 0%"
    assert item.classification is NewsClassification.RATE_CHANGE
    assert (item.about_rates, item.about_card_fees) == (True, False)
    assert item.direction is NewsDirection.DOWN and item.classified_by == "keywords"
    assert [i.short_name for i in item.institutions] == ["SCB"]
    assert item.triggered_recheck is True

    # The bank's own source ran at once, marked as triggered by news ...
    [pipeline_run] = db.scalars(select(PipelineRun)).all()
    assert (pipeline_run.source_id, pipeline_run.trigger, pipeline_run.status) == (
        source.id,
        "news",
        "parsed",
    )
    # ... its values come from the bank's page and wait for review, with the news as context.
    task = db.get(ReviewTask, pipeline_run.review_task_id)
    assert task is not None
    assert task.payload_json["news"] == [
        {
            "url": SCB_URL,
            "title": "SCB giảm lãi suất tiết kiệm xuống gần 0%",
            "feed": "vnexpress-kinh-doanh",
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "direction": "down",
        }
    ]
    [rate] = db.scalars(select(SavingsRate)).all()
    snap = db.get(Snapshot, rate.snapshot_id)
    assert snap is not None and snap.source_id == source.id  # from the bank, not the news
    assert rate.status is VersionStatus.PENDING and rate.rate_pct == Decimal("0.50")
    assert item.recheck_json == [
        {
            "institution": "SCB",
            "source_id": source.id,
            "kind": "savings_rate_page",
            "status": "parsed",
            "attached_to": "new",
            "review_task_id": task.id,
        }
    ]

    # Every item here is settled by keywords: none names a known bank ambiguously.
    assert (result.by_keywords, result.by_llm, result.unresolved) == (60, 0, 0)
    fetch = db.scalars(select(NewsFetch)).one()
    assert (fetch.ok, fetch.items_seen, fetch.items_new) == (True, 60, 60)


def test_second_run_adds_nothing_and_rechecks_nothing(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    source: Source,
) -> None:
    run(factory, polite, config, matcher)
    again = run(factory, polite, config, matcher, now=NOW + dt.timedelta(hours=1))

    assert again.feeds[0].new == 0 and again.rechecks == [] and again.runs == []
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(NewsItem)) == 60
    assert db.scalar(select(func.count()).select_from(PipelineRun)) == 1


def test_same_story_in_another_feed_is_dropped_by_title(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    http_server: FixtureServer,
    matcher: InstitutionMatcher,
    source: Source,
) -> None:
    # A second publisher syndicating VnExpress: same titles, other URLs.
    copy = VNEXPRESS.replace(b"https://vnexpress.net/", b"https://copy.example/")
    http_server.route("/a.rss", Reply(200, VNEXPRESS, RSS))
    http_server.route("/b.rss", Reply(200, copy, RSS))
    config = FeedConfig(
        (feed(http_server, "a", "/a.rss"), feed(http_server, "b", "/b.rss", "Copy"))
    )
    result = run(factory, polite, config, matcher, do_recheck=False)

    assert [(f.seen, f.new) for f in result.feeds] == [(60, 60), (60, 0)]
    db.expire_all()
    assert not db.scalars(select(NewsItem).where(NewsItem.url.like("https://copy.%"))).all()


def test_llm_decides_ambiguous_items_and_cooldown_attaches_to_open_task(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    http_server: FixtureServer,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    source: Source,
) -> None:
    run(factory, polite, config, matcher)  # VnExpress: SCB re-checked, task opened
    http_server.route("/757/ngan-hang.rss", Reply(200, VIETSTOCK, RSS))
    vietstock = FeedConfig(
        (feed(http_server, "vietstock-ngan-hang", "/757/ngan-hang.rss", "Vietstock"),)
    )
    llm = FakeLLM()
    later = NOW + dt.timedelta(minutes=10)
    result = run(factory, polite, vietstock, matcher, llm=llm, now=later)

    # Only ambiguous items that name a known bank reach the LLM.
    assert "Lãi suất tiết kiệm SCB bất ngờ rơi về gần 0%/năm" in llm.titles
    assert result.by_llm == len(llm.titles) and result.unresolved == 0
    db.expire_all()
    item = db.scalars(
        select(NewsItem).where(NewsItem.title.like("Lãi suất tiết kiệm SCB bất ngờ%"))
    ).one()
    assert item.classification is NewsClassification.RATE_CHANGE
    assert item.classified_by == "llm" and item.classification_json["institutions"] == ["SCB"]

    # SCB's source ran 10 minutes ago: not fetched again, news added to its open task.
    assert result.runs == []
    [out] = result.rechecks
    assert out["status"] == "ran_recently" and out["attached_to"] == "open"
    task = db.get(ReviewTask, out["review_task_id"])
    assert task is not None
    assert [n["feed"] for n in task.payload_json["news"]] == [
        "vnexpress-kinh-doanh",
        "vietstock-ngan-hang",
    ]
    assert db.scalar(select(func.count()).select_from(PipelineRun)) == 1


def test_llm_cap_and_outage_leave_items_for_the_next_run(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    http_server: FixtureServer,
    matcher: InstitutionMatcher,
    source: Source,
) -> None:
    http_server.route("/v.rss", Reply(200, VIETSTOCK, RSS))
    capped = FeedConfig((feed(http_server, "v", "/v.rss"),), NewsOptions(llm_max_per_run=1))
    llm = FakeLLM()
    first = run(factory, polite, capped, matcher, llm=llm, do_recheck=False)
    assert len(llm.titles) == 1 and first.by_llm == 1 and first.unresolved >= 1

    broken = FakeLLM(fail_after=0)
    second = run(factory, polite, capped, matcher, llm=broken, do_recheck=False)
    assert second.llm_error == "Anthropic API error 529: overloaded"
    assert second.by_llm == 0 and second.unresolved == first.unresolved
    db.expire_all()
    waiting = db.scalar(
        select(func.count()).select_from(NewsItem).where(NewsItem.classification.is_(None))
    )
    assert waiting == first.unresolved

    # No API key: nothing is guessed, the items keep waiting.
    third = run(factory, polite, capped, matcher, llm=None, do_recheck=False)
    assert third.llm_error == "ANTHROPIC_API_KEY is not set"
    assert third.unresolved == waiting


def test_bank_without_a_source_is_recorded(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    scb: Institution,
) -> None:
    result = run(factory, polite, config, matcher)  # no SCB source exists

    assert result.rechecks == [{"institution": "SCB", "topic": "rates", "status": "no_source"}]
    db.expire_all()
    item = db.scalars(select(NewsItem).where(NewsItem.url == SCB_URL)).one()
    assert item.triggered_recheck and item.recheck_json == result.rechecks
    assert db.scalar(select(func.count()).select_from(PipelineRun)) == 0


def test_old_items_never_trigger_a_recheck(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    source: Source,
) -> None:
    result = run(factory, polite, config, matcher, now=NOW + dt.timedelta(days=5))

    assert result.rechecks == [] and result.runs == []
    db.expire_all()
    item = db.scalars(select(NewsItem).where(NewsItem.url == SCB_URL)).one()
    assert item.classification is NewsClassification.RATE_CHANGE  # still classified
    assert item.triggered_recheck is False


def test_broken_feeds_are_recorded(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    http_server: FixtureServer,
    matcher: InstitutionMatcher,
) -> None:
    http_server.route("/blocked.rss", Reply(403, "<h1>Access Denied</h1>"))
    http_server.route("/html.rss", body="<html><body>Bảo trì</body></html>")
    config = FeedConfig(
        (feed(http_server, "blocked", "/blocked.rss"), feed(http_server, "html", "/html.rss"))
    )
    result = run(factory, polite, config, matcher)

    assert not result.ok
    assert [(f.ok, (f.error or "").split(":")[0]) for f in result.feeds] == [
        (False, "FetchError"),
        (False, "FeedError"),
    ]
    db.expire_all()
    fetches = db.scalars(select(NewsFetch).order_by(NewsFetch.id)).all()
    assert [(f.feed, f.ok) for f in fetches] == [("blocked", False), ("html", False)]
    assert "HTTP 403" in (fetches[0].error or "")
    text = daily_summary(db, NOW + dt.timedelta(hours=1), TZ)
    assert "Nguồn tin lỗi: blocked, html" in text


def test_news_due_once_per_hourly_slot(db: Session) -> None:
    morning = dt.datetime(2026, 10, 28, 1, 30, tzinfo=dt.UTC)  # 08:30 in Vietnam
    assert news_due(db, morning, TZ)
    db.add(NewsFetch(feed="x", url="https://x.vn", started_at=morning, ok=True))
    db.flush()
    assert not news_due(db, morning + dt.timedelta(minutes=20), TZ)
    assert news_due(db, morning + dt.timedelta(minutes=40), TZ)  # 09:00 slot


def test_scheduler_tick_runs_news_when_due(
    db: Session,
    factory: Callable[[], Session],
    polite: PoliteHttp,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    source: Source,
    tmp_path: Path,
) -> None:
    # Tried after its 15:00 slot (not due), but over 30 minutes ago (no cooldown).
    source.last_attempt_at = NOW - dt.timedelta(hours=2)
    source.last_status = "unchanged"
    db.commit()
    calls: list[dt.datetime] = []

    def job(fetchers: Fetchers, clock: Callable[[], dt.datetime]) -> NewsRunResult:
        calls.append(clock())
        return run_news(factory, fetchers, MemoryStore(), config, tz=TZ, matcher=matcher, now=clock)

    settings = Settings(pipeline_lock_file=str(tmp_path / "lock"), daily_summary_hour=23)
    out = tick(
        settings,
        factory,
        lambda: Fetchers(polite),
        MemoryStore(),
        PrintNotifier(),
        clock=lambda: NOW,
        news=job,
    )
    assert calls == [NOW] and out.news is not None
    assert [r.status for r in out.results] == ["parsed"]  # the news-triggered re-check

    again = tick(
        settings,
        factory,
        lambda: Fetchers(polite),
        MemoryStore(),
        PrintNotifier(),
        clock=lambda: NOW + dt.timedelta(minutes=5),
        news=job,
    )
    assert len(calls) == 1 and again.news is None  # same hourly slot
