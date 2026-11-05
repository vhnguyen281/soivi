"""Shared API plumbing: cached responses, provenance, verification state.

Caching: read responses are kept in process for `api_cache_seconds` (default 60),
keyed by method + URL (+ body for POST /cards/rank). Each carries an ETag; a
request with a matching If-None-Match gets 304. Cache-Control lets browsers and
a CDN keep GET responses for the same time. Approved values change at most a few
times a day, so a minute of staleness is harmless.
"""

import datetime as dt
import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import InstitutionRef, Provenance
from core.freshness import institution_freshness
from core.models import Institution, Snapshot, Versioned
from core.scoring import METHODOLOGY_VERSION

HEADER = "X-Methodology-Version"
JSON = "application/json"


@dataclass
class ResponseCache:
    ttl: float
    clock: Callable[[], float] = time.monotonic
    entries: dict[str, tuple[float, bytes, str]] = field(default_factory=dict)
    max_entries: int = 2048

    def get(self, key: str) -> tuple[bytes, str] | None:
        hit = self.entries.get(key)
        if hit is None or hit[0] <= self.clock():
            self.entries.pop(key, None)
            return None
        return hit[1], hit[2]

    def put(self, key: str, body: bytes, etag: str) -> None:
        if self.ttl <= 0:
            return
        if len(self.entries) >= self.max_entries:  # simple bound: drop the oldest
            self.entries.pop(next(iter(self.entries)))
        self.entries[key] = (self.clock() + self.ttl, body, etag)

    def clear(self) -> None:
        self.entries.clear()


def send(
    request: Request,
    cache: ResponseCache,
    build: Callable[[], BaseModel],
    *,
    key_extra: bytes = b"",
) -> Response:
    key = f"{request.method} {request.url}"
    if key_extra:
        key += " " + hashlib.sha256(key_extra).hexdigest()
    # "Cache-Control: no-cache" (sent by the site when it rebuilds after an
    # approval) skips the cached copy, so a fresh rebuild never sees stale data.
    fresh = "no-cache" in request.headers.get("Cache-Control", "")
    hit = None if fresh else cache.get(key)
    if hit is None:
        body = build().model_dump_json().encode()
        etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
        cache.put(key, body, etag)
        status = "MISS"
    else:
        body, etag = hit
        status = "HIT"
    headers = {"ETag": etag, HEADER: METHODOLOGY_VERSION, "X-Cache": status}
    if request.method == "GET":
        headers["Cache-Control"] = f"public, max-age={int(cache.ttl)}"
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers=headers)
    return Response(body, media_type=JSON, headers=headers)


# --------------------------------------------------------------------------- provenance


def snapshots(session: Session, versions: Iterable[Versioned]) -> dict[int, Snapshot]:
    ids = {v.snapshot_id for v in versions}
    if not ids:
        return {}
    return {s.id: s for s in session.scalars(select(Snapshot).where(Snapshot.id.in_(ids)))}


def provenance(version: Versioned, snapshot: Snapshot | None) -> Provenance:
    """source_url from the stored copy; checked_at = the latest read that found
    this value (the original fetch, or a later re-check that saw it unchanged)."""
    checked = [t for t in (snapshot.fetched_at if snapshot else None, version.last_seen_at) if t]
    return Provenance(
        source_url=snapshot.url if snapshot else None,
        checked_at=max(checked) if checked else None,
        effective_from=version.effective_from,
        approved_at=version.valid_from,
        extraction_method=version.extraction_method.value,
        snapshot_sha256=snapshot.sha256 if snapshot else None,
        evidence=version.source_evidence,
    )


def verification(session: Session, now: dt.datetime | None = None) -> dict[int, str]:
    """institution id -> verified | unverified | no_sources."""
    return {i: f.state for i, f in institution_freshness(session, now).items()}


def ref(inst: Institution) -> InstitutionRef:
    return InstitutionRef(short_name=inst.short_name, legal_name_vi=inst.legal_name_vi)
