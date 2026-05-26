"""Discovery agent — explores the site and proposes a scraping strategy."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..tools.browser import BROWSER_TOOL_SCHEMAS, BrowserSession, dispatch_browser_tool
from .base import AgentClient, AgentResult

SYSTEM = """You are the Discovery Agent in a web-scraping pipeline.

Your job: explore the target website and produce a concise plan describing HOW to
extract the requested fields. You do NOT write any scraper code.

You have browser tools. Use them sparingly:
1. Navigate to the start URL.
2. Inspect the page structure (title, layout, repeating items).
3. If the start URL is an index/listing, click into one detail page.
4. Decide whether the site is static HTML (no JS needed) or requires a browser.

Produce a final plan in Markdown with the following sections:

## Site overview
- 1-3 sentences describing what the site is.
- URL pattern(s) you observed.

## Extraction strategy
- Static fetch (requests + BeautifulSoup) OR full browser (Playwright)?
- Justify in one sentence based on what you saw.

## Field-by-field plan
For each field in the expected schema, describe (in plain English) where on the
page that field appears and roughly how it should be located (e.g. "inside the
.product-info block, second <p>"). Do NOT commit to exact CSS selectors yet —
that is the next agent's job.

## Risks & notes
- Pagination, rate limits, infinite scroll, login walls, CAPTCHA, anti-bot.
- Anything the next agent should know.

Keep the plan under ~400 words. End your turn with the full Markdown plan as
your final text response (no tools)."""


def run_discovery(
    *,
    url: str,
    schema: dict,
    out_path: Path,
    console: Console,
    model: str,
    browser: BrowserSession,
) -> AgentResult:
    def dispatcher(name: str, args: dict) -> dict:
        return dispatch_browser_tool(browser, name, args)

    agent = AgentClient(
        name="discovery",
        system=SYSTEM,
        tools=BROWSER_TOOL_SCHEMAS,
        dispatcher=dispatcher,
        model=model,
        console=console,
        max_iterations=12,
    )

    user = (
        f"Start URL: {url}\n\n"
        f"Expected output schema (JSON Schema):\n```json\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n\n"
        "Explore the site and produce the plan."
    )

    result = agent.run(user)
    out_path.write_text(result.final_text, encoding="utf-8")
    console.log(f"  [green]✓ plan saved → {out_path}[/green]")
    return result
