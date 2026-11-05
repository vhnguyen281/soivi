"""Tests for core/seed.py and the real files in data/seeds/."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Institution, Source
from core.seed import (
    INSTITUTION_COLUMNS,
    SEEDS_DIR,
    SOURCE_COLUMNS,
    SeedError,
    load_all,
    parse_institutions,
    parse_sources,
)

INST_HEADER = ",".join(INSTITUTION_COLUMNS)
SRC_HEADER = ",".join(SOURCE_COLUMNS)

GOOD_INST = (
    "VCB,Ngân hàng TMCP Ngoại thương Việt Nam,state_bank,https://www.vietcombank.com.vn,false,\n"
    "FEC,Công ty Tài chính TNHH Ngân hàng Việt Nam Thịnh Vượng SMBC,consumer_finance,"
    "https://fecredit.com.vn/,false,\n"
)
GOOD_SRC = (
    "VCB,savings_rate_page,,https://www.vietcombank.com.vn/lai-suat,http,12,,false,\n"
    "VCB,card_tariff_pdf,,,pdf,168,,true,not found yet\n"
)


def write_seeds(tmp_path: Path, inst: str = GOOD_INST, src: str = GOOD_SRC) -> Path:
    (tmp_path / "institutions.csv").write_text(f"{INST_HEADER}\n{inst}", encoding="utf-8")
    (tmp_path / "sources.csv").write_text(f"{SRC_HEADER}\n{src}", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- the real files


def test_real_seed_files_are_valid() -> None:
    institutions = parse_institutions(SEEDS_DIR / "institutions.csv")
    sources = parse_sources(SEEDS_DIR / "sources.csv", (r["short_name"] for r in institutions))
    assert len(institutions) >= 40
    assert sources


def test_every_bank_has_both_source_kinds() -> None:
    institutions = parse_institutions(SEEDS_DIR / "institutions.csv")
    sources = parse_sources(SEEDS_DIR / "sources.csv", (r["short_name"] for r in institutions))
    have = {(s["institution"], s["kind"]) for s in sources}
    for inst in institutions:
        if inst["type"] != "consumer_finance":
            assert (inst["short_name"], "savings_rate_page") in have, inst["short_name"]
        assert (inst["short_name"], "card_tariff_pdf") in have or (
            inst["short_name"],
            "card_product_page",
        ) in have, inst["short_name"]


# --------------------------------------------------------------------------- parsing rules


def test_parses_good_rows(tmp_path: Path) -> None:
    d = write_seeds(tmp_path)
    rows = parse_institutions(d / "institutions.csv")
    assert rows[0]["deposit_insurance"] is True
    assert rows[1]["deposit_insurance"] is False  # finance companies can't take deposits
    src = parse_sources(d / "sources.csv", ["VCB", "FEC"])
    assert src[1]["url"] is None and src[1]["needs_check"] is True


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("X,Tên,state_bank,https://x.vn/ca-nhan/lai-suat,false,", "must be a homepage"),
        ("X,Tên,state_bank,,false,", "without website must have needs_check=true"),
        ("X,Tên,bank,https://x.vn,false,", "type must be one of"),
        ("X,Tên,state_bank,https://x.vn,maybe,", "needs_check must be true/false"),
        ("X,,state_bank,https://x.vn,false,", "legal_name_vi are required"),
    ],
)
def test_rejects_bad_institution(tmp_path: Path, row: str, message: str) -> None:
    d = write_seeds(tmp_path, inst=row + "\n")
    with pytest.raises(SeedError, match=message):
        parse_institutions(d / "institutions.csv")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("VCB,savings_rate_page,,,http,12,,false,", "without url must have needs_check=true"),
        ("NOPE,savings_rate_page,,https://a.vn/x,http,12,,false,", "unknown institution"),
        ("VCB,rates,,https://a.vn/x,http,12,,false,", "kind must be one of"),
        ("VCB,savings_rate_page,,https://a.vn/x,curl,12,,false,", "fetch_method must be one of"),
        ("VCB,savings_rate_page,,https://a.vn/x,http,0,,false,", "cadence_hours must be"),
        ("VCB,savings_rate_page,,ftp://a.vn/x,http,12,,false,", "url must be http"),
        ("VCB,savings_rate_page,,https://a.vn/x,http,12,nope,false,", "no adapter registered"),
    ],
)
def test_rejects_bad_source(tmp_path: Path, row: str, message: str) -> None:
    d = write_seeds(tmp_path, src=row + "\n")
    with pytest.raises(SeedError, match=message):
        parse_sources(d / "sources.csv", ["VCB"])


def test_rejects_duplicates(tmp_path: Path) -> None:
    line = "VCB,savings_rate_page,,https://a.vn/x,http,12,,false,\n"
    d = write_seeds(tmp_path, src=line + line)
    with pytest.raises(SeedError, match="duplicate source"):
        parse_sources(d / "sources.csv", ["VCB"])


def test_reports_all_errors_at_once(tmp_path: Path) -> None:
    d = write_seeds(tmp_path, inst="A,,bank,,x,\nB,,bank,,x,\n")
    with pytest.raises(SeedError) as exc:
        parse_institutions(d / "institutions.csv")
    assert len(exc.value.errors) >= 6


def test_rejects_wrong_header(tmp_path: Path) -> None:
    (tmp_path / "institutions.csv").write_text("name,type\nA,state_bank\n", encoding="utf-8")
    with pytest.raises(SeedError, match="header must be"):
        parse_institutions(tmp_path / "institutions.csv")


# --------------------------------------------------------------------------- loading


def count(db: Session, model: type[Institution] | type[Source]) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.db
def test_load_is_idempotent(db: Session, tmp_path: Path) -> None:
    d = write_seeds(tmp_path)

    first = load_all(db, d)
    assert (first["institutions"].inserted, first["sources"].inserted) == (2, 2)

    second = load_all(db, d)
    assert (second["institutions"].unchanged, second["sources"].unchanged) == (2, 2)
    assert second["institutions"].inserted == second["sources"].inserted == 0
    assert (count(db, Institution), count(db, Source)) == (2, 2)


@pytest.mark.db
def test_load_updates_changed_rows(db: Session, tmp_path: Path) -> None:
    load_all(db, write_seeds(tmp_path))
    found = GOOD_SRC.replace(
        ",,pdf,168,,true,not found yet", ",https://a.vn/phi.pdf,pdf,168,,false,"
    )
    result = load_all(db, write_seeds(tmp_path, src=found))

    assert result["sources"].updated == 1
    src = db.scalars(select(Source).where(Source.url == "https://a.vn/phi.pdf")).one()
    assert src.needs_check is False
    assert count(db, Source) == 2


@pytest.mark.db
def test_load_keeps_rows_missing_from_csv(db: Session, tmp_path: Path) -> None:
    load_all(db, write_seeds(tmp_path))
    only_vcb = GOOD_INST.splitlines()[0] + "\n"
    load_all(db, write_seeds(tmp_path, inst=only_vcb))
    assert count(db, Institution) == 2


@pytest.mark.db
def test_real_seed_loads(db: Session) -> None:
    load_all(db)
    again = load_all(db)
    assert again["institutions"].inserted == again["institutions"].updated == 0
    assert again["sources"].inserted == again["sources"].updated == 0


def test_rejects_wrong_field_count(tmp_path: Path) -> None:
    d = write_seeds(
        tmp_path, src="VCB,savings_rate_page,,https://a.vn/x,http,12,,false,a note, with comma\n"
    )
    with pytest.raises(SeedError, match="expected 9 fields"):
        parse_sources(d / "sources.csv", ["VCB"])
