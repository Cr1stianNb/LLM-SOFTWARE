"""Stage 1 — Discovery (LLM).

Analyses the page and proposes, in prose, how to obtain the requested
information: which page(s) and what extraction strategy. Advisory context for
the later stages; its output is recorded for observability.
"""

from __future__ import annotations

from ..core.types import PipelineContext
from ..llm.client import LLMClient
from ._prompts import schema_lines, truncate_html

_SYSTEM = (
    "You are the Discovery stage of a web-scraping pipeline. Given a target "
    "page and the fields to extract, briefly describe an extraction strategy: "
    "where each field lives on the page and any structural notes. Be concise."
)


def run(ctx: PipelineContext, client: LLMClient) -> str:
    user = (
        f"Fields to extract:\n{schema_lines(ctx.schema)}\n\n"
        f"Page source ({ctx.sample_label or 'sample'}):\n"
        f"{truncate_html(ctx.sample_html)}\n\n"
        "Describe the extraction strategy in a few sentences."
    )
    ctx.discovery = client.chat(_SYSTEM, user, tag="discovery").strip()
    return ctx.discovery
