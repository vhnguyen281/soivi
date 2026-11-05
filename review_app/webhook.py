"""Tell the public site that approved values changed, so it rebuilds its pages.

Called in the background after an approval. Never raises: the approval is already
committed, and the site also refreshes on its own every hour.
"""

import logging

import httpx

from core.config import Settings

log = logging.getLogger(__name__)
HEADER = "X-Soivi-Secret"


def notify_site(settings: Settings, transport: httpx.BaseTransport | None = None) -> bool:
    if not settings.site_revalidate_url:
        return False
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            reply = client.post(
                settings.site_revalidate_url,
                headers={HEADER: settings.site_revalidate_secret},
                json={"reason": "approved"},
            )
        if reply.is_success:
            return True
        log.warning("site revalidation answered HTTP %s", reply.status_code)
    except httpx.HTTPError as exc:
        log.warning("site revalidation failed: %s", type(exc).__name__)
    return False
