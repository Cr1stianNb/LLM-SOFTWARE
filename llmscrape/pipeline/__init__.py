"""The five-stage pipeline.

Discovery -> DOM Mapping -> Implementation -> Test Runner -> Evaluation.
Each stage lives in its own module with a clear input/output contract and is
testable in isolation. Only ``test_runner`` is deterministic (no LLM).
"""

from .runner import build_program, run_pipeline

__all__ = ["build_program", "run_pipeline"]
