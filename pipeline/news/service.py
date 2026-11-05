"""One news run: read the feeds, store new items, classify them, and re-check the
sources of banks that an item says changed their rates or card fees.

    run_news(...)  ->  fetch_feed()  for each feed      (one transaction per feed)
                       classify_pending()                (LLM only for ambiguous items)
                       recheck()                         (one transaction per source)

News never writes product values: a re-check runs the bank's own adapter, whose
changes go to human review as usual, with the news URL attached as context.
"""

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import NewsClassification, ReviewTaskKind, ReviewTaskStatus, SourceKind
from core.models import Institution, NewsFetch, NewsItem, ReviewTask, Source
from pipeline.adapters.base import AdapterContext
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import FetchError
from pipeline.fetch.storage import SnapshotStore
from pipeline.news.classify import Classification, classify_keywords
from pipeline.news.feeds import Feed, FeedConfig, FeedEntry, FeedError, parse, title_key
from pipeline.news.institutions import InstitutionMatcher
from pipeline.news.llm import Classifier, LLMError
from pipeline.registry import all_adapters
from pipeline.runner import RunResult, run_source, runnable
from pipeline.schedule import NEWS, last_slot

Clock = Callable[[], dt.datetime]

RATE_KINDS: tuple[SourceKind, ...] = (SourceKind.SAVINGS_RATE_PAGE,)
CARD_KINDS: tuple[SourceKind, ...] = (SourceKind.CARD_TARIFF_PDF, SourceKind.CARD_PRODUCT_PAGE)
RECHECK = (NewsClassification.RATE_CHANGE, NewsClassification.CARD_CHANGE)


@dataclass
class FeedOutcome:
    feed: str
    ok: bool
    seen: int = 0
    new: int = 0
    by_keywords: int = 0  # new items decided by keywords
    error: str | None = None

    def __str__(self) -> str:
        if not self.ok:
            return f"[failed] {self.feed}: {self.error}"
        return f"[ok] {self.feed}: {self.seen} items, {self.new} new"


@dataclass
class NewsRunResult:
    feeds: list[FeedOutcome] = field(default_factory=list)
    by_keywords: int = 0
    by_llm: int = 0
    unresolved: int = 0  # ambiguous, no LLM answer yet
    llm_error: str | None = None
    rechecks: list[dict[str, Any]] = field(default_factory=list)
    # (result, the source's status before the run) for broken-adapter alerts
    runs: list[tuple[RunResult, str | None]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.feeds) and all(r.ok for r, _ in self.runs)

    def lines(self) -> list[str]:
        out = [str(f) for f in self.feeds]
        out.append(
            f"classified: {self.by_keywords} by keywords, {self.by_llm} by LLM, "
            f"{self.unresolved} waiting for the LLM"
            + (f" ({self.llm_error})" if self.llm_error else "")
        )
        for r in self.rechecks:
            task = f", review task {r['review_task_id']}" if r.get("review_task_id") else ""
            source = f" source {r['source_id']}" if r.get("source_id") else ""
            out.append(f"recheck {r['institution']}{source}: {r['status']}{task}")
        return out


# --------------------------------------------------------------------------- fetch + store


def fetch_feed(
    session_factory: Callable[[], Session],
    fetchers: Fetchers,
    feed: Feed,
    config: FeedConfig,
    matcher: InstitutionMatcher,
    tz: ZoneInfo,
    now: Clock,
) -> FeedOutcome:
    started = now()
    outcome = FeedOutcome(feed.name, ok=False)
    try:
        response = fetchers.http.get(feed.url)
        entries = parse(response.content, feed, tz)
    except (FetchError, FeedError) as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
        entries = []
    with session_factory() as session, session.begin():
        if entries:
            outcome.ok, outcome.seen = True, len(entries)
            outcome.new, outcome.by_keywords = store_entries(
                session, feed, entries, config, matcher, now()
            )
        session.add(
            NewsFetch(
                feed=feed.name,
                url=feed.url,
                started_at=started,
                ok=outcome.ok,
                items_seen=outcome.seen,
                items_new=outcome.new,
                error=outcome.error,
            )
        )
    return outcome


def store_entries(
    session: Session,
    feed: Feed,
    entries: Sequence[FeedEntry],
    config: FeedConfig,
    matcher: InstitutionMatcher,
    now: dt.datetime,
) -> tuple[int, int]:
    """Insert entries not seen before (same URL, or same title within a few days).
    Each new item is classified by keywords straight away; ambiguous ones stay NULL.
    Returns (new items, of which decided by keywords)."""
    institutions = {i.short_name: i for i in session.scalars(select(Institution))}
    window = dt.timedelta(days=config.options.dedupe_title_days)
    new = by_keywords = 0
    for entry in entries:
        if session.scalar(select(NewsItem.id).where(NewsItem.url == entry.url)):
            continue
        key = title_key(entry.title)
        when = entry.published_at or now
        same_story = session.scalar(
            select(NewsItem.id).where(
                NewsItem.title_key == key,
                func.coalesce(NewsItem.published_at, NewsItem.created_at).between(
                    when - window, when + window
                ),
            )
        )
        if key and same_story:
            continue
        item = NewsItem(
            feed=feed.name,
            url=entry.url,
            title=entry.title,
            title_key=key,
            summary=entry.summary,
            published_at=entry.published_at,
            created_at=now,
        )
        item.institutions = [
            institutions[s] for s in matcher.find(entry.title, entry.summary) if s in institutions
        ]
        decided = classify_keywords(entry.title, entry.summary, matcher)
        if decided is not None:
            _apply(item, decided, now)
            by_keywords += 1
        session.add(item)
        session.flush()  # later entries in this run see it (same story in one feed)
        new += 1
    return new, by_keywords


def _apply(item: NewsItem, decision: Classification, now: dt.datetime) -> None:
    item.classification = decision.category
    item.about_rates = decision.about_rates
    item.about_card_fees = decision.about_card_fees
    item.direction = decision.direction
    item.classified_by = decision.method
    item.classified_at = now
    item.classification_json = decision.as_json()


# --------------------------------------------------------------------------- classify


def _recent(now: dt.datetime, hours: int) -> Any:
    return func.coalesce(NewsItem.published_at, NewsItem.created_at) >= now - dt.timedelta(
        hours=hours
    )


def classify_pending(
    session: Session,
    config: FeedConfig,
    llm: Classifier | None,
    publishers: dict[str, str],
    result: NewsRunResult,
    now: dt.datetime,
) -> None:
    """Ask the LLM about recent ambiguous items (newest first, capped per run).
    Older ambiguous items are left alone: they could no longer trigger a re-check."""
    pending = session.scalars(
        select(NewsItem)
        .where(
            NewsItem.classification.is_(None),
            _recent(now, config.options.recheck_window_hours),
        )
        .order_by(func.coalesce(NewsItem.published_at, NewsItem.created_at).desc())
    ).all()
    budget = config.options.llm_max_per_run if llm is not None else 0
    for item in pending:
        if budget <= 0 or result.llm_error:
            result.unresolved += 1
            continue
        budget -= 1
        try:
            assert llm is not None
            decision = llm(item.title, item.summary, publishers.get(item.feed, item.feed))
        except LLMError as exc:
            # Stop for this run (an outage or a bad key would fail every call).
            result.llm_error = str(exc)
            result.unresolved += 1
            continue
        _apply(item, decision, now)
        result.by_llm += 1
    if llm is None and pending:
        result.llm_error = "ANTHROPIC_API_KEY is not set"


# --------------------------------------------------------------------------- re-check


@dataclass
class _Plan:
    source_ids: dict[int, list[int]] = field(default_factory=dict)  # source -> news items
    no_source: list[tuple[int, str, str]] = field(default_factory=list)  # item, inst, topic


def _plan(session: Session, items: Sequence[NewsItem]) -> _Plan:
    plan = _Plan()
    adapters = set(all_adapters())
    for item in items:
        data = item.classification_json or {}
        topics: list[tuple[str, tuple[SourceKind, ...]]] = []
        if item.about_rates:
            topics.append(("rates", RATE_KINDS))
        if item.about_card_fees:
            topics.append(("card_fees", CARD_KINDS))
        for short_name in data.get("institutions", []):
            inst = session.scalars(
                select(Institution).where(Institution.short_name == short_name)
            ).first()
            for topic, kinds in topics:
                sources = (
                    session.scalars(
                        runnable().where(Source.institution_id == inst.id, Source.kind.in_(kinds))
                    ).all()
                    if inst
                    else []
                )
                sources = [s for s in sources if s.adapter_name in adapters]
                if not sources:
                    plan.no_source.append((item.id, short_name, topic))
                for s in sources:
                    plan.source_ids.setdefault(s.id, []).append(item.id)
    return plan


def recheck(
    session_factory: Callable[[], Session],
    fetchers: Fetchers,
    store: SnapshotStore,
    config: FeedConfig,
    result: NewsRunResult,
    now: Clock,
) -> None:
    with session_factory() as session:
        items = session.scalars(
            select(NewsItem)
            .where(
                NewsItem.classification.in_(RECHECK),
                NewsItem.triggered_recheck.is_(False),
                _recent(now(), config.options.recheck_window_hours),
            )
            .order_by(NewsItem.id)
        ).all()
        plan = _plan(session, items)
        item_ids = [i.id for i in items]

    outcomes: dict[int, list[dict[str, Any]]] = {i: [] for i in item_ids}
    for item_id, short_name, topic in plan.no_source:
        missing = {"institution": short_name, "topic": topic, "status": "no_source"}
        outcomes[item_id].append(missing)
        result.rechecks.append(missing)

    cooldown = dt.timedelta(minutes=config.options.recheck_cooldown_minutes)
    for source_id, news_ids in plan.source_ids.items():
        with session_factory() as session, session.begin():
            source = session.get(Source, source_id)
            assert source is not None
            inst = session.get(Institution, source.institution_id or 0)
            out: dict[str, Any] = {
                "institution": inst.short_name if inst else None,
                "source_id": source_id,
                "kind": source.kind.value,
            }
            if source.last_attempt_at and now() - source.last_attempt_at < cooldown:
                out["status"] = "ran_recently"
                task_id = None
            else:
                previous = source.last_status
                ctx = AdapterContext(session=session, fetchers=fetchers, store=store)
                run = run_source(ctx, source, trigger="news", now=now)
                result.runs.append((run, previous))
                out["status"] = run.status
                task_id = run.diff.review_task_id if run.diff else None
            out["attached_to"] = "new" if task_id else None
            if task_id is None:
                task_id = _open_task(
                    session,
                    source_id,
                    now() - dt.timedelta(hours=config.options.recheck_window_hours),
                )
                out["attached_to"] = "open" if task_id else None
            out["review_task_id"] = task_id
            if task_id is not None:
                news = session.scalars(select(NewsItem).where(NewsItem.id.in_(news_ids))).all()
                task = session.get(ReviewTask, task_id)
                assert task is not None
                attach_news(task, news)
        for news_id in news_ids:
            outcomes[news_id].append(out)
        result.rechecks.append(out)

    with session_factory() as session, session.begin():
        for item_id, item_outcomes in outcomes.items():
            item = session.get(NewsItem, item_id)
            assert item is not None
            item.triggered_recheck = True
            item.recheck_json = item_outcomes


def _open_task(session: Session, source_id: int, since: dt.datetime) -> int | None:
    """The newest open review task for the source, if recent: the news is context for it."""
    return session.scalar(
        select(ReviewTask.id)
        .where(
            ReviewTask.source_id == source_id,
            ReviewTask.kind == ReviewTaskKind.VERSION_REVIEW,
            ReviewTask.status == ReviewTaskStatus.OPEN,
            ReviewTask.created_at >= since,
        )
        .order_by(ReviewTask.created_at.desc(), ReviewTask.id.desc())
        .limit(1)
    )


def attach_news(task: ReviewTask, items: Sequence[NewsItem]) -> None:
    """Add the items to the task's payload["news"] (context only; once per URL)."""
    payload = dict(task.payload_json or {})
    news: list[dict[str, Any]] = list(payload.get("news", []))
    known = {n["url"] for n in news}
    for item in items:
        if item.url in known:
            continue
        known.add(item.url)
        news.append(
            {
                "url": item.url,
                "title": item.title,
                "feed": item.feed,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "direction": item.direction.value if item.direction else None,
            }
        )
    payload["news"] = news
    task.payload_json = payload  # a new dict, so SQLAlchemy sees the change


# --------------------------------------------------------------------------- run


def run_news(
    session_factory: Callable[[], Session],
    fetchers: Fetchers,
    store: SnapshotStore,
    config: FeedConfig,
    *,
    tz: ZoneInfo,
    llm: Classifier | None = None,
    matcher: InstitutionMatcher | None = None,
    feeds: Sequence[Feed] | None = None,
    do_recheck: bool = True,
    now: Clock = lambda: dt.datetime.now(dt.UTC),
) -> NewsRunResult:
    result = NewsRunResult()
    if matcher is None:
        with session_factory() as session:
            matcher = InstitutionMatcher.from_db(session)
    for feed in feeds if feeds is not None else config.feeds:
        result.feeds.append(fetch_feed(session_factory, fetchers, feed, config, matcher, tz, now))

    result.by_keywords = sum(f.by_keywords for f in result.feeds)
    with session_factory() as session, session.begin():
        publishers = {f.name: f.publisher for f in config.feeds}
        classify_pending(session, config, llm, publishers, result, now())

    if do_recheck:
        recheck(session_factory, fetchers, store, config, result, now)
    return result


def news_due(session: Session, now: dt.datetime, tz: ZoneInfo) -> bool:
    """Due when no feed has been read since the most recent news slot."""
    slot = last_slot(NEWS, now, tz)
    return not session.scalar(
        select(func.count()).select_from(NewsFetch).where(NewsFetch.started_at >= slot)
    )
