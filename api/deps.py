"""FastAPI dependencies: a read session, the response cache, settings, the store."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from api.common import ResponseCache
from core.config import Settings
from pipeline.fetch.storage import SnapshotStore


def session(request: Request) -> Iterator[Session]:
    s: Session = request.app.state.session_factory()
    try:
        yield s
    finally:
        s.close()


def cache(request: Request) -> ResponseCache:
    return request.app.state.cache  # type: ignore[no-any-return]


def settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def store(request: Request) -> SnapshotStore:
    return request.app.state.store()  # type: ignore[no-any-return]


DB = Annotated[Session, Depends(session)]
Cache = Annotated[ResponseCache, Depends(cache)]
Config = Annotated[Settings, Depends(settings)]
Store = Annotated[SnapshotStore, Depends(store)]
