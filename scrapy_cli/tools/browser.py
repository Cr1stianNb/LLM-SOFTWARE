"""Playwright-based browser tools exposed to agents."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright, TimeoutError as PlaywrightTimeout

MAX_HTML_CHARS = 20_000
MAX_LIST_ITEMS = 50


@dataclass
class BrowserSession:
    """Wraps a Playwright page so agents can drive a single browser instance."""

    headless: bool = True
    timeout_ms: int = 20_000
    _playwright: Any = None
    _browser: Any = None
    _page: Page | None = None
    last_url: str | None = None

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

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession not started — use as context manager")
        return self._page

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict:
        try:
            self.page.goto(url, wait_until=wait_until)
        except PlaywrightTimeout as exc:
            return {"ok": False, "error": f"timeout: {exc}", "url": url}
        self.last_url = url
        return {
            "ok": True,
            "url": self.page.url,
            "title": self.page.title(),
        }

    def get_html(self, selector: str | None = None, max_chars: int = MAX_HTML_CHARS) -> dict:
        if selector:
            try:
                element = self.page.query_selector(selector)
            except Exception as exc:
                return {"ok": False, "error": f"invalid selector: {exc}"}
            if element is None:
                return {"ok": False, "error": "no element matched"}
            html = element.inner_html()
        else:
            html = self.page.content()
        truncated = len(html) > max_chars
        return {
            "ok": True,
            "html": html[:max_chars],
            "truncated": truncated,
            "total_chars": len(html),
        }

    def query(self, selector: str, attributes: list[str] | None = None) -> dict:
        try:
            elements = self.page.query_selector_all(selector)
        except Exception as exc:
            return {"ok": False, "error": f"invalid selector: {exc}"}

        attrs = attributes or ["href", "src", "id", "class"]
        items: list[dict] = []
        for el in elements[:MAX_LIST_ITEMS]:
            text = (el.inner_text() or "").strip()
            entry = {"text": text[:300]}
            for attr in attrs:
                val = el.get_attribute(attr)
                if val is not None:
                    entry[attr] = val
            items.append(entry)
        return {
            "ok": True,
            "match_count": len(elements),
            "returned": len(items),
            "truncated": len(elements) > MAX_LIST_ITEMS,
            "items": items,
        }

    def get_text(self, selector: str) -> dict:
        try:
            element = self.page.query_selector(selector)
        except Exception as exc:
            return {"ok": False, "error": f"invalid selector: {exc}"}
        if element is None:
            return {"ok": False, "error": "no element matched"}
        text = (element.inner_text() or "").strip()
        return {"ok": True, "text": text}

    def get_attribute(self, selector: str, attribute: str) -> dict:
        try:
            element = self.page.query_selector(selector)
        except Exception as exc:
            return {"ok": False, "error": f"invalid selector: {exc}"}
        if element is None:
            return {"ok": False, "error": "no element matched"}
        return {"ok": True, "value": element.get_attribute(attribute)}

    def list_links(self, selector: str | None = None) -> dict:
        sel = selector or "a[href]"
        try:
            elements = self.page.query_selector_all(sel)
        except Exception as exc:
            return {"ok": False, "error": f"invalid selector: {exc}"}
        items = []
        for el in elements[:MAX_LIST_ITEMS]:
            href = el.get_attribute("href")
            if not href:
                continue
            items.append({"text": (el.inner_text() or "").strip()[:200], "href": href})
        return {
            "ok": True,
            "match_count": len(elements),
            "returned": len(items),
            "items": items,
        }

    def screenshot(self, path: str | Path, full_page: bool = False) -> dict:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(target), full_page=full_page)
        return {"ok": True, "path": str(target)}


# ----------------------------------------------------------------------
# Anthropic tool schemas
# ----------------------------------------------------------------------

BROWSER_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "browser_navigate",
        "description": "Navigate the browser to a URL. Returns the final URL and page title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute URL to load."},
                "wait_until": {
                    "type": "string",
                    "enum": ["load", "domcontentloaded", "networkidle"],
                    "default": "domcontentloaded",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_get_html",
        "description": (
            "Return the HTML of the page (or a single selector). Truncated to ~20k chars. "
            "Use a selector whenever possible to avoid context bloat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Optional CSS selector."},
                "max_chars": {"type": "integer", "default": MAX_HTML_CHARS},
            },
        },
    },
    {
        "name": "browser_query",
        "description": (
            "Run a CSS selector and return up to 50 matches with their inner text and "
            "common attributes (href, src, id, class). Best tool for mapping repeating items."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "attributes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra attributes to extract per match.",
                },
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_get_text",
        "description": "Return the inner text of the first element matching a selector.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "browser_get_attribute",
        "description": "Return a single attribute value from the first element matching a selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "attribute": {"type": "string"},
            },
            "required": ["selector", "attribute"],
        },
    },
    {
        "name": "browser_list_links",
        "description": "List anchor links (up to 50) on the page, optionally scoped to a selector.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
        },
    },
]


def dispatch_browser_tool(session: BrowserSession, name: str, args: dict) -> dict:
    """Route an Anthropic tool_use call to the BrowserSession method."""
    if name == "browser_navigate":
        return session.navigate(args["url"], args.get("wait_until", "domcontentloaded"))
    if name == "browser_get_html":
        return session.get_html(args.get("selector"), args.get("max_chars", MAX_HTML_CHARS))
    if name == "browser_query":
        return session.query(args["selector"], args.get("attributes"))
    if name == "browser_get_text":
        return session.get_text(args["selector"])
    if name == "browser_get_attribute":
        return session.get_attribute(args["selector"], args["attribute"])
    if name == "browser_list_links":
        return session.list_links(args.get("selector"))
    return {"ok": False, "error": f"unknown browser tool: {name}"}
