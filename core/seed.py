"""Load seed data from data/seeds/ into the database. Run with `make seed`.

The CSV files are the source of truth for the rows they describe. Loading is
idempotent: rows are matched on a natural key and inserted or updated, so running
it twice changes nothing. Rows in the database that are not in the CSV are left
alone (never deleted).

- institutions.csv: matched on short_name
- sources.csv:      matched on (institution, kind, variant); `adapter` must be registered
- market_series.yaml (VNCMA): providers become `source` rows of kind market_data
                    (matched on variant = provider name); series matched on `code`

Every row is validated before anything is written. Any problem aborts the whole
load with a list of all errors, so the database never gets half a seed.
"""

import csv
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import DataGrade, FetchMethod, Frequency, InstitutionType, MonthEndRule, SourceKind
from core.models import Institution, MarketSeries, Source

SEEDS_DIR = Path(__file__).resolve().parent.parent / "data" / "seeds"

INSTITUTION_COLUMNS = ("short_name", "legal_name_vi", "type", "website", "needs_check", "note")
SOURCE_COLUMNS = (
    "institution",
    "kind",
    "variant",
    "url",
    "fetch_method",
    "cadence_hours",
    "adapter",
    "needs_check",
    "note",
)


class SeedError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("seed data is invalid:\n  " + "\n  ".join(errors))
        self.errors = errors


@dataclass
class Counts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    changes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.inserted} inserted, {self.updated} updated, {self.unchanged} unchanged"


# --------------------------------------------------------------------------- parsing


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    """Rows with their line numbers. Header must match `columns` exactly."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != columns:
            raise SeedError([f"{path.name}: header must be {','.join(columns)}"])
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise SeedError(
                    [
                        f"{path.name}:{reader.line_num}: expected {len(columns)} fields "
                        "(quote values that contain commas)"
                    ]
                )
            rows.append((reader.line_num, {k: v.strip() for k, v in row.items()}))
        return rows


def _parse_bool(value: str) -> bool | None:
    return {"true": True, "false": False, "": False}.get(value.lower())


# Root, or a country/language root such as https://www.sc.com/vn/
_HOMEPAGE_PATH = re.compile(r"^/?$|^/[a-z]{2}(-[a-z]{2})?/?$", re.IGNORECASE)


def _is_homepage(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.netloc)
        and bool(_HOMEPAGE_PATH.match(parts.path))
        and not parts.query
        and not parts.fragment
    )


def _is_http_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def parse_institutions(path: Path) -> list[dict[str, Any]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    types = {t.value for t in InstitutionType}

    for line, r in _read_csv(path, INSTITUTION_COLUMNS):
        where = f"{path.name}:{line}"
        needs_check = _parse_bool(r["needs_check"])
        if needs_check is None:
            errors.append(f"{where}: needs_check must be true/false, got {r['needs_check']!r}")
        if not r["short_name"] or not r["legal_name_vi"]:
            errors.append(f"{where}: short_name and legal_name_vi are required")
        if r["short_name"] in seen:
            errors.append(f"{where}: duplicate short_name {r['short_name']!r}")
        seen.add(r["short_name"])
        if r["type"] not in types:
            errors.append(f"{where}: type must be one of {sorted(types)}, got {r['type']!r}")
        if r["website"] and not _is_homepage(r["website"]):
            errors.append(f"{where}: website must be a homepage URL, got {r['website']!r}")
        if not r["website"] and not needs_check:
            errors.append(f"{where}: a row without website must have needs_check=true")

        rows.append(
            {
                "short_name": r["short_name"],
                "legal_name_vi": r["legal_name_vi"],
                "type": r["type"],
                "website": r["website"] or None,
                "needs_check": bool(needs_check),
                # Every bank that takes deposits from individuals must join the
                # deposit insurance scheme; finance companies cannot take them.
                "deposit_insurance": r["type"] != InstitutionType.CONSUMER_FINANCE,
            }
        )

    if errors:
        raise SeedError(errors)
    return rows


def parse_sources(
    path: Path, institutions: Iterable[str], adapters: Iterable[str] | None = None
) -> list[dict[str, Any]]:
    """`adapters`: registered adapter names; defaults to everything in pipeline/adapters."""
    if adapters is None:
        from pipeline.registry import all_adapters, load_adapters

        load_adapters()
        adapters = all_adapters()
    adapters = set(adapters)
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    known = set(institutions)
    seen_keys: set[tuple[str, str, str]] = set()
    seen_urls: set[tuple[str, str]] = set()
    kinds = {k.value for k in SourceKind}
    methods = {m.value for m in FetchMethod}

    for line, r in _read_csv(path, SOURCE_COLUMNS):
        where = f"{path.name}:{line}"
        needs_check = _parse_bool(r["needs_check"])
        if needs_check is None:
            errors.append(f"{where}: needs_check must be true/false, got {r['needs_check']!r}")
        if r["institution"] not in known:
            errors.append(f"{where}: unknown institution {r['institution']!r}")
        if r["kind"] not in kinds:
            errors.append(f"{where}: kind must be one of {sorted(kinds)}, got {r['kind']!r}")
        if r["fetch_method"] not in methods:
            errors.append(f"{where}: fetch_method must be one of {sorted(methods)}")
        if not r["cadence_hours"].isdigit() or int(r["cadence_hours"]) <= 0:
            errors.append(f"{where}: cadence_hours must be a positive integer")
        key = (r["institution"], r["kind"], r["variant"])
        if key in seen_keys:
            errors.append(f"{where}: duplicate source {key}")
        seen_keys.add(key)
        if r["url"]:
            if not _is_http_url(r["url"]):
                errors.append(f"{where}: url must be http(s), got {r['url']!r}")
            if (r["url"], r["kind"]) in seen_urls:
                errors.append(f"{where}: duplicate url {r['url']!r} for kind {r['kind']!r}")
            seen_urls.add((r["url"], r["kind"]))
        elif not needs_check:
            errors.append(f"{where}: a row without url must have needs_check=true")
        if r["adapter"] and r["adapter"] not in adapters:
            errors.append(f"{where}: no adapter registered as {r['adapter']!r}")

        rows.append(
            {
                "institution": r["institution"],
                "kind": r["kind"],
                "variant": r["variant"],
                "url": r["url"] or None,
                "fetch_method": r["fetch_method"],
                "cadence_hours": int(r["cadence_hours"]) if r["cadence_hours"].isdigit() else 0,
                "adapter_name": r["adapter"] or None,
                "needs_check": bool(needs_check),
            }
        )

    if errors:
        raise SeedError(errors)
    return rows


# --------------------------------------------------------------------------- loading


def _apply(obj: Any, values: dict[str, Any], label: str, counts: Counts) -> None:
    changed = {k: v for k, v in values.items() if getattr(obj, k) != v}
    if not changed:
        counts.unchanged += 1
        return
    for k, v in changed.items():
        counts.changes.append(f"{label}: {k} {getattr(obj, k)!r} -> {v!r}")
        setattr(obj, k, v)
    counts.updated += 1


def load_institutions(session: Session, rows: list[dict[str, Any]]) -> Counts:
    counts = Counts()
    existing = {i.short_name: i for i in session.scalars(select(Institution))}
    for row in rows:
        inst = existing.get(row["short_name"])
        if inst is None:
            session.add(Institution(**row))
            counts.inserted += 1
        else:
            _apply(inst, row, row["short_name"], counts)
    session.flush()
    return counts


def load_sources(session: Session, rows: list[dict[str, Any]]) -> Counts:
    counts = Counts()
    ids = {i.short_name: i.id for i in session.scalars(select(Institution))}
    by_key: dict[tuple[int | None, str, str], list[Source]] = {}
    for src in session.scalars(select(Source)):
        by_key.setdefault((src.institution_id, src.kind, src.variant), []).append(src)

    for row in rows:
        inst_id = ids[row["institution"]]
        values = {k: v for k, v in row.items() if k != "institution"}
        matches = by_key.get((inst_id, row["kind"], row["variant"]), [])
        label = "/".join(x for x in (row["institution"], row["kind"], row["variant"]) if x)
        if len(matches) > 1:
            raise SeedError([f"{label}: {len(matches)} sources in the DB; fix by hand first"])
        if matches:
            _apply(matches[0], values, label, counts)
        else:
            session.add(Source(institution_id=inst_id, **values))
            counts.inserted += 1
    session.flush()
    return counts


# --------------------------------------------------------------------------- VNCMA market series

MARKET_CADENCE_HOURS = 744  # monthly, like the bank sources
SERIES_KEYS = {
    "code",
    "provider",
    "asset_class",
    "request",
    "value_field",
    "unit",
    "native_frequency",
    "period",
    "month_end_rule",
    "max_gap_days",
    "grade",
    "active",
    "note",
}
REQUIRED_REQUEST_KEYS: dict[str, set[str]] = {
    "vnstock": {"call"},  # plus date_field, unless "reduce" is set
    "hnx": {"curve", "start"},
    "worldbank": {"page", "link_contains", "sheet"},
    "shiller": {"page", "link_contains", "sheet"},
    "sjc": {"start", "gold_type"},
    "sbv": {"page"},
    "manual": set(),  # entered by hand: `python -m pipeline market manual`
}


def parse_market(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(providers, series) from market_series.yaml, validated."""
    doc = yaml.safe_load(path.read_text("utf-8")) or {}
    errors: list[str] = []
    providers: list[dict[str, Any]] = []
    for name, p in (doc.get("providers") or {}).items():
        if name not in REQUIRED_REQUEST_KEYS:
            errors.append(f"{path.name}: provider {name!r} has no fetcher")
        if not _is_http_url(str(p.get("url", ""))):
            errors.append(f"{path.name}: provider {name!r} needs an http(s) url")
        if p.get("fetch_method") not in {m.value for m in FetchMethod}:
            errors.append(f"{path.name}: provider {name!r} has a bad fetch_method")
        providers.append(
            {
                "kind": SourceKind.MARKET_DATA.value,
                "variant": name,
                "url": p.get("url"),
                "fetch_method": p.get("fetch_method"),
                "cadence_hours": MARKET_CADENCE_HOURS,
                "adapter_name": None,
                "needs_check": False,
            }
        )
    known = {p["variant"] for p in providers}
    series: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, r in enumerate(doc.get("series") or [], 1):
        where = f"{path.name} series #{i} ({r.get('code', '?')})"
        extra = set(r) - SERIES_KEYS
        if extra:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
        code = str(r.get("code", ""))
        if not re.fullmatch(r"[a-z0-9_]{2,64}", code):
            errors.append(f"{where}: code must be lower_snake_case")
        if code in seen:
            errors.append(f"{where}: duplicate code")
        seen.add(code)
        provider = r.get("provider")
        if provider not in known:
            errors.append(f"{where}: unknown provider {provider!r}")
        request = r.get("request")
        if not isinstance(request, dict):
            errors.append(f"{where}: request must be a mapping")
        elif provider in REQUIRED_REQUEST_KEYS and not REQUIRED_REQUEST_KEYS[provider] <= set(
            request
        ):
            missing = sorted(REQUIRED_REQUEST_KEYS[provider] - set(request))
            errors.append(f"{where}: request needs {missing}")
        elif provider == "vnstock" and "date_field" not in request and "reduce" not in request:
            errors.append(f"{where}: a vnstock request needs date_field (or reduce)")
        for key, enum in (
            ("native_frequency", Frequency),
            ("period", Frequency),
            ("month_end_rule", MonthEndRule),
            ("grade", DataGrade),
        ):
            if r.get(key) not in {e.value for e in enum}:
                errors.append(f"{where}: {key} must be one of {[e.value for e in enum]}")
        gap = r.get("max_gap_days")
        if r.get("month_end_rule") == MonthEndRule.LAST_ON_OR_BEFORE.value and not (
            isinstance(gap, int) and gap > 0
        ):
            errors.append(f"{where}: last_on_or_before needs a positive max_gap_days")
        if not r.get("value_field") or not r.get("unit"):
            errors.append(f"{where}: value_field and unit are required")
        series.append(
            {
                "code": code,
                "provider": provider,
                "asset_class": r.get("asset_class"),
                "request": request,
                "value_field": r.get("value_field"),
                "unit": r.get("unit"),
                "native_frequency": r.get("native_frequency"),
                "period": r.get("period"),
                "month_end_rule": r.get("month_end_rule"),
                "max_gap_days": gap,
                "grade": r.get("grade"),
                "active": bool(r.get("active", True)),
                "note": r.get("note"),
            }
        )
    if errors:
        raise SeedError(errors)
    return providers, series


def load_market(
    session: Session, providers: list[dict[str, Any]], series: list[dict[str, Any]]
) -> Counts:
    counts = Counts()
    existing = {
        s.variant: s
        for s in session.scalars(select(Source).where(Source.kind == SourceKind.MARKET_DATA))
    }
    for row in providers:
        src = existing.get(row["variant"])
        if src is None:
            src = Source(institution_id=None, **row)
            session.add(src)
            existing[row["variant"]] = src
            counts.inserted += 1
        else:
            _apply(src, row, f"provider/{row['variant']}", counts)
    session.flush()
    by_code = {m.code: m for m in session.scalars(select(MarketSeries))}
    for row in series:
        values = {k: v for k, v in row.items() if k != "provider"}
        values["source_id"] = existing[row["provider"]].id
        current = by_code.get(row["code"])
        if current is None:
            session.add(MarketSeries(**values))
            counts.inserted += 1
        else:
            _apply(current, values, f"series/{row['code']}", counts)
    session.flush()
    return counts


def load_all(session: Session, seeds_dir: Path = SEEDS_DIR) -> dict[str, Counts]:
    institutions = parse_institutions(seeds_dir / "institutions.csv")
    sources = parse_sources(seeds_dir / "sources.csv", (r["short_name"] for r in institutions))
    market = seeds_dir / "market_series.yaml"
    market_rows = parse_market(market) if market.exists() else None
    results = {
        "institutions": load_institutions(session, institutions),
        "sources": load_sources(session, sources),
    }
    if market_rows is not None:
        results["market"] = load_market(session, *market_rows)
    return results


def main() -> None:
    from core.db import session_scope

    try:
        with session_scope() as session:
            results = load_all(session)
    except SeedError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    for name, counts in results.items():
        print(f"{name}: {counts}")
        for change in counts.changes:
            print(f"  {change}")


if __name__ == "__main__":
    main()
