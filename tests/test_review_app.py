"""Review app: auth, queue, task page, decisions, snapshots, audit log."""

import datetime as dt
import itertools
from collections.abc import Iterator
from decimal import Decimal
from html import unescape
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    ExtractionMethod,
    FetchMethod,
    InstitutionType,
    NewsDirection,
    ReviewActionKind,
    ReviewTaskStatus,
    SourceKind,
    VersionStatus,
)
from core.models import (
    SAVINGS_RATE_KEY,
    Institution,
    ReviewAction,
    ReviewTask,
    SavingsRate,
    Snapshot,
    Source,
)
from core.versioning import get_current
from pipeline.diff import diff_snapshot
from pipeline.fetch.storage import MemoryStore
from pipeline.records import SavingsRateRecord
from review_app.app import create_app

pytestmark = pytest.mark.db

AUTH = ("reviewer", "s3cret-review")
HX = {"HX-Request": "true"}
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
_n = itertools.count(1)


def rate(months: int, value: str) -> SavingsRateRecord:
    return SavingsRateRecord(
        product_name="Tiết kiệm thường",
        channel="counter",
        term_months=months,
        interest_payment="end",
        rate_pct=value,
    )


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def source(db: Session) -> Source:
    bank = Institution(
        legal_name_vi="Ngân hàng Ví Dụ", short_name="VIDU", type=InstitutionType.JOINT_STOCK_BANK
    )
    db.add(bank)
    db.flush()
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


def snap(
    db: Session, store: MemoryStore, source: Source, body: bytes, ctype: str = "text/html"
) -> Snapshot:
    n = next(_n)
    ext = {"text/html": "html", "application/pdf": "pdf", "application/json": "json"}[ctype]
    s = Snapshot(
        source_id=source.id,
        url=source.url or "",
        fetched_at=NOW,
        http_status=200,
        content_type=ctype,
        sha256=f"{n:064x}",
        storage_key=f"VIDU/x/{n}.{ext}",
        size_bytes=len(body),
    )
    db.add(s)
    db.flush()
    store.put(s.storage_key, body, ctype)
    return s


def make_task(
    db: Session, store: MemoryStore, source: Source, records: list[Any], body: bytes = b"<p>x</p>"
) -> int:
    result = diff_snapshot(
        db, source, snap(db, store, source, body), records, ExtractionMethod.HTML, now=NOW
    )
    assert result.review_task_id is not None
    return result.review_task_id


@pytest.fixture
def client(db: Session, store: MemoryStore) -> Iterator[TestClient]:
    conn = db.connection()
    assert isinstance(conn, Connection)
    settings = Settings(review_username=AUTH[0], review_password=AUTH[1])
    app = create_app(
        settings,
        session_factory=lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        store=store,
    )
    with TestClient(app) as c:
        c.auth = AUTH
        yield c


def versions(db: Session) -> list[SavingsRate]:
    db.expire_all()
    return list(db.scalars(select(SavingsRate).order_by(SavingsRate.id)))


def task(db: Session, task_id: int) -> ReviewTask:
    db.expire_all()
    t = db.get(ReviewTask, task_id)
    assert t is not None
    return t


def actions(db: Session) -> list[ReviewAction]:
    return list(db.scalars(select(ReviewAction).order_by(ReviewAction.id)))


# --------------------------------------------------------------------------- auth & safety


def test_requires_login(client: TestClient) -> None:
    assert client.get("/", auth=None).status_code == 401
    assert client.get("/", auth=("reviewer", "wrong")).status_code == 401
    assert client.get("/", auth=("someone", AUTH[1])).status_code == 401
    assert client.get("/").status_code == 200


def test_refuses_to_start_without_password() -> None:
    with pytest.raises(RuntimeError, match="REVIEW_PASSWORD"):
        create_app(Settings(review_password=""))


def test_writes_need_the_htmx_header(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(12, "5.90")])
    response = client.post(f"/tasks/{task_id}/approve-all")  # e.g. a form on another site
    assert response.status_code == 403
    assert {v.status for v in versions(db)} == {VersionStatus.PENDING}
    assert actions(db) == []


# --------------------------------------------------------------------------- queue & task page


def test_queue_lists_open_tasks_oldest_first(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    first = make_task(db, store, source, [rate(1, "4.50"), rate(12, "5.90")])
    task(db, first).created_at = NOW - dt.timedelta(hours=2)
    second = make_task(db, store, source, [rate(6, "15.00")])  # out of range: 1 warning
    task(db, second).created_at = NOW - dt.timedelta(hours=1)
    db.flush()

    html = client.get("/").text

    assert html.index(f'href="/tasks/{first}"') < html.index(f'href="/tasks/{second}"')
    assert "VIDU" in html and "savings_rate_page" in html
    assert '<span class="warn">1</span>' in html


def test_task_page_shows_old_and_new(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    first = make_task(db, store, source, [rate(12, "5.90")])
    client.post(f"/tasks/{first}/approve-all", headers=HX)
    changed = make_task(db, store, source, [rate(12, "6.50")])

    html = unescape(client.get(f"/tasks/{changed}").text)

    assert "Tiết kiệm thường · counter · 12 tháng · end" in html
    assert "<s>5.900</s> → <mark>6.50</mark>" in html
    assert "large_change" in html and "+0.600 points (5.900 → 6.50)" in html
    assert "Duyệt tất cả" in html


def test_task_page_shows_attached_news(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    from pipeline.news.service import attach_news

    task_id = make_task(db, store, source, [rate(12, "5.90")])
    plain = client.get(f"/tasks/{task_id}").text
    assert "Tin tức liên quan" not in plain

    task = db.get(ReviewTask, task_id)
    assert task is not None
    item = SimpleNamespace(
        url="https://vnexpress.net/scb-giam-lai-suat-tiet-kiem-xuong-gan-0-5137507.html",
        title="SCB giảm lãi suất tiết kiệm <xuống> gần 0%",
        feed="vnexpress-kinh-doanh",
        published_at=dt.datetime(2026, 10, 28, 9, 35, tzinfo=dt.UTC),
        direction=NewsDirection.DOWN,
    )
    attach_news(task, [item, item])  # type: ignore[list-item]
    db.flush()

    html = client.get(f"/tasks/{task_id}").text
    assert "Tin tức liên quan (1)" in html
    assert (
        'href="https://vnexpress.net/scb-giam-lai-suat-tiet-kiem-xuong-gan-0-5137507.html"' in html
    )
    assert 'rel="noopener noreferrer"' in html
    assert "SCB giảm lãi suất tiết kiệm &lt;xuống&gt; gần 0%" in html  # escaped
    assert "28/10 16:35" in html and "giảm" in html  # Vietnam time, direction
    assert "không lấy từ báo" in html


def test_new_rows_show_rate_first_and_hide_empty_fields(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(12, "5.90")])
    html = unescape(client.get(f"/tasks/{task_id}").text)
    row = html[html.index('id="item-savings_rate-') :]
    assert row.index("rate_pct") < row.index("</dl>")
    assert "conditions_text" not in row.split("</tr>")[0]  # None: hidden
    assert "is_cd" not in row.split("</tr>")[0]  # False: hidden


# --------------------------------------------------------------------------- decisions


def test_approve_all_closes_old_versions_and_logs(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    first = make_task(db, store, source, [rate(12, "5.90")])
    response = client.post(f"/tasks/{first}/approve-all", headers=HX)
    assert response.status_code == 204 and response.headers["HX-Redirect"] == "/"
    [old] = versions(db)
    assert old.status == VersionStatus.APPROVED and old.reviewer == "reviewer"

    changed = make_task(db, store, source, [rate(12, "6.10")])
    client.post(f"/tasks/{changed}/approve-all", headers=HX)

    old, new = versions(db)
    assert old.valid_to is not None and old.valid_to == new.valid_from  # old closed
    live = get_current(db, SavingsRate, **{c: getattr(new, c) for c in SavingsRate.__version_key__})
    assert live is not None and live.rate_pct == Decimal("6.10")
    assert task(db, changed).status == ReviewTaskStatus.APPROVED
    log = actions(db)
    assert [a.action for a in log] == [ReviewActionKind.APPROVE_ALL] * 2
    assert log[-1].version_ids == [new.id] and log[-1].reviewer == "reviewer"


def test_reject_all(client: TestClient, db: Session, store: MemoryStore, source: Source) -> None:
    task_id = make_task(db, store, source, [rate(1, "4.50"), rate(12, "5.90")])
    client.post(f"/tasks/{task_id}/reject-all", headers=HX)
    assert {v.status for v in versions(db)} == {VersionStatus.REJECTED}
    assert task(db, task_id).status == ReviewTaskStatus.REJECTED
    assert actions(db)[-1].action == ReviewActionKind.REJECT_ALL


def test_needs_fix_requires_a_note(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(12, "59.00")])
    assert (
        client.post(f"/tasks/{task_id}/needs-fix", headers=HX, data={"note": "  "}).status_code
        == 409
    )
    assert task(db, task_id).status == ReviewTaskStatus.OPEN

    client.post(
        f"/tasks/{task_id}/needs-fix", headers=HX, data={"note": "dấu phẩy đọc sai: 5,90 → 59,0"}
    )

    t = task(db, task_id)
    assert t.status == ReviewTaskStatus.NEEDS_FIX and t.note == "dấu phẩy đọc sai: 5,90 → 59,0"
    assert {v.status for v in versions(db)} == {VersionStatus.REJECTED}  # nothing wrong goes live
    assert actions(db)[-1].note == t.note


def test_row_by_row_then_task_closes(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(1, "4.50"), rate(12, "5.90")])
    one, twelve = versions(db)

    r1 = client.post(f"/tasks/{task_id}/versions/savings_rate/{one.id}/approve", headers=HX)
    assert r1.status_code == 200
    assert f'id="item-savings_rate-{one.id}"' in r1.text and "s-approved" in r1.text
    assert task(db, task_id).status == ReviewTaskStatus.OPEN  # one row still pending

    r2 = client.post(f"/tasks/{task_id}/versions/savings_rate/{twelve.id}/reject", headers=HX)
    assert 'id="task-status" hx-swap-oob="true"' in r2.text and ">approved<" in r2.text
    assert task(db, task_id).status == ReviewTaskStatus.APPROVED  # something was approved
    assert [v.status for v in versions(db)] == [VersionStatus.APPROVED, VersionStatus.REJECTED]
    assert [(a.action, a.version_ids) for a in actions(db)] == [
        (ReviewActionKind.APPROVE, [one.id]),
        (ReviewActionKind.REJECT, [twelve.id]),
    ]


def test_refused_actions(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(1, "4.50"), rate(12, "5.90")])
    one, _ = versions(db)
    client.post(f"/tasks/{task_id}/versions/savings_rate/{one.id}/approve", headers=HX)
    again = client.post(f"/tasks/{task_id}/versions/savings_rate/{one.id}/reject", headers=HX)
    assert again.status_code == 409 and "approved, not pending" in again.text

    other = make_task(db, store, source, [rate(6, "5.50")])
    [six] = [v for v in versions(db) if v.term_months == 6]
    wrong_task = client.post(f"/tasks/{task_id}/versions/savings_rate/{six.id}/approve", headers=HX)
    assert wrong_task.status_code == 409 and "not part of task" in wrong_task.text

    client.post(f"/tasks/{other}/reject-all", headers=HX)
    closed = client.post(f"/tasks/{other}/approve-all", headers=HX)
    assert closed.status_code == 409 and "already rejected" in closed.text


def test_superseded_rows_are_skipped(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    older = make_task(db, store, source, [rate(12, "5.90")])
    make_task(db, store, source, [rate(12, "6.00")])  # replaces the unreviewed proposal
    result = client.post(f"/tasks/{older}/approve-all", headers=HX)
    assert result.status_code == 204
    assert actions(db)[-1].version_ids == []  # nothing pending was left in the older task
    assert "superseded" in client.get(f"/tasks/{older}").text


# --------------------------------------------------------------------------- snapshots & audit


def test_html_snapshot_is_sandboxed(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    body = b"<html><script>alert(1)</script><p>L\xc3\xa3i su\xe1\xba\xa5t</p></html>"
    task_id = make_task(db, store, source, [rate(12, "5.90")], body=body)
    snap_id = task(db, task_id).snapshot_id

    page = client.get(f"/snapshots/{snap_id}").text
    assert f'<iframe class="snap" sandbox src="/snapshots/{snap_id}/raw?display=1"' in page
    raw = client.get(f"/snapshots/{snap_id}/raw")
    assert raw.content == body  # the evidence, byte for byte
    shown = client.get(f"/snapshots/{snap_id}/raw?display=1")
    assert shown.content.startswith(b'<base href="https://vidu.example/lai-suat">')
    assert shown.headers["content-security-policy"] == "sandbox"
    assert raw.headers["content-security-policy"] == "sandbox"
    assert raw.headers["x-content-type-options"] == "nosniff"


def test_pdf_and_json_snapshots(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    pdf = snap(db, store, source, b"%PDF-1.4 ...", "application/pdf")
    page = client.get(f"/snapshots/{pdf.id}?page=3").text
    assert f'href="/snapshots/{pdf.id}/raw#page=3"' in page
    assert client.get(f"/snapshots/{pdf.id}/raw").headers["content-type"] == "application/pdf"

    js = snap(db, store, source, b'{"rates": 0.054}', "application/json")
    assert '"rates": 0.054' in unescape(client.get(f"/snapshots/{js.id}").text)
    assert client.get("/snapshots/999999").status_code == 404


def test_audit_page_and_log_is_append_only(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(12, "5.90")])
    client.post(f"/tasks/{task_id}/needs-fix", headers=HX, data={"note": "bảng lệch cột"})

    html = client.get("/audit").text
    assert "needs_fix" in html and "bảng lệch cột" in html and "VIDU" in html

    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(update(ReviewAction).values(note="sửa lại"))


def test_site_webhook() -> None:
    import httpx

    from review_app.webhook import notify_site

    seen: list[httpx.Request] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"revalidated": True})

    settings = Settings(
        site_revalidate_url="http://web:3000/api/revalidate", site_revalidate_secret="s3"
    )
    assert notify_site(settings, httpx.MockTransport(ok)) is True
    assert seen[0].headers["X-Soivi-Secret"] == "s3"
    assert notify_site(Settings(site_revalidate_url=""), httpx.MockTransport(ok)) is False

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert notify_site(settings, httpx.MockTransport(down)) is False  # never raises
    assert notify_site(settings, httpx.MockTransport(lambda r: httpx.Response(401))) is False


def test_approving_calls_the_site(
    client: TestClient,
    db: Session,
    store: MemoryStore,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("review_app.app.notify_site", lambda s: calls.append("approved"))
    task_id = make_task(db, store, source, [rate(12, "5.90")])
    client.post(f"/tasks/{task_id}/reject-all", headers=HX)
    assert calls == []  # rejecting publishes nothing
    other = make_task(db, store, source, [rate(12, "6.10")])
    client.post(f"/tasks/{other}/approve-all", headers=HX)
    assert calls == ["approved"]


def test_retire_takes_a_live_value_down_with_a_note(
    client: TestClient, db: Session, store: MemoryStore, source: Source
) -> None:
    task_id = make_task(db, store, source, [rate(12, "5.90")])
    client.post(f"/tasks/{task_id}/approve-all", headers=HX)
    [live] = versions(db)
    url = f"/tasks/{task_id}/versions/savings_rate/{live.id}/retire"
    page = client.get(f"/tasks/{task_id}").text
    assert f"{url}" in page  # the "Gỡ" form is offered on a live value

    assert client.post(url, headers=HX, data={"note": " "}).status_code == 409  # needs a reason
    reply = client.post(url, headers=HX, data={"note": "ngân hàng không còn công bố"})
    assert reply.status_code == 200 and "Gỡ" not in reply.text  # nothing left to take down

    db.refresh(live)
    assert live.status is VersionStatus.APPROVED and live.valid_to is not None  # history kept
    key = {c: getattr(live, c) for c in SAVINGS_RATE_KEY}
    assert get_current(db, SavingsRate, **key) is None
    last = actions(db)[-1]
    assert (last.action.value, last.version_ids, last.note) == (
        "retire",
        [live.id],
        "ngân hàng không còn công bố",
    )
    assert client.post(url, headers=HX, data={"note": "again"}).status_code == 409
