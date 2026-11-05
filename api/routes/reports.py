"""POST /reports: a community report (message + optional screenshot)."""

import datetime as dt
import hashlib
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from api.common import HEADER
from api.deps import DB, Config, Store
from api.reports import image_type
from api.schemas import Error, ReportCreated
from core.models import CommunityReport, Institution
from core.scoring import METHODOLOGY_VERSION

router = APIRouter(tags=["reports"])


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post(
    "/reports",
    response_model=ReportCreated,
    status_code=201,
    summary="Report a wrong or outdated value",
    responses={400: {"model": Error}, 413: {"model": Error}, 429: {"model": Error}},
)
async def create_report(
    request: Request,
    session: DB,
    settings: Config,
    store: Store,
    message: Annotated[str, Form(min_length=10, max_length=2000)],
    institution: Annotated[str | None, Form(description="short_name, e.g. ACB")] = None,
    product_ref: Annotated[str | None, Form(max_length=500)] = None,
    contact: Annotated[
        str | None, Form(max_length=200, description="Optional; never published")
    ] = None,
    captcha_token: Annotated[str | None, Form(description="Turnstile/hCaptcha token")] = None,
    screenshot: Annotated[UploadFile | None, File(description="PNG, JPEG or WebP")] = None,
) -> JSONResponse:
    """Stored for a human to triage. A report never changes a published value; at
    most it makes us re-check the bank's own page."""
    ip = client_ip(request, settings.trust_proxy_headers)
    wait = request.app.state.report_limiter.check(ip)
    if wait is not None:
        raise HTTPException(
            429, "too many reports; try again later", {"Retry-After": str(int(wait) + 1)}
        )
    if not request.app.state.captcha.verify(captcha_token, ip):
        raise HTTPException(400, "captcha check failed")

    inst_id = None
    if institution:
        inst_id = session.scalar(
            select(Institution.id).where(Institution.short_name == institution.upper())
        )
        if inst_id is None:
            raise HTTPException(400, f"unknown institution {institution!r}; see /institutions")

    key = None
    if screenshot is not None and screenshot.filename:
        data = await screenshot.read(settings.report_max_screenshot_bytes + 1)
        if len(data) > settings.report_max_screenshot_bytes:
            raise HTTPException(413, "screenshot too large")
        kind = image_type(data)
        if kind is None:
            raise HTTPException(400, "screenshot must be a PNG, JPEG or WebP image")
        ext, content_type = kind
        sha = hashlib.sha256(data).hexdigest()
        key = f"reports/{dt.datetime.now(dt.UTC):%Y-%m-%d}/{sha}.{ext}"
        if not store.exists(key):
            store.put(key, data, content_type)

    report = CommunityReport(
        institution_id=inst_id,
        product_ref=(product_ref or "").strip() or None,
        message=message.strip(),
        evidence_storage_key=key,
        contact=(contact or "").strip() or None,
    )
    session.add(report)
    session.commit()
    body = ReportCreated(
        id=report.id,
        status=report.status.value if report.status else "new",
        message="Cảm ơn bạn. Chúng tôi sẽ kiểm tra lại với trang của ngân hàng.",
    )
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=201,
        headers={HEADER: METHODOLOGY_VERSION, "Cache-Control": "no-store"},
    )
