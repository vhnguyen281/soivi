"""Read-side helpers for the review app's VNCMA tab (Prompt 8)."""

import json
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.cma.release import next_version, previous_payload, release_of
from core.cma.report import macro_order, markdown_vi, payload, write_xlsx
from core.models import CmaAdjustment, CmaRelease, CmaRun

FORMATS = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
    "md": "text/markdown; charset=utf-8",
}


def runs(session: Session, limit: int = 30) -> list[dict[str, Any]]:
    released = {r.run_id: r for r in session.scalars(select(CmaRelease))}
    out = []
    for run in session.scalars(select(CmaRun).order_by(CmaRun.id.desc()).limit(limit)):
        classes = run.output.get("classes", {})
        out.append(
            {
                "run": run,
                "release": released.get(run.id),
                "eq_large": classes.get("eq_large", {}).get("final"),
                "cash": classes.get("cash_vnd", {}).get("final"),
                "adjusted": sum(1 for c in classes.values() if c.get("adjustment")),
            }
        )
    return out


def _doc(session: Session, run: CmaRun) -> tuple[dict[str, Any], CmaRelease | None]:
    release = release_of(session, run.id)
    if release is not None:
        return release.payload, release
    return payload(run, f"{next_version(session, run)}-draft"), None


def run_view(session: Session, run_id: int) -> dict[str, Any] | None:
    run = session.get(CmaRun, run_id)
    if run is None:
        return None
    doc, release = _doc(session, run)
    adjustments = list(
        session.scalars(
            select(CmaAdjustment).where(CmaAdjustment.run_id == run.id).order_by(CmaAdjustment.id)
        )
    )
    return {
        "run": run,
        "doc": doc,
        "release": release,
        "adjustments": adjustments,
        "suggested_version": None if release else next_version(session, run),
        "macro": dict(sorted(run.output["macro"].items(), key=lambda kv: macro_order(kv[0]))),
        "corr": doc["correlation"],
    }


def download(session: Session, run_id: int, fmt: str) -> tuple[str, bytes, str] | None:
    run = session.get(CmaRun, run_id)
    if run is None:
        return None
    doc, release = _doc(session, run)
    previous = previous_payload(session, release) if release else previous_payload(session)
    name = f"vncma-{doc['version']}.{fmt}"
    if fmt == "json":
        return name, json.dumps(doc, ensure_ascii=False, indent=1).encode(), FORMATS[fmt]
    if fmt == "md":
        return name, markdown_vi(doc, previous).encode(), FORMATS[fmt]
    with tempfile.TemporaryDirectory() as tmp:
        path = write_xlsx(run, doc, Path(tmp) / name, previous)
        return name, path.read_bytes(), FORMATS[fmt]
