"""Implementation agent — writes the actual scraper module."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..tools.filesystem import (
    FILESYSTEM_TOOL_SCHEMAS,
    FilesystemSandbox,
    dispatch_filesystem_tool,
)
from .base import AgentClient, AgentResult

SYSTEM = """You are the Implementation Agent in a web-scraping pipeline.

Your job: write a single self-contained Python module that scrapes one URL and
returns a dict matching the expected JSON Schema.

Inputs you receive:
- Expected schema
- A DOM map JSON produced by a previous agent
- The discovery plan
- Optional: feedback from a previous failed run (if this is a retry)

Output module requirements:
1. File path is provided to you. WRITE the file using `write_file`.
2. The module MUST expose: `def scrape(url: str) -> dict`.
3. Use Playwright (sync API) if the DOM map / plan say JS is required, otherwise
   prefer `requests` + `BeautifulSoup` (faster).
4. Apply the transforms declared in the DOM map:
   - "trim": str.strip()
   - "int": int(re.sub(r'[^0-9-]', '', s))
   - "float": float on cleaned numeric string
   - "currency": strip currency chars, return float
   - "rating_words": map {"One":1,"Two":2,"Three":3,"Four":4,"Five":5}
   - "none": leave as-is
5. Be defensive: if an element is missing, return None for that field (don't crash).
6. No external network calls beyond the target URL.
7. Add a `if __name__ == "__main__":` block that prints scrape(sys.argv[1]) as JSON,
   so the file is also runnable standalone.
8. Keep the code under ~150 lines. No classes unless necessary. No CLI framework.

When you're done writing the file, your final assistant message should be a one-line
confirmation like: `Wrote scraper to <path>`. Do not include the code in the chat —
the file on disk is the deliverable."""


def run_implementation(
    *,
    schema: dict,
    dom_map: dict,
    plan_md: str,
    scraper_path: Path,
    sandbox: FilesystemSandbox,
    console: Console,
    model: str,
    feedback: str | None = None,
) -> AgentResult:
    def dispatcher(name: str, args: dict) -> dict:
        return dispatch_filesystem_tool(sandbox, name, args)

    agent = AgentClient(
        name="implementation",
        system=SYSTEM,
        tools=FILESYSTEM_TOOL_SCHEMAS,
        dispatcher=dispatcher,
        model=model,
        console=console,
        max_iterations=10,
        max_tokens=8192,
    )

    parts = [
        f"Target scraper path: {scraper_path}",
        "",
        "Expected schema:",
        "```json",
        json.dumps(schema, indent=2, ensure_ascii=False),
        "```",
        "",
        "DOM map:",
        "```json",
        json.dumps(dom_map, indent=2, ensure_ascii=False),
        "```",
        "",
        "Discovery plan:",
        plan_md,
    ]
    if feedback:
        parts.extend(
            [
                "",
                "PREVIOUS ATTEMPT FAILED. Evaluation feedback:",
                feedback,
                "",
                "Fix the scraper accordingly and rewrite the file at the target path.",
            ]
        )
    parts.append("")
    parts.append("Now write the scraper file.")

    result = agent.run("\n".join(parts))
    console.log(f"  [green]✓ scraper written → {scraper_path}[/green]")
    return result
