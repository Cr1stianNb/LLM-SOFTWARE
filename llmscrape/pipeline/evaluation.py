"""Stage 5 — Evaluation (LLM).

Produces the human-readable evaluation report comparing actual vs expected.
Important: the pass/fail verdict itself is *not* produced here — it was computed
deterministically by the Test Runner. This stage only narrates the already-fixed
facts, so the verdict never depends on LLM variability.
"""

from __future__ import annotations

import json

from ..core.types import PipelineContext
from ..llm.client import LLMClient

_SYSTEM = (
    "You are the Evaluation stage. You are given, for each test case, the "
    "deterministic field-by-field comparison of expected vs actual values and "
    "whether it passed. Write a short, clear, human-readable report. Do NOT "
    "change any verdict; only summarize the provided facts."
)


def _facts(ctx: PipelineContext) -> str:
    payload = []
    for r in ctx.test_results:
        payload.append(
            {
                "test": r.name,
                "passed": r.passed,
                "error": r.error,
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
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run(ctx: PipelineContext, client: LLMClient) -> str:
    user = (
        "Comparison facts (authoritative, do not alter verdicts):\n"
        f"{_facts(ctx)}\n\n"
        "Write the evaluation report."
    )
    ctx.evaluation_report = client.chat(_SYSTEM, user, tag="evaluation").strip()
    return ctx.evaluation_report
