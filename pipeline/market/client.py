"""The single entry point to vnstock.

vnstock 5 comes from vnstocks.com's own package index (see pyproject.toml). The
paid tier is unlocked by an API key saved on this machine with `vnstock register`
(or VNSTOCK_API_KEY); the key never goes in the repo. The sponsor package
`vnstock_data` from vnstock 3/4 is no longer used.

vnstock is imported lazily, so the rest of the pipeline (and the test suite)
works on machines without it.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


class MarketDataError(Exception):
    """A vnstock call failed or returned nothing usable. The message names the call."""


@dataclass(frozen=True)
class AccountStatus:
    version: str
    tier: str
    authenticated: bool
    active: bool
    expires_at: str | None  # the plan
    release_expires_on: str | None  # each vnstock release stops working after a date
    release_days_left: int | None


@dataclass(frozen=True)
class IndexClose:
    symbol: str
    date: dt.date
    close: Decimal
    source: str  # vnstock's df.attrs["source"], e.g. "kbs"


# One step of a vnstock call chain: (name, args, kwargs). args=None means attribute
# access, e.g. Reference().fund.list("bond_fund") is
# [("Reference", (), {}), ("fund", None, {}), ("list", ("bond_fund",), {})].
Step = tuple[str, tuple[Any, ...] | None, dict[str, Any]]


def describe(chain: Sequence[Step]) -> str:
    """`Market().index("VN30").ohlcv(start="2000-01-01")` for a chain."""
    parts = []
    for name, args, kwargs in chain:
        if args is None:
            parts.append(name)
            continue
        params = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        parts.append(f"{name}({', '.join(params)})")
    return ".".join(parts).replace("'", '"')


class MarketClient(Protocol):
    def status(self) -> AccountStatus: ...
    def latest_index_close(self, symbol: str) -> IndexClose: ...
    def call(self, chain: Sequence[Step]) -> Any: ...


class VnstockClient:
    """MarketClient backed by the installed vnstock package."""

    def __init__(self) -> None:
        try:
            import vnstock
        except ImportError as exc:
            raise MarketDataError(
                "vnstock is not installed: run `uv sync` (it comes from vnstocks.com's index)"
            ) from exc
        self._vnstock: Any = vnstock

    def status(self) -> AccountStatus:
        try:
            raw: dict[str, Any] = self._vnstock.status()
        except Exception as exc:
            raise MarketDataError(f"vnstock.status() failed: {exc}") from exc
        release = raw.get("release") or {}
        return AccountStatus(
            version=str(release.get("version") or self._vnstock.__version__),
            tier=str(raw.get("tier") or "unknown"),
            authenticated=bool(raw.get("authenticated")),
            active=bool(raw.get("active")),
            expires_at=raw.get("expires_at"),
            release_expires_on=release.get("expires_on"),
            release_days_left=release.get("days_left"),
        )

    def call(self, chain: Sequence[Step]) -> Any:
        """Run a call chain against vnstock and return what it returns (usually a DataFrame).

        Used by the probe. Exceptions are wrapped in MarketDataError naming the call.
        """
        obj: Any = self._vnstock
        try:
            for name, args, kwargs in chain:
                obj = getattr(obj, name)
                if args is not None:
                    obj = obj(*args, **kwargs)
        except Exception as exc:
            raise MarketDataError(f"{describe(chain)} failed: {type(exc).__name__}: {exc}") from exc
        return obj

    def latest_index_close(self, symbol: str) -> IndexClose:
        call = f'Market().index("{symbol}").ohlcv(length=5)'
        try:
            df = self._vnstock.Market().index(symbol).ohlcv(length=5)
        except Exception as exc:
            raise MarketDataError(f"{call} failed: {exc}") from exc
        if df is None or len(df) == 0 or "close" not in df.columns or "time" not in df.columns:
            raise MarketDataError(f"{call} returned no rows or no time/close columns")
        last = df.sort_values("time").iloc[-1]
        return IndexClose(
            symbol=symbol,
            date=last["time"].date(),
            close=Decimal(str(last["close"])),
            source=str(df.attrs.get("source", "unknown")),
        )
