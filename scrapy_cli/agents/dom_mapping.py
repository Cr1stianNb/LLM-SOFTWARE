"""DOM Mapping agent — produces exact CSS selectors for each schema field."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..tools.browser import BROWSER_TOOL_SCHEMAS, BrowserSession, dispatch_browser_tool
from .base import AgentClient, AgentResult

SYSTEM = """You are the DOM Mapping Agent in a web-scraping pipeline.

You receive:
- An expected output schema (JSON Schema)
- A discovery plan written by a previous agent
- A sample URL to inspect

Your job: produce a JSON object that maps every schema field to a precise CSS
selector and extraction recipe. Use the browser tools to verify selectors against
the live page before committing to them.

Output format — when you are done, emit a SINGLE final message containing only
this JSON object (no Markdown fence, no prose):

{
  "sample_url": "<url you mapped against>",
  "page_kind": "detail" | "listing" | "mixed",
  "container": "<optional CSS selector for the root item, e.g. for listings>",
  "fields": {
    "<field_name>": {
      "selector": "<CSS selector>",
      "source": "text" | "attribute" | "html",
      "attribute": "<name if source=attribute>",
      "transform": "<one of: trim, int, float, currency, rating_words, none>",
      "notes": "<short note>"
    }
  },
  "pagination": {
    "next_selector": "<CSS selector or null>",
    "strategy": "<rel-next | numbered | infinite-scroll | none>"
  }
}

Rules:
- Selectors MUST be valid CSS (no XPath).
- Prefer stable selectors (semantic classes, data-* attrs) over brittle nth-child.
- For each field, actually call browser_query or browser_get_text to confirm it
  yields the expected value before you finalize.
- transform="rating_words" means the source emits words like "One/Two/Three" that
  must be mapped to integers 1..5.
- transform="currency" means strip currency symbols and return a float.
- If a field can't be located, set selector to null and explain in notes.

Be efficient — at most ~15 tool calls."""


def run_dom_mapping(
    *,
    url: str,
    schema: dict,
    plan_md: str,
    out_path: Path,
    console: Console,
    model: str,
    browser: BrowserSession,
) -> tuple[AgentResult, dict | None]:
    def dispatcher(name: str, args: dict) -> dict:
        return dispatch_browser_tool(browser, name, args)

    agent = AgentClient(
        name="dom_mapping",
        system=SYSTEM,
        tools=BROWSER_TOOL_SCHEMAS,
        dispatcher=dispatcher,
        model=model,
        console=console,
        max_iterations=18,
    )

    user = (
        f"Sample URL: {url}\n\n"
        f"Expected schema:\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n\n"
        f"Discovery plan:\n{plan_md}\n\n"
        "Verify selectors against the live page, then emit the final JSON."
    )

    result = agent.run(user)
    parsed = _extract_json(result.final_text)
    if parsed is not None:
        out_path.write_text(
            json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        console.log(f"  [green]✓ dom map saved → {out_path}[/green]")
    else:
        out_path.write_text(result.final_text, encoding="utf-8")
        console.log(f"  [yellow]⚠ dom map not valid JSON — raw saved to {out_path}[/yellow]")
    return result, parsed


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown fences
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: find first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None
