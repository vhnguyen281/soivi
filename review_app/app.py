"""Review app: FastAPI + Jinja2 + HTMX, behind HTTP basic auth.

    uv run python -m review_app          # http://127.0.0.1:8001 (REVIEW_PORT)

Every write is a POST that must carry HTMX's `HX-Request` header. Browsers send
basic-auth credentials automatically, so this header (which another site cannot
add without a CORS preflight we never allow) is what stops cross-site requests.
"""

import datetime as dt
import html
import json
import re
import secrets
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.models import Institution, Snapshot, Source
from pipeline.fetch.storage import MinioStore, SnapshotStore
from review_app import service, vncma_view
from review_app.service import ReviewError
from review_app.webhook import notify_site

HERE = Path(__file__).resolve().parent
security = HTTPBasic(realm="Soivi review")


def create_app(
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
    store: SnapshotStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if not settings.review_password:
        raise RuntimeError("REVIEW_PASSWORD is empty: set it in .env before starting the app")
    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal
    make_session = session_factory

    app = FastAPI(title="Soivi review", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["vnd"] = lambda v: (
        f"{int(v):,}".replace(",", ".") if v is not None else "—"
    )
    templates.env.filters["show"] = _show
    templates.env.filters["vntime"] = lambda iso: _local_time(iso, settings.timezone)
    lazy_store: list[SnapshotStore] = [store] if store else []

    def get_store() -> SnapshotStore:
        if not lazy_store:
            lazy_store.append(MinioStore(settings))
        return lazy_store[0]

    def reviewer(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
        ok_user = secrets.compare_digest(
            credentials.username.encode(), settings.review_username.encode()
        )
        ok_pass = secrets.compare_digest(
            credentials.password.encode(), settings.review_password.encode()
        )
        if not (ok_user and ok_pass):
            raise HTTPException(401, "wrong username or password", {"WWW-Authenticate": "Basic"})
        return credentials.username

    def htmx_only(request: Request) -> None:
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "write requests must come from the review page")

    def db() -> Iterator[Session]:
        session = make_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    Reviewer = Annotated[str, Depends(reviewer)]
    DB = Annotated[Session, Depends(db)]
    Write = Depends(htmx_only)

    def render(request: Request, name: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    # ------------------------------------------------------------------ pages

    @app.get("/", response_class=HTMLResponse)
    def queue(request: Request, user: Reviewer, session: DB) -> HTMLResponse:
        return render(request, "queue.html", rows=service.open_tasks(session), user=user)

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task(request: Request, task_id: int, user: Reviewer, session: DB) -> HTMLResponse:
        try:
            view = service.task_view(session, task_id)
        except ReviewError as exc:
            raise HTTPException(404, str(exc)) from exc
        return render(request, "task.html", view=view, user=user)

    @app.get("/audit", response_class=HTMLResponse)
    def audit(request: Request, user: Reviewer, session: DB) -> HTMLResponse:
        return render(request, "audit.html", rows=service.audit_log(session), user=user)

    # ------------------------------------------------------------------ actions

    def task_done(result: service.ActionResult) -> Response:
        # Task-level actions send the reviewer back to the queue.
        return Response(status_code=204, headers={"HX-Redirect": "/"})

    @app.post("/tasks/{task_id}/approve-all", dependencies=[Write])
    def approve_all(
        task_id: int, user: Reviewer, session: DB, background: BackgroundTasks
    ) -> Response:
        result = _or_409(service.approve_all, session, task_id, user)
        background.add_task(notify_site, settings)  # published values changed
        return task_done(result)

    @app.post("/tasks/{task_id}/reject-all", dependencies=[Write])
    def reject_all(task_id: int, user: Reviewer, session: DB) -> Response:
        return task_done(_or_409(service.reject_all, session, task_id, user))

    @app.post("/tasks/{task_id}/needs-fix", dependencies=[Write])
    def needs_fix(
        task_id: int, user: Reviewer, session: DB, note: Annotated[str, Form()] = ""
    ) -> Response:
        return task_done(_or_409(service.needs_fix, session, task_id, user, note))

    @app.post("/tasks/{task_id}/versions/{table}/{version_id}/retire", dependencies=[Write])
    def retire(
        request: Request,
        task_id: int,
        table: str,
        version_id: int,
        user: Reviewer,
        session: DB,
        background: BackgroundTasks,
        note: Annotated[str, Form()] = "",
    ) -> HTMLResponse:
        _or_409(service.retire, session, task_id, table, version_id, user, note)
        background.add_task(notify_site, settings)  # a published value came down
        item = service.item_view(session, task_id, table, version_id)
        return render(request, "_row.html", item=item, task_id=task_id)

    @app.post("/tasks/{task_id}/versions/{table}/{version_id}/{decision}", dependencies=[Write])
    def decide(
        request: Request,
        task_id: int,
        table: str,
        version_id: int,
        decision: str,
        user: Reviewer,
        session: DB,
        background: BackgroundTasks,
    ) -> HTMLResponse:
        if decision not in {"approve", "reject"}:
            raise HTTPException(404)
        result = _or_409(
            service.decide_version,
            session,
            task_id,
            table,
            version_id,
            user,
            approve=decision == "approve",
        )
        if decision == "approve":
            background.add_task(notify_site, settings)
        item = service.item_view(session, task_id, table, version_id)
        return render(
            request,
            "_row.html",
            item=item,
            task_id=task_id,
            task_status=result.task_status,
            oob=True,
        )

    # ------------------------------------------------------------------ VNCMA

    @app.get("/vncma", response_class=HTMLResponse)
    def vncma(request: Request, user: Reviewer, session: DB) -> HTMLResponse:
        return render(request, "vncma.html", rows=vncma_view.runs(session), user=user)

    @app.get("/vncma/runs/{run_id}", response_class=HTMLResponse)
    def vncma_run(request: Request, run_id: int, user: Reviewer, session: DB) -> HTMLResponse:
        view = vncma_view.run_view(session, run_id)
        if view is None:
            raise HTTPException(404, "no such run")
        return render(request, "vncma_run.html", view=view, user=user)

    @app.get("/vncma/runs/{run_id}/download/{fmt}")
    def vncma_download(run_id: int, fmt: str, user: Reviewer, session: DB) -> Response:
        if fmt not in vncma_view.FORMATS:
            raise HTTPException(404)
        doc = vncma_view.download(session, run_id, fmt)
        if doc is None:
            raise HTTPException(404, "no such run")
        name, content, media = doc
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/vncma/runs/{run_id}/release", dependencies=[Write])
    def vncma_release(
        run_id: int,
        user: Reviewer,
        session: DB,
        background: BackgroundTasks,
        version: Annotated[str, Form()] = "",
        reviewer_name: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
    ) -> Response:
        from core.cma.release import ReleaseError, approve

        try:
            approve(session, run_id, version, reviewer_name, note)
        except ReleaseError as exc:
            raise HTTPException(409, str(exc)) from exc
        background.add_task(notify_site, settings)  # the public VNCMA page rebuilds
        return Response(status_code=204, headers={"HX-Redirect": f"/vncma/runs/{run_id}"})

    @app.get("/vncma/portfolios/{version}", response_class=HTMLResponse)
    def vncma_portfolios(
        request: Request, version: str, user: Reviewer, session: DB
    ) -> HTMLResponse:
        view = vncma_view.portfolio_view(session, version)
        if view is None:
            raise HTTPException(404, "no such release")
        return render(request, "vncma_portfolios.html", view=view, user=user)

    @app.post("/vncma/portfolios/{version}/approve", dependencies=[Write])
    def vncma_portfolios_approve(
        version: str,
        user: Reviewer,
        session: DB,
        background: BackgroundTasks,
        reviewer_name: Annotated[str, Form()] = "",
    ) -> Response:
        from core.cma.portfolios import PortfolioError, approve

        try:
            approve(session, version, reviewer_name)
        except PortfolioError as exc:
            raise HTTPException(409, str(exc)) from exc
        background.add_task(notify_site, settings)
        return Response(status_code=204, headers={"HX-Redirect": f"/vncma/portfolios/{version}"})

    # ------------------------------------------------------------------ health

    @app.get("/health")
    def health(user: Reviewer, session: DB, strict: bool = False) -> Response:
        """Every source with its last status and the age of its last success.

        ?strict=1 answers 503 when any monitored source is stale or broken, for
        uptime monitors (which can send the basic-auth login)."""
        report = health_report(session)
        status = 503 if strict and report["status"] != "ok" else 200
        return Response(
            json.dumps(report, ensure_ascii=False, indent=1),
            status_code=status,
            media_type="application/json",
        )

    # ------------------------------------------------------------------ snapshots

    @app.get("/snapshots/{snapshot_id}", response_class=HTMLResponse)
    def snapshot_page(
        request: Request, snapshot_id: int, user: Reviewer, session: DB, page: int | None = None
    ) -> HTMLResponse:
        snap = _snapshot(session, snapshot_id)
        kind = _kind(snap)
        body = None
        if kind == "json":
            raw = get_store().get(snap.storage_key)
            try:
                body = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
            except ValueError:
                body = raw.decode("utf-8", errors="replace")
        return render(
            request, "snapshot.html", snap=snap, kind=kind, body=body, page=page, user=user
        )

    @app.get("/snapshots/{snapshot_id}/raw")
    def snapshot_raw(
        snapshot_id: int, user: Reviewer, session: DB, display: bool = False
    ) -> Response:
        """The stored bytes. With ?display=1, HTML gets a <base href> to the bank's URL
        so its stylesheets and images load (still sandboxed: no scripts run)."""
        snap = _snapshot(session, snapshot_id)
        content = get_store().get(snap.storage_key)
        if display and _kind(snap) == "html":
            content = _with_base(content, snap.url)
        headers = {
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            # Bank HTML is shown as evidence only: no scripts, forms, or same-origin access.
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, max-age=3600",
        }
        media = {
            "html": "text/html; charset=utf-8",
            "pdf": "application/pdf",
            "json": "application/json",
        }
        return Response(
            content, media_type=media.get(_kind(snap), "application/octet-stream"), headers=headers
        )

    return app


def _or_409(
    fn: Callable[..., service.ActionResult], *args: Any, **kwargs: Any
) -> service.ActionResult:
    try:
        return fn(*args, **kwargs)
    except ReviewError as exc:
        raise HTTPException(409, str(exc)) from exc


def health_report(session: Session, now: dt.datetime | None = None) -> dict[str, Any]:
    from zoneinfo import ZoneInfo

    from core.freshness import source_staleness
    from pipeline.schedule import SCHEDULES, next_slot
    from pipeline.validate.rules import staleness_policy

    now = now or dt.datetime.now(dt.UTC)
    tz = ZoneInfo(get_settings().timezone)
    policy = staleness_policy()
    names = {i.id: i.short_name for i in session.scalars(select(Institution))}
    sources = []
    problems = 0
    for s in session.scalars(select(Source).order_by(Source.id)):
        monitored = bool(s.active and not s.needs_check and s.url and s.adapter_name)
        reasons = source_staleness(s, now, policy) if monitored else []
        broken = s.last_status in {"parse_failed", "diff_failed"}
        state = (
            "not_monitored"
            if not monitored
            else ("broken" if broken else ("stale" if reasons else "ok"))
        )
        problems += state in {"broken", "stale"}
        age = (now - s.last_success_at).total_seconds() if s.last_success_at else None
        schedule = SCHEDULES.get(s.kind)
        sources.append(
            {
                "id": s.id,
                "institution": names.get(s.institution_id or 0),
                "kind": s.kind.value,
                "variant": s.variant,
                "adapter": s.adapter_name,
                "state": state,
                "last_status": s.last_status,
                "last_attempt_at": s.last_attempt_at.isoformat() if s.last_attempt_at else None,
                "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
                "last_success_age_hours": round(age / 3600, 1) if age is not None else None,
                "consecutive_failures": s.consecutive_failures,
                "stale_reasons": reasons,
                "last_error": s.last_error,
                "next_run": next_slot(schedule, now, tz).isoformat()
                if monitored and schedule
                else None,
            }
        )
    monitored_count = sum(x["state"] != "not_monitored" for x in sources)
    return {
        "status": "ok" if problems == 0 else "degraded",
        "checked_at": now.isoformat(),
        "monitored_sources": monitored_count,
        "problems": problems,
        "sources": sources,
    }


def _snapshot(session: Session, snapshot_id: int) -> Snapshot:
    snap = session.get(Snapshot, snapshot_id)
    if snap is None:
        raise HTTPException(404, "no such snapshot")
    return snap


def _kind(snap: Snapshot) -> str:
    ct = (snap.content_type or "").lower()
    if "pdf" in ct or snap.storage_key.endswith(".pdf"):
        return "pdf"
    if "json" in ct or snap.storage_key.endswith(".json"):
        return "json"
    if "html" in ct or snap.storage_key.endswith(".html"):
        return "html"
    return "other"


def _with_base(content: bytes, url: str) -> bytes:
    """Insert <base href=url> so relative CSS/images resolve to the bank's site."""
    tag = f'<base href="{html.escape(url, quote=True)}">'.encode()
    match = re.search(rb"<head[^>]*>", content, re.IGNORECASE)
    if match:
        return content[: match.end()] + tag + content[match.end() :]
    return tag + content


def _local_time(iso: str | None, timezone: str) -> str:
    """'2026-10-28T09:58:32+00:00' -> '28/10 16:58' (local time)."""
    if not iso:
        return ""
    from zoneinfo import ZoneInfo

    try:
        when = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return when.astimezone(ZoneInfo(timezone)).strftime("%d/%m %H:%M")


def _show(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "có" if value else "không"
    return str(value)
