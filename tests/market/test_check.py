"""`python -m pipeline market check`, offline with a fake client."""

import datetime as dt
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pipeline.__main__ import main
from pipeline.market.client import (
    AccountStatus,
    IndexClose,
    MarketDataError,
    VnstockClient,
)

VN = ZoneInfo("Asia/Ho_Chi_Minh")

GOLDEN = AccountStatus(
    version="5.2.1",
    tier="golden",
    authenticated=True,
    active=True,
    expires_at="2027-04-09T14:29:10Z",
    release_expires_on="2027-10-27",
    release_days_left=356,
)


class FakeClient:
    def __init__(self, status: AccountStatus = GOLDEN, fail_index: bool = False) -> None:
        self._status = status
        self._fail_index = fail_index

    def status(self) -> AccountStatus:
        return self._status

    def latest_index_close(self, symbol: str) -> IndexClose:
        if self._fail_index:
            raise MarketDataError(f'Market().index("{symbol}").ohlcv(length=5) returned no rows')
        return IndexClose(symbol, dt.date(2026, 11, 5), Decimal("1865.23"), "kbs")


def test_check_prints_version_tier_and_close(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["market", "check"], market_client_factory=FakeClient) == 0
    out = capsys.readouterr().out
    assert "vnstock 5.2.1" in out
    assert "tier: golden" in out
    assert "works until 2027-10-27" in out
    assert "VN30 close 2026-11-05: 1865.23 (source kbs)" in out


def test_check_fails_when_not_logged_in(capsys: pytest.CaptureFixture[str]) -> None:
    status = AccountStatus("5.2.1", "guest", False, False, None, None, None)
    assert main(["market", "check"], market_client_factory=lambda: FakeClient(status)) == 1
    assert "vnstock register" in capsys.readouterr().err


def test_check_reports_the_failing_call(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["market", "check"], market_client_factory=lambda: FakeClient(fail_index=True)) == 1
    assert 'Market().index("VN30")' in capsys.readouterr().err


class _Frame:
    """Just enough of a DataFrame for VnstockClient.latest_index_close."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.columns = list(rows[0]) if rows else []
        self.attrs = {"source": "kbs"}

    def __len__(self) -> int:
        return len(self.rows)

    def sort_values(self, key: str) -> "_Frame":
        return _Frame(sorted(self.rows, key=lambda r: r[key]))

    @property
    def iloc(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeVnstock:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def Market(self) -> "_FakeVnstock":
        return self

    def index(self, symbol: str) -> "_FakeVnstock":
        return self

    def ohlcv(self, length: int) -> _Frame:
        return _Frame(self.rows)


def _client(rows: list[dict[str, Any]]) -> VnstockClient:
    client = VnstockClient.__new__(VnstockClient)
    client._vnstock = _FakeVnstock(rows)
    return client


def test_latest_close_takes_the_newest_row() -> None:
    rows = [
        {"time": dt.datetime(2026, 11, 5, 7, tzinfo=VN), "close": 1865.23},
        {"time": dt.datetime(2026, 11, 4, 7, tzinfo=VN), "close": 1862.07},
    ]
    close = _client(rows).latest_index_close("VN30")
    assert close == IndexClose("VN30", dt.date(2026, 11, 5), Decimal("1865.23"), "kbs")


def test_latest_close_raises_on_empty_result() -> None:
    with pytest.raises(MarketDataError, match="returned no rows"):
        _client([]).latest_index_close("VN30")
