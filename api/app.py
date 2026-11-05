"""Public API (read-only except POST /reports). OpenAPI docs at /docs and /redoc.

    uv run python -m api        # http://127.0.0.1:8002 (API_PORT); make api in Docker

Every value carries its provenance (source_url, checked_at, effective_from) and
every response, errors included, the methodology version: in the JSON body and
as the X-Methodology-Version header. Amounts are integer VND; rates are decimal
strings. Read responses are cached (api/common.py).
"""

import time
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.common import HEADER, ResponseCache, send
from api.reports import Captcha, RateLimiter, make_captcha
from api.routes import cards, changes, institutions, reports, savings
from api.schemas import Error, MethodologyOut
from core.config import Settings, get_settings
from core.scoring import METHODOLOGY_VERSION
from core.scoring.cards import PERSONAS, SPEND_CATEGORIES
from core.scoring.savings import CHANNEL_PREFERENCES, ScoringError
from pipeline.fetch.storage import SnapshotStore

METHODOLOGY_URL = "https://github.com/soivi/soivi/blob/main/docs/methodology.md"

DESCRIPTION = f"""
So sánh lãi suất tiết kiệm và thẻ tín dụng tại Việt Nam. / Compare Vietnamese savings
rates and credit cards.

- Every value comes from the bank's own page and was approved by a person.
- Every value carries `source_url`, `checked_at` and `effective_from`.
- Every response carries `methodology_version` ([methodology]({METHODOLOGY_URL})).
- Amounts are integer VND. Rates are decimal strings, e.g. `"5.900"`.
"""


def error(status: int, detail: object, headers: dict[str, str] | None = None) -> JSONResponse:
    body = Error(error=detail).model_dump(mode="json", exclude_none=True)
    return JSONResponse(body, status, {HEADER: METHODOLOGY_VERSION, **(headers or {})})


def create_app(
    session_factory: Callable[[], Session] | None = None,
    *,
    settings: Settings | None = None,
    store: SnapshotStore | None = None,
    captcha: Captcha | None = None,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if session_factory is None:
        from core.db import SessionLocal

        session_factory = SessionLocal

    app = FastAPI(
        title="Soivi API",
        version=METHODOLOGY_VERSION,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.session_factory = session_factory
    app.state.settings = settings
    tick = clock or time.monotonic
    app.state.cache = ResponseCache(settings.api_cache_seconds, clock=tick)
    app.state.report_limiter = RateLimiter(settings.report_rate_limit_per_hour, clock=tick)
    app.state.captcha = captcha or make_captcha(settings)
    lazy: list[SnapshotStore] = [store] if store else []

    def get_store() -> SnapshotStore:
        if not lazy:
            from pipeline.fetch.storage import MinioStore

            lazy.append(MinioStore(settings))
        return lazy[0]

    app.state.store = get_store

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error(exc.status_code, exc.detail, dict(exc.headers or {}))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
        ]
        body = Error(error="invalid request", details=details).model_dump(mode="json")
        return JSONResponse(body, 422, {HEADER: METHODOLOGY_VERSION})

    @app.exception_handler(ScoringError)
    async def scoring_error(request: Request, exc: ScoringError) -> JSONResponse:
        return error(422, str(exc))

    @app.middleware("http")
    async def version_header(request: Request, call_next: Callable[..., object]) -> Response:
        response: Response = await call_next(request)  # type: ignore[misc]
        response.headers[HEADER] = METHODOLOGY_VERSION
        return response

    @app.get("/methodology", response_model=MethodologyOut, tags=["methodology"])
    def methodology(request: Request) -> Response:
        """The methodology in force, and the options its formulas accept."""
        return send(
            request,
            app.state.cache,
            lambda: MethodologyOut(
                document=METHODOLOGY_URL,
                savings_channels=sorted(CHANNEL_PREFERENCES),
                spend_categories=[c.value for c in SPEND_CATEGORIES],
                personas=list(PERSONAS),
            ),
        )

    for module in (institutions, savings, cards, changes, reports):
        app.include_router(module.router)
    return app
