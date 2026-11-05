"""Alerts, daily summary, Telegram, scheduler tick, /health."""

import datetime as dt
import json
import threading
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import FetchMethod, InstitutionType, SourceKind
from core.models import Institution, Notification, PipelineRun, Snapshot, Source
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import PoliteHttp
from pipeline.fetch.storage import MemoryStore
from pipeline.monitor import alert_for, daily_summary, summary_due
from pipeline.notify import PrintNotifier, TelegramNotifier, notify
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register, unregister
from pipeline.runner import RunResult
from pipeline.scheduler import LockBusy, single_run, tick
from review_app.app import create_app
from tests.http_fixture import FixtureServer

pytestmark = pytest.mark.db

VN = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.UTC)  # 19:00 in Vietnam


class Recording:
    channel = "test"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(text)


# --------------------------------------------------------------------------- alerts


def result(status: str, error: str | None = None) -> RunResult:
    r = RunResult(7, "VIDU/savings_rate_page", status)  # type: ignore[arg-type]
    r.error = error
    return r


def test_alert_when_an_adapter_breaks() -> None:
    kind, text = alert_for(result("parse_failed", "AdapterBroken: table <b> missing"), "parsed")  # type: ignore[misc]
    assert kind == "adapter_broken"
    assert "VIDU/savings_rate_page" in text and "&lt;b&gt;" in text  # escaped for Telegram HTML


def test_no_repeat_while_still_broken_and_note_on_recovery() -> None:
    assert alert_for(result("parse_failed", "x"), "parse_failed") is None
    assert alert_for(result("diff_failed", "x"), "parse_failed") is None
    kind, _ = alert_for(result("unchanged"), "parse_failed")  # type: ignore[misc]
    assert kind == "adapter_recovered"
    assert (
        alert_for(result("fetch_failed", "timeout"), "parsed") is None
    )  # staleness covers fetches
    assert alert_for(result("parsed"), None) is None


# --------------------------------------------------------------------------- data helpers


@pytest.fixture
def bank(db: Session) -> Institution:
    inst = Institution(
        legal_name_vi="Ngân hàng Ví Dụ", short_name="VIDU", type=InstitutionType.JOINT_STOCK_BANK
    )
    db.add(inst)
    db.flush()
    return inst


def make_source(db: Session, bank: Institution, url: str, **kw: Any) -> Source:
    values: dict[str, Any] = {
        "institution_id": bank.id,
        "kind": SourceKind.SAVINGS_RATE_PAGE,
        "url": url,
        "fetch_method": FetchMethod.HTTP,
        "cadence_hours": 12,
        "adapter_name": "monitor_test_adapter",
    }
    values.update(kw)
    s = Source(**values)
    db.add(s)
    db.flush()
    return s


# --------------------------------------------------------------------------- summary


def test_daily_summary_content(db: Session, bank: Institution) -> None:
    ok = make_source(
        db, bank, "https://a.vn/1", last_success_at=NOW, last_attempt_at=NOW, last_status="parsed"
    )
    broken = make_source(
        db,
        bank,
        "https://a.vn/2",
        variant="online",
        last_status="parse_failed",
        last_error="AdapterBroken: rates table not found",
        consecutive_failures=2,
        last_success_at=NOW - dt.timedelta(days=3),
    )
    for source, status, new in [
        (ok, "parsed", 3),
        (ok, "unchanged", 0),
        (broken, "parse_failed", 0),
    ]:
        db.add(
            PipelineRun(
                source_id=source.id,
                started_at=NOW - dt.timedelta(hours=2),
                finished_at=NOW - dt.timedelta(hours=2),
                status=status,
                new=new,
                changed=1 if new else 0,
            )
        )
    db.add(
        PipelineRun(
            source_id=ok.id,
            started_at=NOW - dt.timedelta(days=2),
            finished_at=NOW - dt.timedelta(days=2),
            status="parsed",
            new=99,
        )
    )  # too old
    db.flush()

    text = daily_summary(db, NOW, VN)

    assert "tóm tắt 28/10/2026" in text
    assert "Lượt chạy: 3 (parse_failed 1, parsed 1, unchanged 1)" in text
    assert "Thay đổi tìm thấy: 3 mới, 1 đổi, 0 mất" in text
    assert "Adapter hỏng: 1" in text and "VIDU/savings_rate_page/online: AdapterBroken" in text
    assert "Chưa xác minh (nguồn quá hạn): VIDU" in text


def test_summary_once_a_day_from_19h(db: Session) -> None:
    assert not summary_due(db, NOW - dt.timedelta(hours=1), VN, 19)  # 18:00 VN
    assert summary_due(db, NOW, VN, 19)
    notify(db, Recording(fail=True), "daily_summary", "x", now=NOW)
    assert not summary_due(db, NOW + dt.timedelta(minutes=10), VN, 19)  # back off after a failure
    assert summary_due(db, NOW + dt.timedelta(minutes=40), VN, 19)
    notify(db, Recording(), "daily_summary", "x", now=NOW + dt.timedelta(minutes=40))
    assert not summary_due(db, NOW + dt.timedelta(hours=3), VN, 19)
    assert summary_due(db, NOW + dt.timedelta(days=1), VN, 19)  # tomorrow 19:00


def test_notify_records_every_attempt(db: Session) -> None:
    assert notify(db, Recording(), "adapter_broken", "hello", now=NOW)
    assert not notify(db, Recording(fail=True), "adapter_broken", "hello", now=NOW)
    rows = db.scalars(select(Notification).order_by(Notification.id)).all()
    assert [(r.ok, r.error) for r in rows] == [(True, None), (False, "telegram down")]


# --------------------------------------------------------------------------- Telegram


def test_telegram_sends_html_message() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    TelegramNotifier("123:ABC", "42", transport=httpx.MockTransport(handler)).send("<b>hi</b>")
    [request] = seen
    assert request.url == "https://api.telegram.org/bot123:ABC/sendMessage"
    body = json.loads(request.content)
    assert body == {
        "chat_id": "42",
        "text": "<b>hi</b>",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def test_telegram_errors_never_leak_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    with pytest.raises(RuntimeError) as exc:
        TelegramNotifier("123:SECRET", "42", transport=httpx.MockTransport(handler)).send("x")
    assert "Unauthorized" in str(exc.value) and "SECRET" not in str(exc.value)


def test_no_token_means_print(capsys: pytest.CaptureFixture[str]) -> None:
    from pipeline.notify import make_notifier

    notifier = make_notifier(Settings(telegram_bot_token="", telegram_chat_id=""))
    assert isinstance(notifier, PrintNotifier)
    notifier.send("xin chào")
    assert "[notify] xin chào" in capsys.readouterr().out


# --------------------------------------------------------------------------- scheduler tick


class FlakyAdapter(BaseAdapter):
    __test__ = False
    name = "monitor_test_adapter"
    institution = "VIDU"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        if b"rates" not in content:
            raise AdapterBroken("rates table not found")
        return [
            SavingsRateRecord(
                product_name="Tiết kiệm",
                channel="counter",
                term_months=12,
                interest_payment="end",
                rate_pct=Decimal("5.90"),
            )
        ]


@pytest.fixture
def adapter() -> Iterator[None]:
    register(FlakyAdapter)
    yield
    unregister(FlakyAdapter.name)


def test_tick_runs_due_sources_alerts_and_summarises(
    db: Session,
    bank: Institution,
    adapter: None,
    http_server: FixtureServer,
    polite: PoliteHttp,
    tmp_path: Any,
) -> None:
    http_server.route("/rates", body="<p>rates</p>")
    http_server.route("/broken", body="<p>Bảo trì</p>")
    good = make_source(db, bank, http_server.url("/rates"), variant="a")
    bad = make_source(db, bank, http_server.url("/broken"), variant="b", last_status="parsed")
    db.commit()  # visible to the tick's sessions (still inside the test transaction)
    conn = db.connection()
    assert isinstance(conn, Connection)

    notifier = Recording()
    settings = Settings(pipeline_lock_file=str(tmp_path / "lock"), daily_summary_hour=19)
    out = tick(
        settings,
        lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        lambda: Fetchers(polite),
        MemoryStore(),
        notifier,
        clock=lambda: NOW,
    )

    assert [r.status for r in out.results] == ["parsed", "parse_failed"]
    assert out.alerts == ["adapter_broken"] and out.summary_sent
    assert "Adapter hỏng" in notifier.sent[0] and "rates table not found" in notifier.sent[0]
    assert "tóm tắt" in notifier.sent[1]
    db.expire_all()
    assert (good.last_status, good.consecutive_failures) == ("parsed", 0)
    good_snap = db.scalar(select(Snapshot).where(Snapshot.source_id == good.id))
    assert (
        good_snap is not None and good.last_success_at == good_snap.fetched_at
    )  # real capture time
    assert good.last_attempt_at == NOW
    assert (bad.last_status, bad.consecutive_failures) == ("parse_failed", 1)
    runs = db.scalars(select(PipelineRun).order_by(PipelineRun.id)).all()
    assert [(r.status, r.trigger, r.new) for r in runs] == [
        ("parsed", "schedule", 1),
        ("parse_failed", "schedule", 0),
    ]
    assert (
        db.scalar(select(Snapshot).where(Snapshot.source_id == bad.id)) is not None
    )  # evidence kept

    # Same slot again: nothing due, no repeat alert, summary already sent today.
    again = tick(
        settings,
        lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        lambda: Fetchers(polite),
        MemoryStore(),
        notifier,
        clock=lambda: NOW,
    )
    assert again.results == [] and again.alerts == [] and not again.summary_sent
    assert len(notifier.sent) == 2


def test_ticks_never_overlap(tmp_path: Any) -> None:
    lock = str(tmp_path / "lock")
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with single_run(lock):
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    with pytest.raises(LockBusy), single_run(lock):
        pass
    release.set()
    t.join()
    with single_run(lock):  # free again
        pass


# --------------------------------------------------------------------------- /health


def test_health_endpoint(db: Session, bank: Institution) -> None:
    fresh = make_source(
        db,
        bank,
        "https://a.vn/1",
        variant="a",
        last_status="parsed",
        last_attempt_at=NOW,
        last_success_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=3),
    )
    broken = make_source(
        db,
        bank,
        "https://a.vn/2",
        variant="b",
        last_status="parse_failed",
        last_error="AdapterBroken: x",
        last_success_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=3),
    )
    unmonitored = make_source(db, bank, None, variant="c", needs_check=True)
    db.commit()
    conn = db.connection()
    assert isinstance(conn, Connection)
    app = create_app(
        Settings(review_username="r", review_password="p"),
        session_factory=lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        store=MemoryStore(),
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 401
        client.auth = ("r", "p")
        report = client.get("/health").json()
        assert client.get("/health?strict=1").status_code == 503

    assert report["status"] == "degraded" and report["problems"] == 1
    by_id = {s["id"]: s for s in report["sources"]}
    assert (
        by_id[fresh.id]["state"] == "ok" and 2.9 < by_id[fresh.id]["last_success_age_hours"] < 3.2
    )
    assert by_id[fresh.id]["next_run"] is not None
    assert (
        by_id[broken.id]["state"] == "broken"
        and by_id[broken.id]["last_error"] == "AdapterBroken: x"
    )
    assert (
        by_id[unmonitored.id]["state"] == "not_monitored"
        and by_id[unmonitored.id]["next_run"] is None
    )
