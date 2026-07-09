"""End-to-end pipeline — single agent + deterministic evaluation, no tool calling."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema
from rich.console import Console
from rich.panel import Panel

from .agents.discovery import run_discovery, write_scraper
from .tools.browser import BrowserSession
from .tools.exec import run_scraper


@dataclass
class PipelineConfig:
    url: str
    schema: dict
    tests: list[dict]
    project_root: Path
    model: str = "claude-sonnet-4-6"
    max_retries: int = 2
    headless: bool = True
    slug: str | None = None
    api_base_url: str | None = None
    api_key: str | None = None


@dataclass
class EvaluationOutcome:
    verdict_pass: bool
    passing: int
    total: int
    per_test: list[dict]
    report_md: str


@dataclass
class PipelineRun:
    run_dir: Path
    scraper_path: Path
    sample_html_path: Path
    results_path: Path
    report_path: Path
    raw_response_path: Path
    outcome: EvaluationOutcome | None = None
    attempts: int = 0
    artifacts: dict[str, Path] = field(default_factory=dict)


def execute(config: PipelineConfig, console: Console | None = None) -> PipelineRun:
    console = console or Console(legacy_windows=False)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    slug = config.slug or _slugify(config.url)
    run_dir = config.project_root / "runs" / f"{timestamp}-{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    scrapers_dir = config.project_root / "scrapers"
    scrapers_dir.mkdir(parents=True, exist_ok=True)
    scraper_path = scrapers_dir / f"{slug}.py"

    sample_html_path = run_dir / "sample.html"
    raw_response_path = run_dir / "agent_response.md"
    results_path = run_dir / "results.json"
    report_path = run_dir / "report.md"

    (run_dir / "input_schema.json").write_text(
        json.dumps(config.schema, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "input_tests.json").write_text(
        json.dumps(config.tests, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    sample_url = config.tests[0]["url"] if config.tests else config.url

    pipeline_run = PipelineRun(
        run_dir=run_dir,
        scraper_path=scraper_path,
        sample_html_path=sample_html_path,
        results_path=results_path,
        report_path=report_path,
        raw_response_path=raw_response_path,
    )

    # ----- Pre-fetch sample HTML (no LLM yet) -----
    console.print(Panel.fit("[bold]Pre-fetch[/bold] sample HTML", style="cyan"))
    with BrowserSession(headless=config.headless) as browser:
        fetch_result = browser.fetch(sample_url)
    if not fetch_result.ok:
        console.print(f"[red]Failed to fetch sample URL: {fetch_result.error}[/red]")
        return pipeline_run
    sample_html_path.write_text(fetch_result.html, encoding="utf-8")
    console.log(
        f"  fetched {fetch_result.total_chars} chars from {sample_url} "
        f"({'truncated' if fetch_result.truncated else 'full'})"
    )

    feedback: str | None = None
    outcome: EvaluationOutcome | None = None

    for attempt in range(1, config.max_retries + 2):
        pipeline_run.attempts = attempt
        console.print(
            Panel.fit(f"[bold]Discovery[/bold] (attempt {attempt})", style="cyan")
        )

        agent_result = run_discovery(
            url=config.url,
            sample_html=fetch_result.html,
            schema=config.schema,
            tests=config.tests,
            console=console,
            model=config.model,
            api_base_url=config.api_base_url,
            api_key=config.api_key,
            feedback=feedback,
        )
        raw_response_path.write_text(agent_result.final_text, encoding="utf-8")

        if not write_scraper(agent_result.final_text, scraper_path):
            console.print(
                "[red]Agent response did not contain a python code block. "
                f"See {raw_response_path}.[/red]"
            )
            return pipeline_run
        console.log(f"  [green]scraper written -> {scraper_path}[/green]")

        # ----- Run tests (deterministic) -----
        console.print(Panel.fit("[bold]Run tests[/bold]", style="cyan"))
        results = _run_all_tests(scraper_path, config.tests, console)
        results_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # ----- Evaluate (deterministic) -----
        console.print(Panel.fit("[bold]Evaluate[/bold]", style="cyan"))
        outcome = _evaluate(config.schema, config.tests, results)
        report_path.write_text(outcome.report_md, encoding="utf-8")
        pipeline_run.outcome = outcome
        console.print(
            f"[bold]{'PASS' if outcome.verdict_pass else 'FAIL'}[/bold] — "
            f"{outcome.passing}/{outcome.total} passing"
        )

        if outcome.verdict_pass:
            break
        if attempt > config.max_retries:
            break
        feedback = outcome.report_md
        console.print(
            f"[yellow]-> retrying Discovery with feedback "
            f"(attempt {attempt + 1} of {config.max_retries + 1})[/yellow]"
        )

    manifest = {
        "url": config.url,
        "model": config.model,
        "slug": slug,
        "attempts": pipeline_run.attempts,
        "verdict_pass": outcome.verdict_pass if outcome else False,
        "passing": outcome.passing if outcome else 0,
        "total": outcome.total if outcome else 0,
        "artifacts": {
            "scraper": str(scraper_path),
            "sample_html": str(sample_html_path),
            "agent_response": str(raw_response_path),
            "results": str(results_path),
            "report": str(report_path),
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    pipeline_run.artifacts = {k: Path(v) for k, v in manifest["artifacts"].items()}
    return pipeline_run


# ----------------------------------------------------------------------
# Test running
# ----------------------------------------------------------------------

def _run_all_tests(scraper_path: Path, tests: list[dict], console: Console) -> dict:
    results = []
    for test in tests:
        name = test.get("name") or test["url"]
        console.log(f"  running {name}")
        exec_result = run_scraper(str(scraper_path), test["url"])
        results.append(
            {
                "name": name,
                "url": test["url"],
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


# ----------------------------------------------------------------------
# Deterministic evaluation
# ----------------------------------------------------------------------

def _evaluate(schema: dict, tests: list[dict], actual_results: dict) -> EvaluationOutcome:
    by_name: dict[str, dict] = {}
    for r in actual_results.get("results", []):
        key = r.get("name") or r.get("url")
        by_name[key] = r

    per_test: list[dict] = []
    for test in tests:
        name = test.get("name") or test["url"]
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
        passed = bool(actual_entry.get("ok")) and not schema_errors and not diff
        per_test.append(
            {
                "name": name,
                "url": test["url"],
                "passed": passed,
                "ran_ok": bool(actual_entry.get("ok")),
                "schema_errors": schema_errors,
                "diff": diff,
                "actual": actual,
                "expected": expected,
                "stderr": actual_entry.get("stderr") or "",
            }
        )

    passing = sum(1 for t in per_test if t["passed"])
    total = len(per_test)
    report_md = _render_report(per_test, passing, total)
    return EvaluationOutcome(
        verdict_pass=passing == total and total > 0,
        passing=passing,
        total=total,
        per_test=per_test,
        report_md=report_md,
    )


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


def _render_report(per_test: list[dict], passing: int, total: int) -> str:
    verdict = "PASS" if passing == total and total > 0 else "FAIL"
    lines = [f"VERDICT: {verdict} ({passing}/{total} passing)", ""]
    for t in per_test:
        status = "[PASS]" if t["passed"] else "[FAIL]"
        lines.append(f"## {status} {t['name']}")
        lines.append(f"- url: {t['url']}")
        if not t["ran_ok"]:
            lines.append("- scraper raised an error:")
            lines.append("```")
            lines.append((t.get("stderr") or "").strip() or "(no stderr captured)")
            lines.append("```")
        if t["schema_errors"]:
            lines.append("- schema validation errors:")
            for err in t["schema_errors"]:
                lines.append(f"  - {err}")
        if t["diff"]:
            lines.append("- field diffs (expected vs actual):")
            for d in t["diff"]:
                if d["kind"] == "value":
                    lines.append(
                        f"  - `{d['path']}`: expected {d['expected']!r}, got {d['actual']!r}"
                    )
                elif d["kind"] == "missing":
                    lines.append(f"  - `{d['path']}`: missing (expected {d['expected']!r})")
                elif d["kind"] == "unexpected":
                    lines.append(f"  - `{d['path']}`: unexpected key (got {d['actual']!r})")
                elif d["kind"] == "length_mismatch":
                    lines.append(
                        f"  - `{d['path']}`: length {d['actual_len']} vs expected {d['expected_len']}"
                    )
        if t["passed"]:
            lines.append("- all checks passed.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _slugify(url: str) -> str:
    host = urlparse(url).hostname or "site"
    host = host.replace("www.", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", host).strip("_").lower()
    return slug or "site"
