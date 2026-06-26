"""Stage 2 — DOM Mapping (LLM).

Identifies the relevant DOM nodes / CSS selectors for each schema field, given
the Discovery strategy and the page HTML. Emits a JSON map field -> selector.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.types import PipelineContext
from ..llm.client import LLMClient, parse_json_loose
from ._prompts import schema_lines, truncate_html

_SYSTEM = (
    "You are the DOM Mapping stage. For each field, identify the CSS selector "
    "and DOM location that contains its value. Return ONLY a JSON object that "
    "maps each field name to an object {\"selector\": ..., \"notes\": ...}."
)


def run(ctx: PipelineContext, client: LLMClient) -> Dict[str, Any]:
    user = (
        f"Fields:\n{schema_lines(ctx.schema)}\n\n"
        f"Discovery strategy:\n{ctx.discovery or '(none)'}\n\n"
        f"Page source:\n{truncate_html(ctx.sample_html)}\n\n"
        "Return the field -> selector JSON map."
    )
    raw = client.chat(_SYSTEM, user, tag="dom_mapping")
    ctx.dom_map = parse_json_loose(raw, context="DOM Mapping output")
    return ctx.dom_map
