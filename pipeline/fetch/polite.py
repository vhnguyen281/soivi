"""Polite HTTP access (CLAUDE.md principle 6). Every network request goes through here.

- robots.txt is read once per origin and cached (default 24 h). A 4xx robots.txt
  means "no rules"; a 5xx or unreachable robots.txt means "don't crawl" until it
  can be read, which is the conservative reading of RFC 9309.
- At most one request per host every `crawler_min_delay_seconds` (>= 5 s),
  shared by robots.txt fetches, retries and browser page loads.
- Timeouts, connection errors, 429 and 5xx are retried with exponential backoff
  (honouring Retry-After). Other 4xx are not retried.
- Requests carry the User-Agent from settings, which must name a contact.

The rate limit lives in one process. Run one pipeline process at a time.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from core.config import Settings, get_settings

Clock = Callable[[], float]
Sleep = Callable[[float], None]

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_WAIT = 300.0  # never sleep longer than this, whatever Retry-After says


class FetchError(Exception):
    """A fetch failed for good (after retries, or not retryable)."""


class RobotsDisallowed(FetchError):
    """robots.txt forbids the URL, or could not be read."""


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}"


class RateLimiter:
    """Blocks until `delay` seconds have passed since the last request to a host."""

    def __init__(self, delay: float, clock: Clock = time.monotonic, sleep: Sleep = time.sleep):
        self.delay = delay
        self.clock = clock
        self.sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> float:
        """Wait if needed, then record a request. Returns the seconds waited."""
        waited = 0.0
        last = self._last.get(host)
        if last is not None:
            waited = max(0.0, self.delay - (self.clock() - last))
            if waited:
                self.sleep(waited)
        self._last[host] = self.clock()
        return waited


@dataclass
class _Robots:
    parser: RobotFileParser | None  # None = could not read robots.txt: crawl nothing
    fetched_at: float


@dataclass
class PoliteHttp:
    settings: Settings = field(default_factory=get_settings)
    timeout: float = 30.0
    max_attempts: int = 3
    backoff_base: float = 5.0  # seconds; attempt n waits base * 2**(n-1)
    robots_ttl: float = 24 * 3600
    clock: Clock = time.monotonic
    sleep: Sleep = time.sleep
    transport: httpx.BaseTransport | None = None  # tests only

    def __post_init__(self) -> None:
        if "@" not in self.user_agent:
            raise ValueError("CRAWLER_USER_AGENT must include a contact email")
        self.limiter = RateLimiter(self.settings.crawler_min_delay_seconds, self.clock, self.sleep)
        self.client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Language": "vi,en;q=0.5"},
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
        )
        self._robots: dict[str, _Robots] = {}

    @property
    def user_agent(self) -> str:
        return self.settings.crawler_user_agent

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PoliteHttp":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------- robots.txt

    def allowed(self, url: str) -> bool:
        origin = origin_of(url)
        cached = self._robots.get(origin)
        if cached is None or self.clock() - cached.fetched_at > self.robots_ttl:
            cached = _Robots(self._read_robots(origin), self.clock())
            self._robots[origin] = cached
        if cached.parser is None:
            return False
        return cached.parser.can_fetch(self.user_agent, url)

    def _read_robots(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            response = self._send("GET", f"{origin}/robots.txt")
        except FetchError:
            return None
        if response.status_code >= 500:
            return None
        if response.status_code >= 400:
            parser.parse([])  # no robots.txt: no rules
        else:
            parser.parse(response.text.splitlines())
        return parser

    def check_allowed(self, url: str) -> None:
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt does not allow {url} (or could not be read)")

    # ----------------------------------------------------------------- requests

    def request(
        self, url: str, method: str = "GET", data: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET (or a form POST, for read-only endpoints that need one) after the
        robots.txt check, with retries. Any final status is returned."""
        self.check_allowed(url)
        return self._send(method, url, data)

    def get(
        self, url: str, method: str = "GET", data: dict[str, str] | None = None
    ) -> httpx.Response:
        """Like request(), but raises FetchError unless the final status is 2xx."""
        response = self.request(url, method, data)
        if not response.is_success:
            raise FetchError(f"{method} {url} returned HTTP {response.status_code}")
        return response

    def _send(self, method: str, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self.limiter.wait(host_of(url))
            try:
                # data={} still sends an empty form body (some servlets need it)
                response = self.client.request(method, url, data=data if method == "POST" else None)
            except httpx.TransportError as exc:  # timeouts, connection errors
                last_error = f"{type(exc).__name__}: {exc}"
                retry_after = None
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                last_error = f"HTTP {response.status_code}"
                retry_after = _retry_after(response)
                if attempt == self.max_attempts:
                    return response
            if attempt < self.max_attempts:
                backoff = self.backoff_base * 2 ** (attempt - 1)
                self.sleep(min(max(backoff, retry_after or 0), MAX_RETRY_WAIT))
        raise FetchError(f"{method} {url} failed after {self.max_attempts} attempts: {last_error}")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())
