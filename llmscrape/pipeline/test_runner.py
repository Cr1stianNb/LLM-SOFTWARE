"""Stage 4 — Test Runner (DETERMINISTIC, no LLM).

For each test case it reads the frozen snapshot, applies the extraction program,
and compares the result to the expected output field by field. The pass/fail
verdict is computed here by exact (type-aware) comparison so it is fully
reproducible and never depends on LLM variability.
"""

from __future__ import annotations

import os
from typing import Any

from ..core.errors import FetchError
from ..core.types import (
    FieldComparison,
    OutputSchema,
    PipelineContext,
    TestCase,
    TestCaseResult,
)
from ..extract import apply_program
from ..fetch import read_fixture

_NUMBER_EPS = 1e-9


def _coerce(value: Any, field_type: str) -> Any:
    """Coerce a value to its schema type for comparison. None stays None."""
    if value is None:
        return None
    try:
        if field_type == "number":
            return float(value)
        if field_type == "integer":
            return int(value)
        if field_type == "boolean":
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "y"}
            return bool(value)
        return str(value)
    except (ValueError, TypeError):
        return value  # leave as-is; comparison will fail cleanly


def _values_equal(expected: Any, actual: Any, field_type: str) -> bool:
    exp = _coerce(expected, field_type)
    act = _coerce(actual, field_type)
    if exp is None or act is None:
        return exp == act
    if field_type == "number":
        return abs(float(exp) - float(act)) <= _NUMBER_EPS
    return exp == act


def compare(expected: dict, actual: dict, schema: OutputSchema) -> list:
    """Field-by-field comparison driven by the schema. Returns comparisons."""
    comparisons = []
    for f in schema.fields:
        exp = expected.get(f.name)
        act = actual.get(f.name)
        comparisons.append(
            FieldComparison(
                field=f.name,
                expected=exp,
                actual=act,
                passed=_values_equal(exp, act, f.type),
            )
        )
    return comparisons


def _resolve_fixture(test: TestCase, fixtures_dir: str) -> str:
    # Absolute paths win; otherwise resolve under the fixtures directory.
    if os.path.isabs(test.fixture):
        return test.fixture
    return os.path.join(fixtures_dir, test.fixture)


def run(ctx: PipelineContext, fixtures_dir: str) -> list:
    """Execute every test case against its snapshot. No network, no LLM."""
    if ctx.program is None:
        raise FetchError("internal error: extraction program not built yet.")

    results = []
    for test in ctx.test_cases:
        path = _resolve_fixture(test, fixtures_dir)
        try:
            html = read_fixture(path)
            extracted = apply_program(html, ctx.program)
            comparisons = compare(test.expected, extracted, ctx.schema)
            passed = all(c.passed for c in comparisons)
            results.append(
                TestCaseResult(
                    name=test.name,
                    passed=passed,
                    extracted=extracted,
                    comparisons=comparisons,
                )
            )
        except FetchError as exc:
            # A missing/unreadable fixture is a controlled, per-case failure.
            results.append(
                TestCaseResult(
                    name=test.name,
                    passed=False,
                    extracted={},
                    comparisons=[],
                    error=str(exc),
                )
            )
    ctx.test_results = results
    return results
