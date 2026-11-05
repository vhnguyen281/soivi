"""BaseAdapter: one subclass per source page format.

A subclass declares its metadata and implements parse():

    @register
    class VietcombankSavings(BaseAdapter):
        name = "vietcombank_savings"
        institution = "VIETCOMBANK"
        source_kind = SourceKind.SAVINGS_RATE_PAGE
        fetch_method = FetchMethod.HTTP

        @classmethod
        def parse_content(cls, content: bytes) -> list[Record]:
            ...

fetch() is shared: it downloads the page politely, stores the bytes, and writes a
snapshot row. parse() must raise AdapterBroken when the page is not what it expects;
it must never return partial data (CLAUDE.md).
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.enums import ExtractionMethod, FetchMethod, SourceKind
from core.models import Institution, Snapshot, Source
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.storage import SnapshotStore, snapshot_key
from pipeline.records import Record
from pipeline.validate.rules import RuleWarning


class AdapterError(Exception):
    """The adapter is misconfigured or used on the wrong source."""


class AdapterBroken(AdapterError):
    """The snapshot does not look like what the adapter expects (layout changed,
    table missing, a value that cannot be read). Raised instead of returning
    partial data."""


@dataclass
class AdapterContext:
    session: Session
    fetchers: Fetchers
    store: SnapshotStore


class BaseAdapter(ABC):
    name: ClassVar[str]
    institution: ClassVar[str]  # institution.short_name
    source_kind: ClassVar[SourceKind]
    fetch_method: ClassVar[FetchMethod] = FetchMethod.HTTP
    # Provenance recorded on every version this adapter proposes. JSON and HTML
    # sources use HTML; PDF text/grids use PDF_TABLE; image PDFs use OCR.
    extraction_method: ClassVar[ExtractionMethod] = ExtractionMethod.HTML
    # Browser sources: text the rendered page must contain before it is captured
    # (pages that load their data late can otherwise be stored half-empty).
    browser_wait_for: ClassVar[str | None] = None
    # Most sources are a GET. Some bank endpoints only answer a form POST.
    http_method: ClassVar[str] = "GET"
    http_data: ClassVar[dict[str, str] | None] = None

    def allows_empty(self) -> bool:
        """Whether parse() may legitimately find nothing (the runner refuses an empty
        result otherwise). Only sources that can truly state nothing say yes."""
        return False

    def __init__(self, source: Source, ctx: AdapterContext) -> None:
        self.source = source
        self.ctx = ctx
        self._bytes: dict[str, bytes] = {}  # sha256 -> content fetched in this run
        # Warnings for the reviewer from the last parse() (shown on the review task).
        self.notes: list[RuleWarning] = []
        self._check_source()

    def _check_source(self) -> None:
        inst = self.ctx.session.get(Institution, self.source.institution_id)
        problems = []
        if inst is None or inst.short_name != self.institution:
            problems.append(f"institution is {inst.short_name if inst else None!r}")
        if self.source.kind != self.source_kind:
            problems.append(f"kind is {self.source.kind.value!r}")
        if self.source.fetch_method != self.fetch_method:
            problems.append(f"fetch_method is {self.source.fetch_method.value!r}")
        if not self.source.url:
            problems.append("url is empty")
        if problems:
            raise AdapterError(
                f"adapter {self.name!r} expects {self.institution}/{self.source_kind.value}"
                f" via {self.fetch_method.value}, but source {self.source.id}: "
                + ", ".join(problems)
            )

    # ----------------------------------------------------------------- fetch

    def resolve_url(self) -> str:
        """The URL to fetch. Defaults to source.url.

        Override for two-step sources, e.g. a document listing that names the
        current PDF. Use self.ctx.fetchers so the extra request stays polite.
        """
        assert self.source.url is not None  # checked in __init__
        return self.source.url

    def fetch(self) -> Snapshot:
        """Download the source, store the bytes, and write a snapshot row."""
        url = self.resolve_url()
        fetcher = self.ctx.fetchers.for_method(self.fetch_method)
        result = fetcher.fetch(url, self.http_method, self.http_data, self.browser_wait_for)
        sha256 = hashlib.sha256(result.content).hexdigest()
        previous = self.ctx.session.scalars(
            select(Snapshot)
            .where(Snapshot.source_id == self.source.id)
            .order_by(Snapshot.fetched_at.desc(), Snapshot.id.desc())
            .limit(1)
        ).first()

        key = snapshot_key(
            self.institution, self.source_kind.value, result.fetched_at, sha256, result.content_type
        )
        if not self.ctx.store.exists(key):  # same bytes already stored today
            self.ctx.store.put(key, result.content, result.content_type)

        snapshot = Snapshot(
            source_id=self.source.id,
            url=result.final_url,
            fetched_at=result.fetched_at,
            http_status=result.status,
            content_type=result.content_type,
            sha256=sha256,
            storage_key=key,
            size_bytes=len(result.content),
            unchanged=previous is not None and previous.sha256 == sha256,
        )
        self.ctx.session.add(snapshot)
        self.ctx.session.flush()
        self._bytes[sha256] = result.content
        return snapshot

    def read(self, snapshot: Snapshot) -> bytes:
        """The snapshot's raw bytes (from memory if fetched in this run)."""
        cached = self._bytes.get(snapshot.sha256)
        return cached if cached is not None else self.ctx.store.get(snapshot.storage_key)

    # ----------------------------------------------------------------- parse

    def parse(self, snapshot: Snapshot) -> list[Record]:
        """Turn the snapshot into records. Raises AdapterBroken instead of guessing."""
        return self.parse_content(self.read(snapshot))

    @classmethod
    @abstractmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        """Parse raw bytes. A classmethod so fixture tests need no database or network."""
