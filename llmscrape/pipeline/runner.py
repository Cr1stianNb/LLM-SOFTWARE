"""Pipeline orchestrator.

Wires the five stages together while keeping every intermediate result on the
shared :class:`PipelineContext` so the run stays observable. The ``observer``
callback (used by ``-v``) is invoked after each stage with a human-readable
summary of what that stage produced.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from ..core.types import ExtractionProgram, PipelineContext
from ..llm.client import LLMClient
from . import discovery, dom_mapping, evaluation, implementation, test_runner

# observer(stage_name, summary_text) -> None
Observer = Callable[[str, str], None]


def _noop(stage: str, summary: str) -> None:  # pragma: no cover
    return None


def build_program(
    ctx: PipelineContext, client: LLMClient, observer: Optional[Observer] = None
) -> ExtractionProgram:
    """Run the three LLM stages that produce the extraction program."""
    obs = observer or _noop

    discovery.run(ctx, client)
    obs("1. Discovery", ctx.discovery)

    dom_mapping.run(ctx, client)
    obs("2. DOM Mapping", json.dumps(ctx.dom_map, ensure_ascii=False, indent=2))

    program = implementation.run(ctx, client)
    obs("3. Implementation", json.dumps(program.to_dict(), ensure_ascii=False, indent=2))
    return program


def run_pipeline(
    ctx: PipelineContext,
    client: LLMClient,
    fixtures_dir: str,
    observer: Optional[Observer] = None,
) -> PipelineContext:
    """Run all five stages: build the program, test it, evaluate the results."""
    obs = observer or _noop

    build_program(ctx, client, observer)

    test_runner.run(ctx, fixtures_dir)
    obs(
        "4. Test Runner (deterministic)",
        "\n".join(
            f"- {r.name}: {'PASS' if r.passed else 'FAIL'}"
            + (f" ({r.error})" if r.error else "")
            for r in ctx.test_results
        ),
    )

    evaluation.run(ctx, client)
    obs("5. Evaluation", ctx.evaluation_report)
    return ctx
