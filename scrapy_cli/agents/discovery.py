"""Discovery agent — single agent that produces a full scraper end-to-end.

In this branch the agent does NOT use tool calling. It receives a pre-fetched
HTML sample of the target page in the prompt and emits a complete Python
scraper module as text. The orchestrator extracts the code block, writes it to
disk and runs the tests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Console

from .base import AgentResult, make_agent

SYSTEM = """You are the Discovery Agent — the sole agent in a web-scraping pipeline.

Given a target URL, a pre-fetched HTML sample, an expected JSON Schema and a list
of test cases, you must produce a complete, runnable Python scraper.

You have NO tools. Everything you need to inspect the site is already in the
sample HTML you receive. If a field cannot be located in the sample, make a
reasonable best guess (the user can iterate).

# Output format

Your response MUST contain exactly one fenced code block tagged `python`. The
block is the entire scraper file. Do not split the code across multiple blocks.
Do not include explanatory prose outside the block — it will be discarded.

# Scraper requirements

1. Expose `def scrape(url: str) -> dict`.
2. Use `requests` + `BeautifulSoup` (lxml parser) if the page is static HTML.
   Use Playwright sync API only if the sample HTML clearly shows JS-rendered
   content (empty body, hydration markers, etc.).
3. The returned dict MUST satisfy the provided JSON Schema:
   - Respect declared types (int, float, string).
   - Apply obvious transforms: strip currency symbols and convert to float,
     parse integers out of "In stock (22 available)"-style strings, map
     star-rating words ("One"/"Two"/.../"Five") to integers 1..5.
4. Be defensive: if an element is missing, return None for that field rather
   than crashing.
5. Add a `if __name__ == "__main__":` block that prints `scrape(sys.argv[1])`
   as JSON, so the file is also runnable standalone.
6. Use only stdlib + `requests` + `beautifulsoup4` + `lxml` + `playwright`.
   No other third-party imports.
7. Keep the file under ~200 lines. No classes unless strictly necessary.

# Retry feedback

If the user message includes a "PREVIOUS ATTEMPT FAILED" section with diff and
schema errors from a previous run, treat that as the highest-priority signal and
fix the scraper accordingly.
"""


def run_discovery(
    *,
    url: str,
    sample_html: str,
    schema: dict,
    tests: list[dict],
    console: Console,
    model: str,
    api_base_url: str | None = None,
    api_key: str | None = None,
    feedback: str | None = None,
) -> AgentResult:
    agent = make_agent(
        name="discovery",
        system=SYSTEM,
        model=model,
        console=console,
        api_base_url=api_base_url,
        api_key=api_key,
        max_tokens=8192,
    )

    parts = [
        f"Target URL: {url}",
        "",
        "Expected JSON Schema:",
        "```json",
        json.dumps(schema, indent=2, ensure_ascii=False),
        "```",
        "",
        f"Test cases ({len(tests)}):",
        "```json",
        json.dumps(tests, indent=2, ensure_ascii=False),
        "```",
        "",
        "Sample HTML (pre-fetched with Playwright, possibly truncated):",
        "```html",
        sample_html,
        "```",
    ]
    if feedback:
        parts.extend(
            [
                "",
                "## PREVIOUS ATTEMPT FAILED",
                feedback,
                "",
                "Rewrite the scraper from scratch addressing the issues above.",
            ]
        )
    parts.extend(["", "Now emit the scraper as a single ```python``` block."])

    return agent.run("\n".join(parts))


CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_python_code(text: str) -> str | None:
    """Pull the first ```python ... ``` block out of an LLM response."""
    match = CODE_BLOCK_RE.search(text)
    if match:
        return match.group(1).rstrip() + "\n"
    # Fallback: if the response looks like raw Python (starts with import/def), return as-is
    stripped = text.strip()
    if stripped.startswith(("import ", "from ", "def ", "#!")):
        return stripped + "\n"
    return None


def write_scraper(text: str, path: Path) -> bool:
    code = extract_python_code(text)
    if code is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return True
