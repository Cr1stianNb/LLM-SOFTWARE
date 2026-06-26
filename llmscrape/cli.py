"""Command-line entry point.

Subcommands
-----------
  run     Build the extraction program and evaluate it against bounded test
          cases (run against frozen snapshots). Prints results + an evaluation
          report; exit code 0 iff every case passes.
  scrape  Normal operation: extract from a live URL (or a local HTML file) and
          print the structured result.

LLM connection is configured via environment variables (overridable by flags):
  LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_MODE, LLM_CASSETTE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMConfig
from .core.errors import EXIT_OK, EXIT_TESTS_FAILED, EXIT_USAGE, ConfigError, ScrapeError
from .core.types import OutputSchema, PipelineContext, TestCase
from .fetch import fetch_live, read_fixture
from .llm.client import LLMClient
from .pipeline import build_program, run_pipeline
from .extract import apply_program


# --- small IO helpers --------------------------------------------------------


def _load_json_file(path: str, what: str) -> Any:
    if not os.path.exists(path):
        raise ConfigError(f"{what} file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"could not read {what} '{path}': {exc}") from exc


def _make_observer(verbose: bool):
    def observer(stage: str, summary: str) -> None:
        if not verbose:
            return
        print(f"\n=== {stage} ===", file=sys.stderr)
        print(summary, file=sys.stderr)

    return observer


def _build_config(args: argparse.Namespace) -> LLMConfig:
    cfg = LLMConfig.from_env()
    if args.base_url:
        cfg.base_url = args.base_url
    if args.model:
        cfg.model = args.model
    if args.api_key:
        cfg.api_key = args.api_key
    if args.llm_mode:
        cfg.mode = args.llm_mode
    cfg.cassette = args.cassette or os.environ.get("LLM_CASSETTE") or cfg.cassette
    if cfg.mode not in ("live", "replay", "record"):
        raise ConfigError(f"invalid --llm-mode '{cfg.mode}' (live|replay|record).")
    return cfg


def _emit(obj: Any, pretty: bool) -> None:
    if pretty:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(obj, ensure_ascii=False))


# --- subcommand: run ---------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    schema = OutputSchema.from_dict(_load_json_file(args.schema, "schema"))
    raw_tests = _load_json_file(args.tests, "test cases")
    if isinstance(raw_tests, dict) and "tests" in raw_tests:
        raw_tests = raw_tests["tests"]
    if not isinstance(raw_tests, list) or not raw_tests:
        raise ConfigError("test cases file must contain a non-empty list of cases.")
    test_cases: List[TestCase] = [TestCase.from_dict(t) for t in raw_tests]

    # Fixtures resolve relative to --fixtures-dir, defaulting to the directory
    # that holds the test-cases file (robust regardless of current directory).
    fixtures_dir = args.fixtures_dir or os.path.dirname(os.path.abspath(args.tests))

    # Build the program from the first test's frozen snapshot (reproducible).
    first_path = os.path.join(fixtures_dir, test_cases[0].fixture)
    sample_html = read_fixture(first_path)

    ctx = PipelineContext(
        schema=schema,
        sample_html=sample_html,
        sample_label=test_cases[0].name,
        test_cases=test_cases,
    )

    client = LLMClient(_build_config(args))
    run_pipeline(ctx, client, fixtures_dir, _make_observer(args.verbose))

    results: List[Dict[str, Any]] = [
        {
            "test": r.name,
            "passed": r.passed,
            "error": r.error,
            "result": r.extracted,
            "fields": [
                {
                    "field": c.field,
                    "expected": c.expected,
                    "actual": c.actual,
                    "passed": c.passed,
                }
                for c in r.comparisons
            ],
        }
        for r in ctx.test_results
    ]
    output = {
        "results": results,
        "evaluation": {
            "report": ctx.evaluation_report,
            "verdict": "pass" if ctx.verdict_passed else "fail",
            "total": len(ctx.test_results),
            "passed": len(ctx.test_results) - ctx.num_failed,
            "failed": ctx.num_failed,
        },
    }
    _emit(output, args.pretty)
    return EXIT_OK if ctx.verdict_passed else EXIT_TESTS_FAILED


# --- subcommand: scrape ------------------------------------------------------


def cmd_scrape(args: argparse.Namespace) -> int:
    schema = OutputSchema.from_dict(_load_json_file(args.schema, "schema"))

    if args.html:  # extract from a local HTML file instead of the network
        html = read_fixture(args.html)
        label = args.html
    else:
        html = fetch_live(args.url, timeout=args.timeout)
        label = args.url

    ctx = PipelineContext(schema=schema, sample_html=html, sample_label=label)
    client = LLMClient(_build_config(args))
    program = build_program(ctx, client, _make_observer(args.verbose))

    result = apply_program(html, program)
    _emit({"source": label, "result": result}, args.pretty)
    return EXIT_OK


# --- argument parsing --------------------------------------------------------


def _add_llm_flags(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("LLM connection (overrides environment)")
    g.add_argument("--base-url", help=f"OpenAI-compatible endpoint (default {DEFAULT_BASE_URL}).")
    g.add_argument("--model", help=f"Qwen3 model id (default {DEFAULT_MODEL}).")
    g.add_argument("--api-key", help="API key (prefer the LLM_API_KEY env var).")
    g.add_argument(
        "--llm-mode",
        choices=["live", "replay", "record"],
        help="live: call endpoint; replay: read cassette; record: call+save.",
    )
    g.add_argument("--cassette", help="Cassette JSON path for replay/record modes.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmscrape",
        description=(
            "Spec-guided web scraping CLI built as a five-stage LLM pipeline "
            "(Discovery -> DOM Mapping -> Implementation -> Test Runner -> "
            "Evaluation). Four stages use an LLM; the Test Runner is deterministic."
        ),
        epilog=(
            "Environment variables: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, "
            "LLM_MODE, LLM_CASSETTE.\n\n"
            "Example (offline, bundled cassette):\n"
            "  llmscrape run --schema fixtures/example_schema.json "
            "--tests fixtures/example_tests.json \\\n"
            "      --llm-mode replay --cassette fixtures/example_cassette.json -v\n\n"
            "Example (live site):\n"
            "  llmscrape scrape https://example.com --schema fixtures/example_schema.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Shared flags, accepted both before and after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true",
                        help="Print each pipeline stage's intermediate result to stderr.")
    common.add_argument("--pretty", action="store_true",
                        help="Pretty-print JSON output.")
    parser.add_argument("-v", "--verbose", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pretty", action="store_true", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser(
        "run",
        parents=[common],
        help="Build the program and evaluate it against bounded test cases.",
        description="Run the full pipeline against test cases (frozen snapshots) "
                    "and emit an evaluation report. Exit 0 iff all cases pass.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument("--schema", required=True, help="Expected-output schema JSON file.")
    p_run.add_argument("--tests", required=True, help="Test cases JSON file.")
    p_run.add_argument("--fixtures-dir", help="Directory of snapshot fixtures "
                       "(default: the test-cases file's directory).")
    _add_llm_flags(p_run)
    p_run.set_defaults(func=cmd_run)

    p_scrape = sub.add_parser(
        "scrape",
        parents=[common],
        help="Extract from a live URL (or local HTML file) and print the result.",
        description="Normal operation: build the extraction program and apply it "
                    "to a live URL, printing the structured result.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_scrape.add_argument("url", nargs="?", help="Target URL (omit when using --html).")
    p_scrape.add_argument("--schema", required=True, help="Expected-output schema JSON file.")
    p_scrape.add_argument("--html", help="Extract from a local HTML file instead of the network.")
    p_scrape.add_argument("--timeout", type=float, default=30.0, help="Live fetch timeout (s).")
    _add_llm_flags(p_scrape)
    p_scrape.set_defaults(func=cmd_scrape)

    return parser


def _force_utf8() -> None:
    # JSON output and reports may contain non-ASCII; avoid console codec errors
    # on platforms whose default stdout encoding is not UTF-8 (e.g. Windows).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):  # pragma: no cover
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scrape" and not args.url and not args.html:
        parser.error("scrape requires a URL or --html.")

    try:
        return args.func(args)
    except ScrapeError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        print("aborted.", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
