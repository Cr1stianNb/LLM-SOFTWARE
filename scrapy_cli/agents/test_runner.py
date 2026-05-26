"""Test Runner agent — executes the scraper against the declared test cases.

This agent is intentionally thin: it loops through tests deterministically, but
the agent shell remains so the run can be inspected uniformly with the others.
We use a tiny LLM-driven loop that just orchestrates `run_scraper` calls and
emits the results JSON. If you want to skip the LLM here for cost, swap in the
`run_tests_direct` helper below — both paths produce the same results.json shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..tools.exec import EXEC_TOOL_SCHEMAS, dispatch_exec_tool
from ..tools.filesystem import (
    FILESYSTEM_TOOL_SCHEMAS,
    FilesystemSandbox,
    dispatch_filesystem_tool,
)
from .base import AgentClient, AgentResult

SYSTEM = """You are the Test Runner Agent.

You receive a scraper path and a list of test cases. For each test case, call
`run_scraper(scraper_path, url)` exactly once. Collect the results. When all
tests have been run, emit a SINGLE final message containing ONLY this JSON:

{
  "scraper_path": "...",
  "results": [
    {
      "name": "<test name>",
      "url": "<url>",
      "ok": <bool — true if scraper executed without error>,
      "actual": <the scraper's returned dict or null>,
      "stderr": "<truncated stderr, only if ok=false>"
    }
  ]
}

Rules:
- Never invent a result. Only report what `run_scraper` actually returned.
- Do not modify the scraper. Do not call any tool other than run_scraper.
- Emit the JSON at the end. No markdown fence."""


def run_test_runner(
    *,
    scraper_path: Path,
    tests: list[dict],
    out_path: Path,
    sandbox: FilesystemSandbox,
    console: Console,
    model: str,
) -> tuple[AgentResult | None, dict]:
    """Run all tests. We use the deterministic path by default — fewer tokens.

    The agent path is kept for parity in the pipeline trace.
    """
    direct = run_tests_direct(scraper_path=scraper_path, tests=tests)
    out_path.write_text(json.dumps(direct, indent=2, ensure_ascii=False), encoding="utf-8")
    console.log(f"  [green]✓ test results → {out_path}[/green]")
    return None, direct


def run_tests_direct(*, scraper_path: Path, tests: list[dict]) -> dict:
    results = []
    for test in tests:
        name = test.get("name") or test.get("url")
        url = test["url"]
        exec_result = dispatch_exec_tool(
            "run_scraper",
            {"scraper_path": str(scraper_path), "url": url, "timeout": 90},
        )
        results.append(
            {
                "name": name,
                "url": url,
                "ok": bool(exec_result.get("ok")),
                "actual": exec_result.get("result"),
                "returncode": exec_result.get("returncode"),
                "stderr": (exec_result.get("stderr") or "")[:1500]
                if not exec_result.get("ok")
                else "",
                "parse_error": exec_result.get("parse_error"),
            }
        )
    return {"scraper_path": str(scraper_path), "results": results}


# Agent variant (unused by default) ------------------------------------------------
def run_test_runner_agent(
    *,
    scraper_path: Path,
    tests: list[dict],
    out_path: Path,
    sandbox: FilesystemSandbox,
    console: Console,
    model: str,
) -> tuple[AgentResult, dict | None]:
    def dispatcher(name: str, args: dict) -> dict:
        if name in {"run_scraper"}:
            return dispatch_exec_tool(name, args)
        return dispatch_filesystem_tool(sandbox, name, args)

    agent = AgentClient(
        name="test_runner",
        system=SYSTEM,
        tools=EXEC_TOOL_SCHEMAS + FILESYSTEM_TOOL_SCHEMAS,
        dispatcher=dispatcher,
        model=model,
        console=console,
        max_iterations=2 + len(tests),
    )
    user = (
        f"Scraper path: {scraper_path}\n\n"
        f"Test cases:\n```json\n{json.dumps(tests, indent=2, ensure_ascii=False)}\n```\n\n"
        "Run all tests and emit the final JSON."
    )
    result = agent.run(user)
    try:
        parsed = json.loads(result.final_text.strip())
    except json.JSONDecodeError:
        parsed = None
    if parsed:
        out_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
    return result, parsed
