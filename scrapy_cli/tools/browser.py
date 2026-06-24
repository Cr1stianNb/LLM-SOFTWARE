"""Minimal Playwright fetcher.

In this branch the LLM has no browser tools — the orchestrator pre-fetches a
sample page with Playwright and passes the rendered HTML into the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

MAX_HTML_CHARS = 80_000


@dataclass
class FetchResult:
    ok: bool
    url: str
    final_url: str | None = None
    title: str | None = None
    html: str = ""
    truncated: bool = False
    total_chars: int = 0
    error: str | None = None


class BrowserSession:
    """Wraps a Playwright page and exposes a single `fetch` method."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    def fetch(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        max_chars: int = MAX_HTML_CHARS,
    ) -> FetchResult:
        if self._page is None:
            raise RuntimeError("BrowserSession not started — use as context manager")
        try:
            self._page.goto(url, wait_until=wait_until)
        except PlaywrightTimeout as exc:
            return FetchResult(ok=False, url=url, error=f"timeout: {exc}")

        html = self._page.content()
        return FetchResult(
            ok=True,
            url=url,
            final_url=self._page.url,
            title=self._page.title(),
            html=html[:max_chars],
            truncated=len(html) > max_chars,
            total_chars=len(html),
        )
