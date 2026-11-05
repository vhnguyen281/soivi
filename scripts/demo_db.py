"""Build a throwaway `soivi_demo` database with FICTIONAL banks and cards, for local
work on the public site (web/). Never point production at it.

    uv run python scripts/demo_db.py            # (re)creates soivi_demo
    DATABASE_URL=...soivi_demo API_PORT=8012 uv run python -m api

Every institution is called "Ngân hàng Demo ..." and every URL is on example.com,
so nothing here can be mistaken for a real bank's rate. Values are approved by the
reviewer "demo" through core/versioning, exactly as the review app would.
"""

import datetime as dt
from decimal import Decimal
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import (
    CardNetwork,
    CardType,
    Channel,
    ExtractionMethod,
    FetchMethod,
    InstitutionType,
    InterestPayment,
    RewardCategory,
    RewardType,
    SourceKind,
)
from core.models import (
    CardPerk,
    CardProduct,
    CardReward,
    CardTerms,
    Institution,
    SavingsRate,
    Snapshot,
    Source,
    Versioned,
)
from core.versioning import approve_version, propose_version

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)
DAY = dt.timedelta(days=1)


def recreate() -> str:
    url = make_url(get_settings().database_url).set(database="soivi_demo")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text('DROP DATABASE IF EXISTS "soivi_demo" WITH (FORCE)'))
        conn.execute(text('CREATE DATABASE "soivi_demo"'))
    admin.dispose()
    rendered = url.render_as_string(hide_password=False)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    command.upgrade(cfg, "head")
    return rendered


def snapshot(db: Session, source: Source, at: dt.datetime, n: int, url: str) -> Snapshot:
    s = Snapshot(
        source_id=source.id,
        url=url,
        fetched_at=at,
        http_status=200,
        content_type="application/pdf" if url.endswith(".pdf") else "text/html",
        sha256=f"{n:064x}",
        storage_key=f"demo/{n}",
        size_bytes=1,
    )
    db.add(s)
    db.flush()
    return s


def put(
    db: Session,
    model: type[Versioned],
    data: dict[str, Any],
    snap: Snapshot,
    at: dt.datetime,
    method: ExtractionMethod = ExtractionMethod.HTML,
    **kw: Any,
) -> None:
    v = propose_version(
        db, model, data, snapshot_id=snap.id, extraction_method=method, now=at, **kw
    ).version
    if v.status.value == "pending":
        approve_version(db, model, v.id, reviewer="demo", now=at)


def rate(inst: Institution, months: int, pct: str, **kw: Any) -> dict[str, Any]:
    data = {
        "institution_id": inst.id,
        "region": "",
        "product_name": "Tiết kiệm thường",
        "channel": Channel.COUNTER,
        "term_months": months,
        "term_days": 0,
        "min_amount_vnd": 0,
        "interest_payment": InterestPayment.END,
        "rate_pct": Decimal(pct),
        "conditions_text": None,
        "is_cd": False,
    }
    data.update(kw)
    return data


def main() -> None:
    url = recreate()
    engine = create_engine(url)
    n = 0
    with Session(engine) as db:
        banks = []
        for i, (short, name, stale) in enumerate(
            [
                ("DEMOA", "Ngân hàng Demo An Bình Giả Lập", False),
                ("DEMOB", "Ngân hàng Demo Bắc Ví Dụ", False),
                ("DEMOC", "Ngân hàng Demo Cũ (nguồn quá hạn)", True),
            ]
        ):
            inst = Institution(
                legal_name_vi=name,
                short_name=short,
                type=InstitutionType.JOINT_STOCK_BANK,
                website=f"https://{short.lower()}.example.com",
                deposit_insurance=True,
            )
            db.add(inst)
            db.flush()
            src = Source(
                institution_id=inst.id,
                kind=SourceKind.SAVINGS_RATE_PAGE,
                url=f"https://{short.lower()}.example.com/lai-suat",
                fetch_method=FetchMethod.HTTP,
                cadence_hours=12,
                adapter_name="demo",
                last_success_at=NOW - (10 * DAY if stale else dt.timedelta(hours=2)),
            )
            db.add(src)
            db.flush()
            banks.append((inst, src, i))

        terms = [1, 3, 6, 12, 24, 36]
        base = {1: 3.6, 3: 3.9, 6: 5.0, 12: 5.6, 24: 5.8, 36: 5.9}
        for inst, src, i in banks:
            page = f"https://{inst.short_name.lower()}.example.com/lai-suat"
            weeks_ago = [10, 6, 3, 1]
            for step, w in enumerate(weeks_ago):
                n += 1
                at = NOW - w * 7 * DAY
                snap = snapshot(db, src, at, n, page)
                bump = (step - 1) * 0.1 + i * 0.15
                for m in terms:
                    for channel, extra in ((Channel.COUNTER, 0.0), (Channel.ONLINE, 0.2)):
                        put(
                            db,
                            SavingsRate,
                            rate(
                                inst,
                                m,
                                f"{base[m] + bump + extra:.2f}",
                                channel=channel,
                                conditions_text="Mức lãi suất tối đa" if m >= 24 else None,
                            ),
                            snap,
                            at,
                            effective_from=(at - 2 * DAY).date(),
                        )
                    put(
                        db,
                        SavingsRate,
                        rate(
                            inst,
                            m,
                            f"{base[m] + bump - 0.2:.2f}",
                            interest_payment=InterestPayment.MONTHLY,
                        ),
                        snap,
                        at,
                    )
            put(
                db,
                SavingsRate,
                rate(
                    inst,
                    12,
                    f"{base[12] + 0.5:.2f}",
                    min_amount_vnd=1_000_000_000,
                    product_name="Tiết kiệm VIP",
                    conditions_text="Chỉ áp dụng cho khách hàng mới mở tài khoản lần đầu",
                ),
                snap,
                NOW - 7 * DAY,
            )

        inst, _, _ = banks[0]
        card_src = Source(
            institution_id=inst.id,
            kind=SourceKind.CARD_TARIFF_PDF,
            url="https://demoa.example.com/bieu-phi-the.pdf",
            fetch_method=FetchMethod.PDF,
            cadence_hours=168,
            adapter_name="demo",
            last_success_at=NOW - DAY,
        )
        db.add(card_src)
        db.flush()
        n += 1
        snap = snapshot(db, card_src, NOW - 2 * DAY, n, card_src.url or "")
        for name, fee, fx, waiver, cashback in [
            ("Demo Visa Signature", 1_499_000, "1.1", 250_000_000, "10"),
            ("Demo Visa Classic", 300_000, "2.95", 80_000_000, None),
        ]:
            card = CardProduct(
                institution_id=inst.id,
                name=name,
                network=CardNetwork.VISA,
                card_type=CardType.CREDIT,
            )
            db.add(card)
            db.flush()
            q = f"Thẻ tín dụng {name} | {fee:,} VND/thẻ".replace(",", ".")
            put(
                db,
                CardTerms,
                {
                    "card_product_id": card.id,
                    "annual_fee_primary_vnd": fee,
                    "annual_fee_supp_vnd": fee,
                    "fee_waiver_rule_text": None,
                    "fee_waiver_spend_vnd": waiver,
                    "interest_rate_pct": None,
                    "interest_free_days": None,
                    "cash_advance_pct": Decimal("4"),
                    "cash_advance_min_vnd": 100_000,
                    "fx_fee_pct": Decimal(fx),
                    "late_fee_pct": Decimal("6"),
                    "late_fee_min_vnd": 150_000,
                    "min_monthly_income_vnd": None,
                },
                snap,
                NOW - DAY,
                ExtractionMethod.LLM,
                evidence={
                    "annual_fee_primary_vnd": {"page": 1, "quote": q, "value": f"{fee:,} VND/thẻ"},
                    "fx_fee_pct": {
                        "page": 2,
                        "quote": f"Thẻ tín dụng {name} | {fx}%*số tiền giao dịch",
                        "value": f"{fx}%*số tiền giao dịch",
                    },
                },
            )
            if cashback:
                for cat in (RewardCategory.DINING, RewardCategory.TRAVEL):
                    put(
                        db,
                        CardReward,
                        {
                            "card_product_id": card.id,
                            "category": cat,
                            "reward_type": RewardType.CASHBACK,
                            "rate_pct": Decimal(cashback),
                            "points_per_spend": None,
                            "spend_unit_vnd": None,
                            "monthly_cap_vnd": 5_000_000,
                            "conditions_text": None,
                        },
                        snap,
                        NOW - DAY,
                        ExtractionMethod.LLM,
                    )
                put(
                    db,
                    CardPerk,
                    {
                        "card_product_id": card.id,
                        "lounge_visits_per_year": 4,
                        "lounge_unlimited": False,
                        "travel_insurance": True,
                        "travel_insurance_cover_vnd": None,
                        "other_perks_text": "Phòng chờ sân bay",
                    },
                    snap,
                    NOW - DAY,
                    ExtractionMethod.LLM,
                )
        db.commit()
    print(f"soivi_demo ready ({url.split('@')[-1]})")


if __name__ == "__main__":
    main()
