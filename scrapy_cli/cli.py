"""Click-based CLI entry point."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

from .pipeline import PipelineConfig, execute

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
    "haiku": "claude-haiku-4-5-20251001",
}


@click.group()
def main() -> None:
    """Multi-agent web scraping pipeline."""
    load_dotenv()


@main.command()
@click.option(
    "--url",
    required=True,
    help="Start URL of the target site (used by Discovery).",
)
@click.option(
    "--schema",
    "schema_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to JSON Schema describing the expected output.",
)
@click.option(
    "--tests",
    "tests_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to JSON file with test cases ([{name, url, expected}]).",
)
@click.option(
    "--model",
    default="sonnet",
    help="Model: sonnet|opus|haiku or a full model id.",
)
@click.option(
    "--max-retries",
    default=2,
    show_default=True,
    type=int,
    help="How many times to re-run Implementation if Evaluation fails.",
)
@click.option(
    "--slug",
    default=None,
    help="Override the scraper filename slug.",
)
@click.option(
    "--show-browser",
    is_flag=True,
    help="Run Playwright with a visible browser (headless=False).",
)
def run(
    url: str,
    schema_path: Path,
    tests_path: Path,
    model: str,
    max_retries: int,
    slug: str | None,
    show_browser: bool,
) -> None:
    """Run the full discovery → mapping → impl → test → eval pipeline."""
    console = Console()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[red]ANTHROPIC_API_KEY is not set. "
            "Create a .env (see .env.example) or export it.[/red]"
        )
        sys.exit(1)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    tests = json.loads(tests_path.read_text(encoding="utf-8"))
    if not isinstance(tests, list) or not tests:
        console.print("[red]Tests file must be a non-empty JSON array.[/red]")
        sys.exit(1)

    model_id = MODEL_ALIASES.get(model, model)

    config = PipelineConfig(
        url=url,
        schema=schema,
        tests=tests,
        project_root=PROJECT_ROOT,
        model=model_id,
        max_retries=max_retries,
        headless=not show_browser,
        slug=slug,
    )

    console.print(
        Panel.fit(
            f"[bold]URL[/bold] {url}\n"
            f"[bold]Schema[/bold] {schema_path}\n"
            f"[bold]Tests[/bold] {tests_path} ({len(tests)} cases)\n"
            f"[bold]Model[/bold] {model_id}\n"
            f"[bold]Max retries[/bold] {max_retries}",
            title="scrapy-pipeline",
        )
    )

    pipeline_run = execute(config, console=console)

    outcome = pipeline_run.outcome
    if outcome is None:
        console.print("[red]Pipeline aborted before evaluation.[/red]")
        sys.exit(2)

    console.print(
        Panel.fit(
            f"Run dir: [cyan]{pipeline_run.run_dir}[/cyan]\n"
            f"Scraper: [cyan]{pipeline_run.scraper_path}[/cyan]\n"
            f"Verdict: "
            f"[{'green' if outcome.verdict_pass else 'red'}]"
            f"{'PASS' if outcome.verdict_pass else 'FAIL'}[/]"
            f" ({outcome.passing}/{outcome.total})\n"
            f"Attempts: {pipeline_run.attempts}",
            title="result",
        )
    )

    sys.exit(0 if outcome.verdict_pass else 3)


@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--artifact",
    type=click.Choice(["plan", "dom_map", "scraper", "results", "report", "manifest"]),
    default="report",
    show_default=True,
)
def inspect(run_dir: Path, artifact: str) -> None:
    """Pretty-print an artifact from a previous run."""
    console = Console()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]No manifest.json in {run_dir}[/red]")
        sys.exit(1)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if artifact == "manifest":
        console.print(Syntax(json.dumps(manifest, indent=2), "json"))
        return
    artifact_path = Path(manifest["artifacts"][artifact])
    if not artifact_path.exists():
        console.print(f"[red]Missing artifact: {artifact_path}[/red]")
        sys.exit(1)
    content = artifact_path.read_text(encoding="utf-8")
    if artifact in {"plan", "report"}:
        console.print(Markdown(content))
    elif artifact == "scraper":
        console.print(Syntax(content, "python", line_numbers=True))
    else:
        console.print(Syntax(content, "json"))


if __name__ == "__main__":
    main()
