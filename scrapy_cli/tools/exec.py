"""Subprocess-based scraper execution tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT_CHARS = 8_000
DEFAULT_TIMEOUT = 60


def run_scraper(scraper_path: str, url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a generated scraper file as a subprocess and capture its JSON output.

    The scraper module must expose a `scrape(url: str) -> dict` function. We invoke
    it via a small driver so the agent doesn't have to worry about argv parsing.
    """
    target = Path(scraper_path).resolve()
    if not target.exists():
        return {"ok": False, "error": f"scraper not found: {target}"}

    driver = (
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('scraper', r'{target}')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        f"result = mod.scrape({url!r})\n"
        "sys.stdout.write('<<<RESULT>>>')\n"
        "sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s", "url": url}

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    parsed: object | None = None
    parse_error: str | None = None
    sentinel = "<<<RESULT>>>"
    if sentinel in stdout:
        payload = stdout.split(sentinel, 1)[1].strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            parse_error = f"could not parse result JSON: {exc}"
    elif proc.returncode == 0:
        parse_error = "scraper completed without emitting a result sentinel"

    return {
        "ok": proc.returncode == 0 and parse_error is None,
        "returncode": proc.returncode,
        "url": url,
        "result": parsed,
        "parse_error": parse_error,
        "stdout": stdout[:MAX_OUTPUT_CHARS],
        "stderr": stderr[:MAX_OUTPUT_CHARS],
    }


EXEC_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "run_scraper",
        "description": (
            "Execute a generated scraper module against a URL. The module must define "
            "scrape(url: str) -> dict. Returns the parsed dict (or stdout/stderr on error)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scraper_path": {"type": "string"},
                "url": {"type": "string"},
                "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
            },
            "required": ["scraper_path", "url"],
        },
    }
]


def dispatch_exec_tool(name: str, args: dict) -> dict:
    if name == "run_scraper":
        return run_scraper(
            args["scraper_path"],
            args["url"],
            args.get("timeout", DEFAULT_TIMEOUT),
        )
    return {"ok": False, "error": f"unknown exec tool: {name}"}
