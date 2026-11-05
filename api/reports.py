"""Guards for POST /reports: a per-IP rate limit and a pluggable captcha check.

Community reports never publish a value (CLAUDE.md principle 1): they are stored
for triage and can only lead to a re-check of the bank's own source.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from core.config import Settings

CAPTCHA_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://api.hcaptcha.com/siteverify",
}

# Screenshot types we accept, by their first bytes (the declared type can lie).
IMAGE_TYPES = {
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
}


def image_type(data: bytes) -> tuple[str, str] | None:
    for magic, kind in IMAGE_TYPES.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


@dataclass
class RateLimiter:
    """At most `limit` requests per `window` seconds per key (client IP)."""

    limit: int
    window: float = 3600.0
    clock: Callable[[], float] = time.monotonic
    hits: dict[str, deque[float]] = field(default_factory=dict)

    def check(self, key: str) -> float | None:
        """None if allowed (and counted); else seconds until the next slot."""
        now = self.clock()
        q = self.hits.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return q[0] + self.window - now
        q.append(now)
        return None


class Captcha(Protocol):
    enabled: bool

    def verify(self, token: str | None, ip: str | None) -> bool: ...


class NoCaptcha:
    """Captcha off (development, or until a provider is configured)."""

    enabled = False

    def verify(self, token: str | None, ip: str | None) -> bool:
        return True


@dataclass
class SiteVerifyCaptcha:
    """Cloudflare Turnstile or hCaptcha: both answer POST siteverify with {success}."""

    provider: str
    secret: str
    transport: httpx.BaseTransport | None = None  # tests
    enabled: bool = True

    def verify(self, token: str | None, ip: str | None) -> bool:
        if not token:
            return False
        data = {"secret": self.secret, "response": token}
        if ip:
            data["remoteip"] = ip
        try:
            with httpx.Client(timeout=10, transport=self.transport) as client:
                reply = client.post(CAPTCHA_URLS[self.provider], data=data)
            return bool(reply.is_success and reply.json().get("success") is True)
        except (httpx.HTTPError, ValueError):
            return False  # can't verify: refuse rather than let it through


def make_captcha(settings: Settings) -> Captcha:
    if not settings.captcha_provider:
        return NoCaptcha()
    if not settings.captcha_secret:
        raise RuntimeError("CAPTCHA_PROVIDER is set but CAPTCHA_SECRET is empty")
    return SiteVerifyCaptcha(settings.captcha_provider, settings.captcha_secret)
