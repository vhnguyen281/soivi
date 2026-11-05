"""End-to-end pipeline runs: local HTTP server -> adapter -> MemoryStore + test DB.

No real network, no MinIO.
"""

import datetime as dt
import hashlib
import itertools
import re
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from core.enums import FetchMethod, InstitutionType, SourceKind, VersionStatus
from core.models import Institution, ReviewTask, SavingsRate, Snapshot, Source
from pipeline.__main__ import main
from pipeline.adapters.base import AdapterBroken, AdapterContext, BaseAdapter
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import PoliteHttp
from pipeline.fetch.storage import MemoryStore
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register, unregister
from pipeline.runner import due_sources, institution_sources, run_source
from tests.http_fixture import FixtureServer, Reply

pytestmark = pytest.mark.db

PAGE = """<html><body><table id="rates">
<tr><td>1</td><td>4,50</td></tr>
<tr><td>12</td><td>5,90</td></tr>
</table></body></html>"""


class TestSavingsAdapter(BaseAdapter):
    """Reads <tr><td>term</td><td>rate</td></tr> rows. Raises if the table is missing."""

    __test__ = False  # not a pytest class
    name = "test_vidu_savings"
    institution = "VIDU"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP
    parse_calls = 0

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        cls.parse_calls += 1
        html = content.decode("utf-8")
        if 'id="rates"' not in html:
            raise AdapterBroken("rates table not found")
        rows = re.findall(r"<tr><td>(\d+)</td><td>([\d,]+)</td></tr>", html)
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
def registered() -> Iterator[None]:
    register(TestSavingsAdapter)
    TestSavingsAdapter.parse_calls = 0
    yield
    unregister(TestSavingsAdapter.name)


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


_variants = itertools.count()


def make_source(db: Session, bank: Institution, url: str | None, **kw: object) -> Source:
    values: dict[str, object] = {
        "variant": f"v{next(_variants)}",  # one bank, several sources of one kind
        "institution_id": bank.id,
        "kind": SourceKind.SAVINGS_RATE_PAGE,
        "url": url,
        "fetch_method": FetchMethod.HTTP,
        "cadence_hours": 12,
        "adapter_name": TestSavingsAdapter.name,
    }
    values.update(kw)
    src = Source(**values)
    db.add(src)
    db.flush()
    return src


@pytest.fixture
def source(db: Session, bank: Institution, http_server: FixtureServer) -> Source:
    http_server.route("/lai-suat", body=PAGE)
    return make_source(db, bank, http_server.url("/lai-suat"))


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def ctx(db: Session, polite: PoliteHttp, store: MemoryStore) -> AdapterContext:
    return AdapterContext(session=db, fetchers=Fetchers(polite), store=store)


def snapshots(db: Session, source: Source) -> list[Snapshot]:
    return list(
        db.scalars(select(Snapshot).where(Snapshot.source_id == source.id).order_by(Snapshot.id))
    )


# --------------------------------------------------------------------------- run_source


def test_first_run_stores_snapshot_and_parses(
    db: Session, ctx: AdapterContext, source: Source, store: MemoryStore
) -> None:
    result = run_source(ctx, source)

    assert result.status == "parsed", result.error
    assert [(r.term_months, r.rate_pct) for r in result.records] == [  # type: ignore[attr-defined]
        (1, Decimal("4.50")),
        (12, Decimal("5.90")),
    ]
    [snap] = snapshots(db, source)
    sha = hashlib.sha256(PAGE.encode()).hexdigest()
    assert snap.sha256 == sha
    assert snap.unchanged is False
    assert snap.http_status == 200 and snap.size_bytes == len(PAGE.encode())
    today = snap.fetched_at.astimezone(dt.UTC).date().isoformat()
    assert snap.storage_key == f"VIDU/savings_rate_page/{today}/{sha}.html"
    assert store.get(snap.storage_key) == PAGE.encode()
    assert source.last_success_at == snap.fetched_at
    assert source.robots_ok is True and source.consecutive_failures == 0
    # the diff step ran: both rates are pending under one review task for this snapshot
    assert result.diff is not None and result.diff.new == 2
    pending = db.scalars(select(SavingsRate)).all()
    assert {v.status for v in pending} == {VersionStatus.PENDING}
    [task] = db.scalars(select(ReviewTask)).all()
    assert task.snapshot_id == snap.id and {v.review_task_id for v in pending} == {task.id}


def test_same_bytes_are_marked_unchanged_and_not_parsed(
    db: Session, ctx: AdapterContext, source: Source, store: MemoryStore
) -> None:
    run_source(ctx, source)
    second = run_source(ctx, source)

    assert second.status == "unchanged"
    assert TestSavingsAdapter.parse_calls == 1
    first, again = snapshots(db, source)
    assert again.unchanged is True and again.sha256 == first.sha256
    assert store.puts == 1  # same key today: bytes not uploaded twice


def test_changed_page_is_parsed_again(
    db: Session, ctx: AdapterContext, source: Source, http_server: FixtureServer
) -> None:
    run_source(ctx, source)
    http_server.route("/lai-suat", body=PAGE.replace("5,90", "6,10"))
    result = run_source(ctx, source)

    assert result.status == "parsed"
    assert result.records[-1].rate_pct == Decimal("6.10")  # type: ignore[attr-defined]
    assert [s.unchanged for s in snapshots(db, source)] == [False, False]


def test_reparse_parses_unchanged_page(ctx: AdapterContext, source: Source) -> None:
    run_source(ctx, source)
    result = run_source(ctx, source, reparse=True)
    assert result.status == "parsed"
    assert TestSavingsAdapter.parse_calls == 2


def test_fetch_failure_counts_and_writes_nothing(
    db: Session, ctx: AdapterContext, bank: Institution, http_server: FixtureServer
) -> None:
    src = make_source(db, bank, http_server.url("/gone"))
    result = run_source(ctx, src)

    assert result.status == "fetch_failed"
    assert "HTTP 404" in (result.error or "")
    assert src.consecutive_failures == 1
    assert snapshots(db, src) == []


def test_robots_block_is_recorded(
    db: Session, ctx: AdapterContext, bank: Institution, http_server: FixtureServer
) -> None:
    src = make_source(db, bank, http_server.url("/private/lai-suat"))
    result = run_source(ctx, src)
    assert result.status == "fetch_failed"
    assert src.robots_ok is False


def test_parse_error_keeps_the_snapshot(
    db: Session, ctx: AdapterContext, source: Source, http_server: FixtureServer
) -> None:
    http_server.route("/lai-suat", body="<html>Bảo trì hệ thống</html>")
    result = run_source(ctx, source)

    assert result.status == "parse_failed"
    assert "rates table not found" in (result.error or "")
    assert len(snapshots(db, source)) == 1  # evidence kept
    # Fetched but unreadable still counts as a failure: the data isn't being refreshed.
    assert source.consecutive_failures == 1
    assert source.last_success_at is None
    assert source.last_status == "parse_failed" and result.adapter_broken


def test_empty_parse_is_a_failure(
    ctx: AdapterContext, source: Source, http_server: FixtureServer
) -> None:
    http_server.route("/lai-suat", body='<table id="rates"></table>')
    result = run_source(ctx, source)
    assert result.status == "parse_failed"
    assert "no records" in (result.error or "")


def test_adapter_must_match_source(db: Session, ctx: AdapterContext, bank: Institution) -> None:
    src = make_source(db, bank, "http://127.0.0.1:1/x", kind=SourceKind.CARD_TARIFF_PDF)
    result = run_source(ctx, src)
    assert result.status == "fetch_failed"
    assert "AdapterError" in (result.error or "") and "kind is 'card_tariff_pdf'" in (
        result.error or ""
    )


def test_unknown_adapter_fails_cleanly(db: Session, ctx: AdapterContext, bank: Institution) -> None:
    src = make_source(db, bank, "http://127.0.0.1:1/x", adapter_name="nope")
    result = run_source(ctx, src)
    assert result.status == "fetch_failed"
    assert "no adapter registered as 'nope'" in (result.error or "")


def test_server_error_then_success(
    db: Session, ctx: AdapterContext, source: Source, http_server: FixtureServer
) -> None:
    http_server.route("/lai-suat", Reply(503), Reply(200, PAGE))
    assert run_source(ctx, source).status == "parsed"


# --------------------------------------------------------------------------- selection


def test_due_sources(db: Session, bank: Institution) -> None:
    # 12:00 UTC = 19:00 in Vietnam; the latest savings slot was 15:00 VN = 08:00 UTC.
    now = dt.datetime(2026, 10, 26, 12, tzinfo=dt.UTC)
    slot = dt.datetime(2026, 10, 26, 8, tzinfo=dt.UTC)
    never = make_source(db, bank, "https://a.vn/1")
    fresh = make_source(
        db,
        bank,
        "https://a.vn/2",
        last_attempt_at=slot + dt.timedelta(minutes=5),
        last_status="parsed",
    )
    stale = make_source(
        db,
        bank,
        "https://a.vn/3",
        last_attempt_at=slot - dt.timedelta(hours=8),
        last_status="parsed",
    )
    make_source(db, bank, None, needs_check=True)
    make_source(db, bank, "https://a.vn/5", needs_check=True)
    make_source(db, bank, "https://a.vn/6", adapter_name=None)
    make_source(db, bank, "https://a.vn/7", active=False)

    due = due_sources(db, now)
    assert [s.id for s in due] == [never.id, stale.id]
    assert fresh not in due


def test_institution_sources(db: Session, bank: Institution) -> None:
    ok = make_source(db, bank, "https://a.vn/1")
    make_source(db, bank, "https://a.vn/2", needs_check=True)
    assert institution_sources(db, "VIDU") == [ok]
    with pytest.raises(LookupError):
        institution_sources(db, "NOPE")


# --------------------------------------------------------------------------- CLI


@pytest.fixture
def cli(db: Session, polite: PoliteHttp, store: MemoryStore):  # type: ignore[no-untyped-def]
    conn = db.connection()
    assert isinstance(conn, Connection)

    def run(*argv: str) -> int:
        return main(
            list(argv),
            session_factory=lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
            fetchers_factory=lambda: Fetchers(polite),
            store_factory=lambda: store,
        )

    return run


def test_cli_run_source(
    cli, db: Session, source: Source, capsys: pytest.CaptureFixture[str]
) -> None:  # type: ignore[no-untyped-def]
    db.commit()  # make fixtures visible to the CLI's sessions (still inside the test transaction)
    assert cli("run", "--source", str(source.id)) == 0
    out = capsys.readouterr()
    assert "[parsed]" in out.out and "VIDU/savings_rate_page" in out.out
    assert "1 sources, 0 failed" in out.err
    assert db.scalar(select(func.count()).select_from(Snapshot)) == 1


def test_cli_institution_and_all_due(cli, db: Session, source: Source) -> None:  # type: ignore[no-untyped-def]
    db.commit()
    assert cli("run", "--institution", "VIDU") == 0
    # just fetched, so nothing is due any more
    assert cli("run", "--all-due") == 0
    assert db.scalar(select(func.count()).select_from(Snapshot)) == 1


def test_cli_reports_failures(
    cli, db: Session, bank: Institution, http_server: FixtureServer
) -> None:  # type: ignore[no-untyped-def]
    src = make_source(db, bank, http_server.url("/gone"))
    db.commit()
    assert cli("run", "--source", str(src.id)) == 1


def test_cli_unknown_targets(cli, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    assert cli("run", "--source", "999999") == 2
    assert cli("run", "--institution", "NOPE") == 2
    assert "no institution 'NOPE'" in capsys.readouterr().err


def test_cli_requires_one_target() -> None:
    with pytest.raises(SystemExit):
        main(["run"])
    with pytest.raises(SystemExit):
        main(["run", "--source", "1", "--all-due"])


def test_cli_lists_adapters(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["adapters"]) == 0
    assert "test_vidu_savings: VIDU/savings_rate_page via http" in capsys.readouterr().out


def test_cli_status(cli, db: Session, source: Source, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    db.commit()
    assert cli("status") == 0
    out = capsys.readouterr().out
    assert "VIDU" in out and "unverified" in out and "never fetched successfully" in out
    assert cli("run", "--source", str(source.id)) == 0
    capsys.readouterr()
    assert cli("status") == 0
    assert "VIDU               verified" in capsys.readouterr().out
