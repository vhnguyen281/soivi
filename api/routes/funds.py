"""GET /funds/stats: the latest approved fund-group statistics (phase A).

Only releases a named reviewer approved are served; draft runs stay in the review app.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from api.common import send
from api.deps import DB, Cache
from api.schemas import FundStatsOut
from core.funds.release import latest_release

router = APIRouter(tags=["funds"])

METHOD = (
    "Annualised returns from month-end NAV per unit (ETFs: closing price) over 1, 3 and 5 years; "
    "volatility of monthly log returns over 36 months; maximum drawdown over 60 months. "
    "Benchmarks are the VNCMA return series for the same window: VN30 with dividend yield "
    "(equity funds, ETFs), 12-month deposits (bond funds), 50/50 (balanced funds)."
)
SOURCE = (
    "NAV per unit from CafeF via vnstock (aggregated; not checked with each fund manager). "
    "Only derived figures are published."
)
DISCLAIMER = {
    "vi": "Lợi nhuận quá khứ không bảo đảm kết quả tương lai. Số liệu tổng hợp theo nhóm, "
    "để tham khảo, không phải lời khuyên đầu tư.",
    "en": "Past returns do not guarantee future results. Group statistics for reference, "
    "not investment advice.",
}


@router.get("/funds/stats", response_model=FundStatsOut, summary="Fund statistics by group")
def fund_stats(request: Request, session: DB, cache: Cache) -> Response:
    release = latest_release(session)
    if release is None:
        raise HTTPException(404, "no approved fund statistics yet")

    def build() -> FundStatsOut:
        return FundStatsOut.model_validate(
            {
                **release.payload,
                "approved_by": release.approved_by,
                "approved_at": release.approved_at,
                "payload_sha256": release.payload_sha256,
                "method": METHOD,
                "source": SOURCE,
                "disclaimer": DISCLAIMER,
            }
        )

    return send(request, cache, build)
