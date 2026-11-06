"""GET /vncma/latest, /vncma/{version}, /vncma/releases, /vncma/{version}/download/{fmt}.

Only approved releases (`cma_release`) are served; drafts never leave the review app.
Each response carries the VNCMA methodology version in the body and in the
X-VNCMA-Methodology-Version header (X-Methodology-Version stays the site's scoring
version). Paths have no /v1 prefix, like the rest of the API (DECISIONS 2026-10-29).
"""

import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from api.common import send
from api.deps import DB, Cache
from api.schemas import VncmaOut, VncmaReleaseRef, VncmaReleasesOut
from core.cma.release import previous_payload
from core.cma.report import markdown_vi, write_xlsx
from core.models import CmaRelease, CmaRun

router = APIRouter(tags=["vncma"])
HEADER = "X-VNCMA-Methodology-Version"
METHODOLOGY_URL = "https://github.com/soivi/soivi/blob/main/docs/vncma/spec.md"
MEDIA = {
    "json": "application/json",
    "md": "text/markdown; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _release(session: DB, version: str) -> CmaRelease:
    query = select(CmaRelease).order_by(CmaRelease.approved_at.desc(), CmaRelease.id.desc())
    if version != "latest":
        query = select(CmaRelease).where(CmaRelease.version == version)
    release = session.scalar(query)
    if release is None:
        raise HTTPException(404, f"no VNCMA release {version!r}")
    return release


def _out(release: CmaRelease) -> VncmaOut:
    doc = dict(release.payload)
    doc["provenance"] = {**doc["provenance"], "payload_sha256": release.payload_sha256}
    doc["methodology_url"] = METHODOLOGY_URL
    doc["downloads"] = {f: f"/vncma/{release.version}/download/{f}" for f in MEDIA}
    return VncmaOut.model_validate(doc)


def _send(request: Request, cache: Cache, release: CmaRelease) -> Response:
    response = send(request, cache, lambda: _out(release))
    response.headers[HEADER] = release.methodology_version
    return response


@router.get("/vncma/releases", response_model=VncmaReleasesOut, summary="VNCMA releases")
def releases(request: Request, session: DB, cache: Cache) -> Response:
    """Every approved release, newest first."""

    def build() -> VncmaReleasesOut:
        rows = session.scalars(
            select(CmaRelease).order_by(CmaRelease.approved_at.desc(), CmaRelease.id.desc())
        )
        return VncmaReleasesOut(
            releases=[
                VncmaReleaseRef(
                    version=r.version,
                    as_of=r.payload["as_of"],
                    approved_at=r.approved_at,
                    methodology_version=r.methodology_version,
                )
                for r in rows
            ]
        )

    return send(request, cache, build)


@router.get("/vncma/latest", response_model=VncmaOut, summary="The latest VNCMA release")
def latest(request: Request, session: DB, cache: Cache) -> Response:
    """Vietnam capital market assumptions: 10-year expected returns (geometric, VND,
    percent per year), volatilities, correlations and scenarios. Planning assumptions,
    not investment advice."""
    return _send(request, cache, _release(session, "latest"))


@router.get("/vncma/{version}", response_model=VncmaOut, summary="One VNCMA release")
def by_version(request: Request, version: str, session: DB, cache: Cache) -> Response:
    """A release by its version, e.g. 2027.1."""
    return _send(request, cache, _release(session, version))


@router.get("/vncma/{version}/download/{fmt}", summary="A release as xlsx, json or markdown")
def download(version: str, fmt: Literal["json", "md", "xlsx"], session: DB) -> Response:
    import json

    release = _release(session, version)
    name = f"vncma-{release.version}.{fmt}"
    headers = {
        "Content-Disposition": f'attachment; filename="{name}"',
        HEADER: release.methodology_version,
        "Cache-Control": "public, max-age=3600",
    }
    if fmt == "json":
        body = json.dumps(release.payload, ensure_ascii=False, indent=1).encode()
        return Response(body, media_type=MEDIA[fmt], headers=headers)
    previous = previous_payload(session, release)
    if fmt == "md":
        return Response(
            markdown_vi(release.payload, previous).encode(), media_type=MEDIA[fmt], headers=headers
        )
    run = session.get(CmaRun, release.run_id)
    assert run is not None
    with tempfile.TemporaryDirectory() as tmp:
        path = write_xlsx(run, release.payload, Path(tmp) / name, previous)
        return Response(path.read_bytes(), media_type=MEDIA[fmt], headers=headers)
