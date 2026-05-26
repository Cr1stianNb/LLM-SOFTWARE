"""End-to-end pipeline orchestration."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel

from .agents.discovery import run_discovery
from .agents.dom_mapping import run_dom_mapping
from .agents.evaluation import EvaluationOutcome, run_evaluation
from .agents.implementation import run_implementation
from .agents.test_runner import run_test_runner
from .tools.browser import BrowserSession
from .tools.filesystem import FilesystemSandbox


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


@dataclass
class PipelineRun:
    run_dir: Path
    scraper_path: Path
    plan_path: Path
    dom_map_path: Path
    results_path: Path
    report_path: Path
    outcome: EvaluationOutcome | None = None
    attempts: int = 0
    artifacts: dict[str, Path] = field(default_factory=dict)


def execute(config: PipelineConfig, console: Console | None = None) -> PipelineRun:
    console = console or Console()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    slug = config.slug or _slugify(config.url)
    run_dir = config.project_root / "runs" / f"{timestamp}-{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    scrapers_dir = config.project_root / "scrapers"
    scrapers_dir.mkdir(parents=True, exist_ok=True)
    scraper_path = scrapers_dir / f"{slug}.py"

    plan_path = run_dir / "plan.md"
    dom_map_path = run_dir / "dom_map.json"
    results_path = run_dir / "results.json"
    report_path = run_dir / "report.md"

    sandbox = FilesystemSandbox([scrapers_dir, run_dir])

    # Persist inputs for traceability
    (run_dir / "input_schema.json").write_text(
        json.dumps(config.schema, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (run_dir / "input_tests.json").write_text(
        json.dumps(config.tests, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    sample_url = (config.tests[0]["url"] if config.tests else config.url)

    pipeline_run = PipelineRun(
        run_dir=run_dir,
        scraper_path=scraper_path,
        plan_path=plan_path,
        dom_map_path=dom_map_path,
        results_path=results_path,
        report_path=report_path,
    )

    with BrowserSession(headless=config.headless) as browser:
        # 1. Discovery
        console.print(Panel.fit("[bold]1/5 Discovery[/bold]", style="cyan"))
        run_discovery(
            url=config.url,
            schema=config.schema,
            out_path=plan_path,
            console=console,
            model=config.model,
            browser=browser,
        )
        plan_md = plan_path.read_text(encoding="utf-8")

        # 2. DOM Mapping
        console.print(Panel.fit("[bold]2/5 DOM Mapping[/bold]", style="cyan"))
        _, dom_map = run_dom_mapping(
            url=sample_url,
            schema=config.schema,
            plan_md=plan_md,
            out_path=dom_map_path,
            console=console,
            model=config.model,
            browser=browser,
        )

    if dom_map is None:
        console.print(
            "[red]DOM Mapping did not produce valid JSON. Aborting.[/red]"
        )
        return pipeline_run

    feedback: str | None = None
    outcome: EvaluationOutcome | None = None

    for attempt in range(1, config.max_retries + 2):  # +1 initial try, +max_retries extras
        pipeline_run.attempts = attempt
        # 3. Implementation
        console.print(
            Panel.fit(
                f"[bold]3/5 Implementation[/bold] (attempt {attempt})",
                style="cyan",
            )
        )
        run_implementation(
            schema=config.schema,
            dom_map=dom_map,
            plan_md=plan_md,
            scraper_path=scraper_path,
            sandbox=sandbox,
            console=console,
            model=config.model,
            feedback=feedback,
        )

        # 4. Test Runner
        console.print(Panel.fit("[bold]4/5 Test Runner[/bold]", style="cyan"))
        _, results = run_test_runner(
            scraper_path=scraper_path,
            tests=config.tests,
            out_path=results_path,
            sandbox=sandbox,
            console=console,
            model=config.model,
        )

        # 5. Evaluation
        console.print(Panel.fit("[bold]5/5 Evaluation[/bold]", style="cyan"))
        outcome = run_evaluation(
            schema=config.schema,
            tests=config.tests,
            results=results,
            out_path=report_path,
            sandbox=sandbox,
            console=console,
            model=config.model,
        )
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
            f"[yellow]→ retrying Implementation with evaluation feedback "
            f"(attempt {attempt + 1} of {config.max_retries + 1})[/yellow]"
        )

    # Save a manifest for `inspect`
    manifest = {
        "url": config.url,
        "model": config.model,
        "slug": slug,
        "attempts": pipeline_run.attempts,
        "verdict_pass": outcome.verdict_pass if outcome else False,
        "passing": outcome.passing if outcome else 0,
        "total": outcome.total if outcome else 0,
        "artifacts": {
            "plan": str(plan_path),
            "dom_map": str(dom_map_path),
            "scraper": str(scraper_path),
            "results": str(results_path),
            "report": str(report_path),
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    pipeline_run.artifacts = {k: Path(v) for k, v in manifest["artifacts"].items()}
    return pipeline_run


def _slugify(url: str) -> str:
    host = urlparse(url).hostname or "site"
    host = host.replace("www.", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", host).strip("_").lower()
    return slug or "site"
