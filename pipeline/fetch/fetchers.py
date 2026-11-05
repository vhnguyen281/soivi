"""Fetchers turn a URL into bytes. All of them go through PoliteHttp's robots.txt
check and per-host rate limit.

- HttpFetcher:    plain GET.
- PdfFetcher:     GET, and the body must really be a PDF.
- BrowserFetcher: headless Chromium via Playwright, for pages that need JavaScript.
                  Only imported when an adapter asks for it.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Protocol

from core.enums import FetchMethod
from pipeline.fetch.polite import FetchError, PoliteHttp, host_of


@dataclass(frozen=True)
class FetchResult:
    url: str  # requested
    final_url: str  # after redirects
    status: int
    content_type: str | None
    content: bytes
    fetched_at: dt.datetime


class Fetcher(Protocol):
    """`wait_for` is only used by the browser fetcher: text that must appear in the
    rendered page before it counts as loaded."""

    def fetch(
        self,
        url: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
        wait_for: str | None = None,
    ) -> FetchResult: ...


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class HttpFetcher:
    def __init__(self, http: PoliteHttp) -> None:
        self.http = http

    def fetch(
        self,
        url: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
        wait_for: str | None = None,
    ) -> FetchResult:
        response = self.http.get(url, method, data)
        content_type = response.headers.get("content-type", "").split(";")[0].strip() or None
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status=response.status_code,
            content_type=content_type,
            content=response.content,
            fetched_at=_now(),
        )


class PdfFetcher(HttpFetcher):
    def fetch(
        self,
        url: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
        wait_for: str | None = None,
    ) -> FetchResult:
        result = super().fetch(url, method, data, wait_for)
        if not result.content.startswith(b"%PDF-"):
            raise FetchError(f"{url} did not return a PDF (content-type {result.content_type!r})")
        return FetchResult(**{**result.__dict__, "content_type": "application/pdf"})


class BrowserFetcher:
    """Renders the page in headless Chromium and returns the final HTML.

    Sub-resources (scripts, images) are loaded by the browser itself; only the
    page navigation is counted against the per-host rate limit.
    """

    def __init__(self, http: PoliteHttp, wait_until: str = "networkidle") -> None:
        self.http = http
        self.wait_until = wait_until
        self._playwright: Any = None
        self._browser: Any = None

    def _ensure_browser(self) -> Any:
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
        return self._browser

    def fetch(
        self,
        url: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
        wait_for: str | None = None,
    ) -> FetchResult:
        if method != "GET":
            raise FetchError("the browser fetcher only loads pages with GET")
        self.http.check_allowed(url)
        self.http.limiter.wait(host_of(url))
        try:
            browser = self._ensure_browser()
        except Exception as exc:  # e.g. Chromium not installed
            raise FetchError(f"could not start headless Chromium: {exc}") from exc
        context = browser.new_context(
            user_agent=self.http.user_agent, locale="vi-VN", java_script_enabled=True
        )
        try:
            page = context.new_page()
            timeout = self.http.timeout * 1000
            # With wait_for, don't wait for the network to go quiet (analytics can keep
            # it busy forever); wait for the content we need instead.
            wait_until = "load" if wait_for else self.wait_until
            response = page.goto(url, wait_until=wait_until, timeout=timeout)
            status = response.status if response is not None else 0
            if not 200 <= status < 300:
                raise FetchError(f"browser GET {url} returned HTTP {status}")
            if wait_for:
                try:
                    page.get_by_text(wait_for).first.wait_for(timeout=timeout)
                except Exception as exc:
                    raise FetchError(
                        f"browser GET {url}: {wait_for!r} did not appear (page incomplete)"
                    ) from exc
            return FetchResult(
                url=url,
                final_url=page.url,
                status=status,
                content_type="text/html",
                content=page.content().encode("utf-8"),
                fetched_at=_now(),
            )
        except FetchError:
            raise
        except Exception as exc:  # Playwright timeouts and navigation errors
            raise FetchError(f"browser GET {url} failed: {type(exc).__name__}: {exc}") from exc
        finally:
            context.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = self._playwright = None


class Fetchers:
    """One shared PoliteHttp (so robots cache and rate limit are shared) and a
    fetcher per method. The browser starts only on first use."""

    def __init__(self, http: PoliteHttp) -> None:
        self.http = http
        self._http_fetcher = HttpFetcher(http)
        self._pdf_fetcher = PdfFetcher(http)
        self._browser_fetcher: BrowserFetcher | None = None

    def for_method(self, method: FetchMethod) -> Fetcher:
        if method is FetchMethod.BROWSER:
            if self._browser_fetcher is None:
                self._browser_fetcher = BrowserFetcher(self.http)
            return self._browser_fetcher
        if method is FetchMethod.PDF:
            return self._pdf_fetcher
        # OCR sources download an image or scanned PDF; OCR happens in parse().
        return self._http_fetcher

    def close(self) -> None:
        if self._browser_fetcher is not None:
            self._browser_fetcher.close()
        self.http.close()
