"""Stage 3 — Implementation (LLM).

Turns the DOM mapping into a concrete, deterministically-executable extraction
program (a declarative set of field rules). This is the extraction logic the
Test Runner and live scraping both apply.
"""

from __future__ import annotations

import json

from ..core.types import ExtractionProgram, PipelineContext
from ..llm.client import LLMClient, parse_json_loose
from ._prompts import RULE_FORMAT, schema_lines, truncate_html

_SYSTEM = (
    "You are the Implementation stage. Produce a declarative extraction program "
    "that the deterministic runner can execute. Output JSON only."
)


def run(ctx: PipelineContext, client: LLMClient) -> ExtractionProgram:
    user = (
        f"Fields:\n{schema_lines(ctx.schema)}\n\n"
        f"DOM mapping:\n{json.dumps(ctx.dom_map, ensure_ascii=False, indent=2)}\n\n"
        f"Page source (for verifying selectors):\n{truncate_html(ctx.sample_html)}\n\n"
        f"{RULE_FORMAT}"
    )
    raw = client.chat(_SYSTEM, user, tag="implementation")
    data = parse_json_loose(raw, context="Implementation output")
    ctx.program = ExtractionProgram.from_dict(data)
    return ctx.program
