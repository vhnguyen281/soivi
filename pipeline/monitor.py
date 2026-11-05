"""What to tell the operator: broken-adapter alerts and the daily summary."""

import datetime as dt
from collections.abc import Sequence
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import NewsClassification, ReviewTaskKind, ReviewTaskStatus
from core.freshness import StalenessPolicy, institution_freshness
from core.models import (
    Institution,
    NewsFetch,
    NewsItem,
    Notification,
    PipelineRun,
    ReviewTask,
    Source,
)
from pipeline.runner import RunResult

BROKEN = frozenset({"parse_failed", "diff_failed"})
OK = frozenset({"parsed", "unchanged"})


# --------------------------------------------------------------------------- alerts


def alert_for(result: RunResult, previous_status: str | None) -> tuple[str, str] | None:
    """(kind, text) when an adapter breaks or recovers; None otherwise.

    Alerts on the change of state only, so a source that stays broken doesn't
    send the same alert at every slot.
    """
    was_broken = previous_status in BROKEN
    if result.status in BROKEN and not was_broken:
        return (
            "adapter_broken",
            f"🔴 <b>Adapter hỏng</b>: {escape(result.label)} (nguồn {result.source_id})\n"
            f"{escape(result.status)}: <code>{escape((result.error or '')[:600])}</code>\n"
            "Bản lưu đã được giữ lại; dữ liệu không được cập nhật cho đến khi sửa.",
        )
    if result.status in OK and was_broken:
        return (
            "adapter_recovered",
            f"🟢 <b>Adapter chạy lại bình thường</b>: {escape(result.label)} "
            f"(nguồn {result.source_id})",
        )
    return None


# --------------------------------------------------------------------------- summary


def summary_due(session: Session, now: dt.datetime, tz: ZoneInfo, hour: int) -> bool:
    """Once a day, from `hour` local time. A failed send is retried after 30 min."""
    local = now.astimezone(tz)
    if local.hour < hour:
        return False
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.UTC)
    sent = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.kind == "daily_summary",
            Notification.ok.is_(True),
            Notification.sent_at >= day_start,
        )
    )
    if sent:
        return False
    recent_failure = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.kind == "daily_summary",
            Notification.ok.is_(False),
            Notification.sent_at >= now - dt.timedelta(minutes=30),
        )
    )
    return not recent_failure


def daily_summary(
    session: Session, now: dt.datetime, tz: ZoneInfo, policy: StalenessPolicy | None = None
) -> str:
    since = now - dt.timedelta(hours=24)
    runs = session.scalars(select(PipelineRun).where(PipelineRun.started_at >= since)).all()
    by_status: dict[str, int] = {}
    for run in runs:
        by_status[run.status] = by_status.get(run.status, 0) + 1
    new = sum(r.new for r in runs)
    changed = sum(r.changed for r in runs)
    removed = sum(r.removed for r in runs)

    open_tasks = session.scalars(
        select(ReviewTask)
        .where(
            ReviewTask.status == ReviewTaskStatus.OPEN,
            ReviewTask.kind == ReviewTaskKind.VERSION_REVIEW,
        )
        .order_by(ReviewTask.created_at)
    ).all()

    names = {i.id: i.short_name for i in session.scalars(select(Institution))}
    broken = session.scalars(
        select(Source).where(Source.last_status.in_(BROKEN)).order_by(Source.id)
    ).all()
    unverified = [
        f for f in institution_freshness(session, now, policy).values() if f.state == "unverified"
    ]

    local = now.astimezone(tz)
    lines = [f"📊 <b>Soivi — tóm tắt {local:%d/%m/%Y}</b> (24 giờ qua)"]
    status_text = ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())) or "không có"
    lines.append(f"Lượt chạy: {len(runs)} ({escape(status_text)})")
    lines.append(f"Thay đổi tìm thấy: {new} mới, {changed} đổi, {removed} mất")
    if open_tasks:
        oldest = (now - open_tasks[0].created_at).total_seconds() / 3600
        lines.append(f"Việc chờ duyệt: {len(open_tasks)} (cũ nhất {oldest:.0f} giờ)")
    else:
        lines.append("Việc chờ duyệt: 0 ✓")
    if broken:
        lines.append(f"🔴 Adapter hỏng: {len(broken)}")
        for s in broken:
            label = "/".join(
                x for x in (names.get(s.institution_id or 0, "-"), s.kind.value, s.variant) if x
            )
            lines.append(f"  • {escape(label)}: {escape((s.last_error or '')[:150])}")
    else:
        lines.append("Adapter hỏng: 0 ✓")
    if unverified:
        names_text = ", ".join(f.short_name for f in unverified)
        lines.append(f"⚠️ Chưa xác minh (nguồn quá hạn): {escape(names_text)}")
    lines += _news_lines(session, since, runs)
    return "\n".join(lines)


def _news_lines(session: Session, since: dt.datetime, runs: Sequence[PipelineRun]) -> list[str]:
    fetches = session.scalars(
        select(NewsFetch).where(NewsFetch.started_at >= since).order_by(NewsFetch.started_at)
    ).all()
    if not fetches:
        return []
    latest = {f.feed: f for f in fetches}  # last attempt per feed
    items = session.scalars(select(NewsItem).where(NewsItem.created_at >= since)).all()
    changes = sum(
        i.classification in (NewsClassification.RATE_CHANGE, NewsClassification.CARD_CHANGE)
        for i in items
    )
    waiting = sum(i.classification is None for i in items)
    rechecks = sum(r.trigger == "news" for r in runs)
    text = (
        f"Tin tức: {len(items)} tin mới, {changes} về thay đổi lãi suất/phí thẻ, "
        f"{rechecks} lần kiểm tra lại nguồn"
    )
    if waiting:
        text += f" ({waiting} tin chưa phân loại được)"
    out = [text]
    failing = sorted(name for name, f in latest.items() if not f.ok)
    if failing:
        out.append(f"⚠️ Nguồn tin lỗi: {escape(', '.join(failing))}")
    return out
