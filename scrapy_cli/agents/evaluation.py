"""Evaluation agent — compares actual scraper output to expected outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
from rich.console import Console

from ..tools.filesystem import (
    FILESYSTEM_TOOL_SCHEMAS,
    FilesystemSandbox,
    dispatch_filesystem_tool,
)
from .base import AgentClient, AgentResult

SYSTEM = """You are the Evaluation Agent in a web-scraping pipeline.

You receive:
- The JSON Schema the scraper output should match
- The test cases with `expected` outputs
- The actual results from running the scraper

You also get the deterministic comparison already computed: schema validation
errors and field-level diffs vs. expected.

Your job: write a Markdown report that:
1. Reports an overall score (X/N tests passing).
2. For each failing test, explains WHY it failed in plain language (selector
   probably wrong? transform issue? site changed?).
3. Gives SPECIFIC, actionable feedback the Implementation Agent can use to fix
   the scraper. Reference field names and the exact diff.
4. If everything passes, says so concisely and stops.

Keep the report under ~500 words. The first line MUST be a verdict in the form:

`VERDICT: PASS` or `VERDICT: FAIL (k/n passing)`

That line is parsed programmatically — do not deviate from the format."""


@dataclass
class EvaluationOutcome:
    verdict_pass: bool
    passing: int
    total: int
    report_md: str
    per_test: list[dict]


def evaluate_deterministic(
    *,
    schema: dict,
    tests: list[dict],
    actual_results: dict,
) -> list[dict]:
    """Compute schema validation + diff per test case before sending to LLM."""
    by_name: dict[str, dict] = {}
    for r in actual_results.get("results", []):
        key = r.get("name") or r.get("url")
        by_name[key] = r

    out: list[dict] = []
    for test in tests:
        name = test.get("name") or test.get("url")
        expected = test.get("expected")
        actual_entry = by_name.get(name) or {}
        actual = actual_entry.get("actual")

        schema_errors: list[str] = []
        if actual is not None:
            try:
                jsonschema.validate(instance=actual, schema=schema)
            except jsonschema.ValidationError as exc:
                schema_errors.append(exc.message)

        diff = _diff(expected, actual) if expected is not None else []
        passed = (
            actual_entry.get("ok")
            and not schema_errors
            and not diff
        )
        out.append(
            {
                "name": name,
                "url": test.get("url"),
                "passed": bool(passed),
                "ran_ok": bool(actual_entry.get("ok")),
                "schema_errors": schema_errors,
                "diff": diff,
                "actual": actual,
                "expected": expected,
                "stderr": actual_entry.get("stderr") or "",
            }
        )
    return out


def _diff(expected: Any, actual: Any, path: str = "") -> list[dict]:
    out: list[dict] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = set(expected) | set(actual)
        for k in sorted(keys):
            sub = f"{path}.{k}" if path else k
            if k not in actual:
                out.append({"path": sub, "kind": "missing", "expected": expected[k]})
            elif k not in expected:
                out.append({"path": sub, "kind": "unexpected", "actual": actual[k]})
            else:
                out.extend(_diff(expected[k], actual[k], sub))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(
                {
                    "path": path,
                    "kind": "length_mismatch",
                    "expected_len": len(expected),
                    "actual_len": len(actual),
                }
            )
        for i in range(min(len(expected), len(actual))):
            out.extend(_diff(expected[i], actual[i], f"{path}[{i}]"))
    else:
        if expected != actual:
            out.append(
                {"path": path or "(root)", "kind": "value", "expected": expected, "actual": actual}
            )
    return out


def run_evaluation(
    *,
    schema: dict,
    tests: list[dict],
    results: dict,
    out_path: Path,
    sandbox: FilesystemSandbox,
    console: Console,
    model: str,
) -> EvaluationOutcome:
    per_test = evaluate_deterministic(schema=schema, tests=tests, actual_results=results)
    passing = sum(1 for t in per_test if t["passed"])
    total = len(per_test)

    def dispatcher(name: str, args: dict) -> dict:
        return dispatch_filesystem_tool(sandbox, name, args)

    agent = AgentClient(
        name="evaluation",
        system=SYSTEM,
        tools=FILESYSTEM_TOOL_SCHEMAS,
        dispatcher=dispatcher,
        model=model,
        console=console,
        max_iterations=4,
        max_tokens=4096,
    )

    user = (
        f"Schema:\n```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```\n\n"
        f"Tests:\n```json\n{json.dumps(tests, indent=2, ensure_ascii=False)}\n```\n\n"
        f"Actual results:\n```json\n{json.dumps(results, indent=2, ensure_ascii=False)}\n```\n\n"
        f"Deterministic per-test analysis (schema_errors + diff):\n"
        f"```json\n{json.dumps(per_test, indent=2, ensure_ascii=False)}\n```\n\n"
        f"Summary: {passing}/{total} passing.\n\n"
        "Write the report. Remember the first line must be the VERDICT line."
    )

    result = agent.run(user)
    report_md = result.final_text.strip()
    out_path.write_text(report_md, encoding="utf-8")
    console.log(f"  [green]✓ report saved → {out_path}[/green]")

    first_line = report_md.splitlines()[0] if report_md else ""
    verdict_pass = first_line.upper().startswith("VERDICT: PASS")

    return EvaluationOutcome(
        verdict_pass=verdict_pass,
        passing=passing,
        total=total,
        report_md=report_md,
        per_test=per_test,
    )
