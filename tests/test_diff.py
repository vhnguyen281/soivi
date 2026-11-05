"""pipeline/diff: parsed records -> pending versions + one review task per snapshot."""

import datetime as dt
import itertools
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.enums import (
    CardNetwork,
    ExtractionMethod,
    FetchMethod,
    InstitutionType,
    ReviewTaskStatus,
    SourceKind,
    VersionStatus,
)
from core.models import (
    CardProduct,
    ChangeEvent,
    Institution,
    ReviewTask,
    SavingsRate,
    Snapshot,
    Source,
)
from core.versioning import approve_version, get_current
from pipeline.diff import DiffError, diff_snapshot
from pipeline.records import CardTermsRecord, SavingsRateRecord

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
HTML = ExtractionMethod.HTML
_ids = itertools.count(1)


@pytest.fixture
def bank(db: Session) -> Institution:
    inst = Institution(
        legal_name_vi="Ngân hàng TMCP Ví Dụ",
        short_name="VIDU",
        type=InstitutionType.JOINT_STOCK_BANK,
    )
    db.add(inst)
    db.flush()
    return inst


@pytest.fixture
def source(db: Session, bank: Institution) -> Source:
    src = Source(
        institution_id=bank.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        url="https://vidu.example/lai-suat",
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name="x",
    )
    db.add(src)
    db.flush()
    return src


def snapshot(db: Session, source: Source) -> Snapshot:
    n = next(_ids)
    s = Snapshot(
        source_id=source.id,
        url=source.url or "",
        fetched_at=NOW,
        http_status=200,
        content_type="text/html",
        sha256=f"{n:064x}",
        storage_key=f"k/{n}",
        size_bytes=1,
    )
    db.add(s)
    db.flush()
    return s


def rate(months: int, value: str, **kw: Any) -> SavingsRateRecord:
    fields: dict[str, Any] = {
        "product_name": "Tiết kiệm thường",
        "channel": "counter",
        "term_months": months,
        "interest_payment": "end",
        "rate_pct": value,
    }
    return SavingsRateRecord(**{**fields, **kw})


PAGE = [rate(1, "4.50"), rate(6, "5.50"), rate(12, "5.90")]


def run(db: Session, source: Source, records: list[Any]) -> Any:
    return diff_snapshot(db, source, snapshot(db, source), records, HTML, now=NOW)


def approve_all(db: Session) -> None:
    for v in db.scalars(select(SavingsRate).where(SavingsRate.status == VersionStatus.PENDING)):
        approve_version(db, SavingsRate, v.id, reviewer="lan", now=NOW)


def tasks(db: Session) -> list[ReviewTask]:
    return list(db.scalars(select(ReviewTask).order_by(ReviewTask.id)))


def key(bank: Institution, months: int) -> dict[str, Any]:
    return {
        "institution_id": bank.id,
        "region": "",
        "product_name": "Tiết kiệm thường",
        "channel": "counter",
        "term_months": months,
        "term_days": 0,
        "min_amount_vnd": 0,
        "interest_payment": "end",
    }


# --------------------------------------------------------------------------- new


def test_new_series_become_pending_with_one_task(
    db: Session, bank: Institution, source: Source
) -> None:
    result = run(db, source, PAGE)

    assert (result.new, result.changed, result.removed, result.unchanged) == (3, 0, 0, 0)
    pending = db.scalars(select(SavingsRate)).all()
    assert len(pending) == 3 and {v.status for v in pending} == {VersionStatus.PENDING}
    [task] = tasks(db)
    assert task.id == result.review_task_id and task.status == ReviewTaskStatus.OPEN
    assert {v.review_task_id for v in pending} == {task.id}
    assert task.payload_json["summary"]["new"] == 3
    assert {i["change"] for i in task.payload_json["items"]} == {"new"}
    events = db.scalars(select(ChangeEvent)).all()
    assert events and {e.review_task_id for e in events} == {task.id}


# --------------------------------------------------------------------------- unchanged


def test_unchanged_page_creates_nothing(db: Session, bank: Institution, source: Source) -> None:
    run(db, source, PAGE)
    approve_all(db)
    events_before = db.scalar(select(func.count()).select_from(ChangeEvent))

    result = run(db, source, PAGE)

    assert (result.new, result.changed, result.removed, result.unchanged) == (0, 0, 0, 3)
    assert result.review_task_id is None
    assert len(tasks(db)) == 1  # only the first one
    assert db.scalar(select(func.count()).select_from(SavingsRate)) == 3
    assert db.scalar(select(func.count()).select_from(ChangeEvent)) == events_before
    live = get_current(db, SavingsRate, **key(bank, 12))
    assert live is not None and live.last_seen_at == NOW


# --------------------------------------------------------------------------- changed


def test_changed_value_is_proposed_and_old_stays_live(
    db: Session, bank: Institution, source: Source
) -> None:
    run(db, source, PAGE)
    approve_all(db)

    result = run(db, source, [rate(1, "4.50"), rate(6, "5.50"), rate(12, "6.10")])

    assert (result.new, result.changed, result.removed, result.unchanged) == (0, 1, 0, 2)
    task = tasks(db)[-1]
    [item] = task.payload_json["items"]
    assert item["change"] == "changed" and item["fields"] == ["rate_pct"]
    assert (item["old"]["rate_pct"], item["new"]["rate_pct"]) == ("5.900", "6.10")
    live = get_current(db, SavingsRate, **key(bank, 12))
    assert live is not None and live.rate_pct == Decimal("5.90")  # still the approved one


# --------------------------------------------------------------------------- removed


def test_disappearing_term_is_listed_and_flagged(
    db: Session, bank: Institution, source: Source
) -> None:
    run(db, source, PAGE)
    approve_all(db)

    result = run(db, source, [rate(1, "4.50"), rate(12, "5.90")])  # 6 months gone

    assert (result.new, result.changed, result.removed, result.unchanged) == (0, 0, 1, 2)
    task = tasks(db)[-1]
    [item] = task.payload_json["items"]
    assert item["change"] == "removed" and item["key"]["term_months"] == 6
    assert [w["rule"] for w in task.payload_json["warnings"]] == ["removed_series"]
    # nothing is written to the series: the approved 6-month rate stays live
    assert get_current(db, SavingsRate, **key(bank, 6)) is not None


def test_removal_is_scoped_to_the_source(db: Session, bank: Institution, source: Source) -> None:
    run(db, source, PAGE)
    approve_all(db)
    online = Source(
        institution_id=bank.id,
        kind=SourceKind.SAVINGS_RATE_PAGE,
        variant="online",
        url="https://vidu.example/online",
        fetch_method=FetchMethod.HTTP,
        cadence_hours=12,
        adapter_name="x",
    )
    db.add(online)
    db.flush()

    result = run(db, online, [rate(3, "6.00", channel="online")])

    assert result.removed == 0  # the counter page's series belong to the other source


# --------------------------------------------------------------------------- warnings


def test_rule_violations_are_warnings_not_rejections(
    db: Session, bank: Institution, source: Source
) -> None:
    run(db, source, PAGE)
    approve_all(db)

    result = run(
        db,
        source,
        [
            rate(1, "4.50"),
            rate(6, "15.00"),  # out of range and a +9.5 point jump
            rate(
                12, "6.50", effective_from=(NOW + dt.timedelta(days=90)).date()
            ),  # +0.6, far future
        ],
    )

    rules = sorted(w.rule for w in result.warnings)
    assert rules == ["future_effective_from", "large_change", "large_change", "range"]
    task = tasks(db)[-1]
    assert len(task.payload_json["warnings"]) == 4
    assert task.status == ReviewTaskStatus.OPEN
    statuses = {v.rate_pct: v.status for v in db.scalars(select(SavingsRate))}
    assert statuses[Decimal("15.00")] == VersionStatus.PENDING  # not auto-rejected


# --------------------------------------------------------------------------- safety


def test_same_snapshot_twice_keeps_one_task(db: Session, bank: Institution, source: Source) -> None:
    snap = snapshot(db, source)
    first = diff_snapshot(db, source, snap, PAGE, HTML, now=NOW)
    again = diff_snapshot(db, source, snap, PAGE, HTML, now=NOW)

    assert again.review_task_id == first.review_task_id
    assert again.new == 3
    assert len(tasks(db)) == 1
    assert db.scalar(select(func.count()).select_from(SavingsRate)) == 3


def test_needs_fix_snapshot_is_proposed_again(
    db: Session, bank: Institution, source: Source
) -> None:
    from review_app import service

    snap = snapshot(db, source)
    first = diff_snapshot(db, source, snap, PAGE, HTML, now=NOW)
    assert first.review_task_id is not None
    service.needs_fix(db, first.review_task_id, "reviewer", "wrong reading", now=NOW)
    # a corrected parser reads the same bytes again: a new task with new pending values
    again = diff_snapshot(db, source, snap, PAGE[:2], HTML, now=NOW)
    assert again.review_task_id not in (None, first.review_task_id)
    assert again.new == 2
    statuses = sorted(v.status.value for v in db.scalars(select(SavingsRate)))
    assert statuses == ["pending", "pending", "rejected", "rejected", "rejected"]


def test_decided_snapshot_reparsed_proposes_only_what_is_new(
    db: Session, bank: Institution, source: Source
) -> None:
    from review_app import service

    snap = snapshot(db, source)
    first = diff_snapshot(db, source, snap, PAGE, HTML, now=NOW)
    assert first.review_task_id is not None
    service.approve_all(db, first.review_task_id, "reviewer", now=NOW)
    # same values again: nothing to review, no task
    same = diff_snapshot(db, source, snap, PAGE, HTML, now=NOW)
    assert (same.unchanged, same.new, same.review_task_id) == (3, 0, None)
    # an extended parser finds one more value in the same bytes
    more = diff_snapshot(db, source, snap, [*PAGE, rate(24, "6.10")], HTML, now=NOW)
    assert (more.unchanged, more.new) == (3, 1)
    assert more.review_task_id not in (None, first.review_task_id)


def test_later_snapshot_with_same_pending_values_adds_no_task(
    db: Session, bank: Institution, source: Source
) -> None:
    run(db, source, PAGE)
    result = run(db, source, PAGE)  # nobody has reviewed yet
    assert result.already_pending == 3 and result.review_task_id is None
    assert len(tasks(db)) == 1


def test_duplicate_series_fails_without_writing(
    db: Session, bank: Institution, source: Source
) -> None:
    with pytest.raises(DiffError, match="two parsed records"):
        run(db, source, [rate(12, "5.90"), rate(12, "6.00")])
    assert db.scalar(select(func.count()).select_from(SavingsRate)) == 0
    assert tasks(db) == []


def test_card_records_find_or_create_the_product(db: Session, bank: Institution) -> None:
    src = Source(
        institution_id=bank.id,
        kind=SourceKind.CARD_TARIFF_PDF,
        url="https://vidu.example/bieu-phi.pdf",
        fetch_method=FetchMethod.PDF,
        cadence_hours=168,
        adapter_name="x",
    )
    db.add(src)
    db.flush()
    terms = CardTermsRecord(
        card_name="Ví Dụ Platinum", network="visa", interest_rate_pct="28", fx_fee_pct="3"
    )

    first = run(db, src, [terms])
    assert first.new == 1
    assert [w.rule for w in first.warnings] == ["new_card_product"]
    [product] = db.scalars(select(CardProduct)).all()
    assert (product.name, product.network) == ("Ví Dụ Platinum", CardNetwork.VISA)

    second = run(db, src, [terms])
    assert second.already_pending == 1 and second.warnings == []  # product found, not re-created
    assert db.scalar(select(func.count()).select_from(CardProduct)) == 1
