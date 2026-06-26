"""First-class shared types.

The output schema, the extraction program, test cases and stage results are all
defined here as typed structures (not loose dicts) so each pipeline stage has a
clear input/output contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import DataError, SchemaError

# --- Field types accepted in the output schema -------------------------------

VALID_FIELD_TYPES = {"string", "number", "integer", "boolean"}


@dataclass
class FieldSpec:
    """One field of the expected output and its type."""

    name: str
    type: str = "string"
    description: str = ""

    def __post_init__(self) -> None:
        if self.type not in VALID_FIELD_TYPES:
            raise SchemaError(
                f"field '{self.name}': unknown type '{self.type}'. "
                f"Valid types: {', '.join(sorted(VALID_FIELD_TYPES))}."
            )


@dataclass
class OutputSchema:
    """The expected shape of an extraction result: a set of typed fields."""

    fields: List[FieldSpec]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutputSchema":
        # Accept either {"fields": {"title": {"type": "string"}, ...}}
        # or the shorthand {"title": "string", ...}.
        raw = data.get("fields", data)
        if not isinstance(raw, dict) or not raw:
            raise SchemaError("output schema must define at least one field.")
        fields: List[FieldSpec] = []
        for name, spec in raw.items():
            if isinstance(spec, str):
                fields.append(FieldSpec(name=name, type=spec))
            elif isinstance(spec, dict):
                fields.append(
                    FieldSpec(
                        name=name,
                        type=spec.get("type", "string"),
                        description=spec.get("description", ""),
                    )
                )
            else:
                raise SchemaError(f"field '{name}': invalid specification.")
        return cls(fields=fields)

    @property
    def names(self) -> List[str]:
        return [f.name for f in self.fields]

    def type_of(self, name: str) -> str:
        for f in self.fields:
            if f.name == name:
                return f.type
        return "string"


# --- The extraction program produced by the Implementation stage -------------


@dataclass
class Rule:
    """A single deterministic extraction rule for one field.

    Pipeline of operations applied to the selected node(s):
    select -> raw value (text/attr/html) -> optional regex group 1 ->
    optional value_map lookup -> ordered transforms.
    """

    field: str
    selector: str
    extract: str = "text"  # "text" | "attr" | "html"
    attr: Optional[str] = None
    regex: Optional[str] = None
    value_map: Dict[str, Any] = field(default_factory=dict)
    transforms: List[str] = field(default_factory=list)
    multiple: bool = False
    default: Any = None

    def __post_init__(self) -> None:
        if self.extract not in {"text", "attr", "html"}:
            raise DataError(
                f"rule for '{self.field}': extract must be text|attr|html, "
                f"got '{self.extract}'."
            )
        if self.extract == "attr" and not self.attr:
            raise DataError(
                f"rule for '{self.field}': extract=attr requires an 'attr' name."
            )


@dataclass
class ExtractionProgram:
    """A declarative, deterministically executable set of field rules.

    The Implementation stage (LLM) emits this; the Test Runner (deterministic)
    and live scraping both execute it without further model involvement.
    """

    rules: List[Rule]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionProgram":
        raw_rules = data.get("rules", data) if isinstance(data, dict) else data
        if not isinstance(raw_rules, list) or not raw_rules:
            raise DataError("extraction program must contain a non-empty 'rules' list.")
        rules: List[Rule] = []
        for r in raw_rules:
            if not isinstance(r, dict) or "field" not in r or "selector" not in r:
                raise DataError(
                    "each rule needs at least 'field' and 'selector'. Offending "
                    f"entry: {r!r}"
                )
            rules.append(
                Rule(
                    field=r["field"],
                    selector=r["selector"],
                    extract=r.get("extract", "text"),
                    attr=r.get("attr"),
                    regex=r.get("regex"),
                    value_map=r.get("value_map", {}) or {},
                    transforms=r.get("transforms", []) or [],
                    multiple=bool(r.get("multiple", False)),
                    default=r.get("default"),
                )
            )
        return cls(rules=rules)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rules": [
                {
                    "field": r.field,
                    "selector": r.selector,
                    "extract": r.extract,
                    "attr": r.attr,
                    "regex": r.regex,
                    "value_map": r.value_map,
                    "transforms": r.transforms,
                    "multiple": r.multiple,
                    "default": r.default,
                }
                for r in self.rules
            ]
        }


# --- Test cases and results --------------------------------------------------


@dataclass
class TestCase:
    """A bounded (input -> expected output) pair.

    ``fixture`` points at a frozen HTML snapshot in the fixtures directory; the
    Test Runner reads it from disk, never from the network. ``url`` is recorded
    for documentation/traceability only.
    """

    name: str
    fixture: str
    expected: Dict[str, Any]
    url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCase":
        if "fixture" not in data or "expected" not in data:
            raise DataError(
                "each test case requires 'fixture' and 'expected'. "
                f"Offending entry: {data!r}"
            )
        return cls(
            name=data.get("name", data["fixture"]),
            fixture=data["fixture"],
            expected=data["expected"],
            url=data.get("url"),
        )


@dataclass
class FieldComparison:
    field: str
    expected: Any
    actual: Any
    passed: bool


@dataclass
class TestCaseResult:
    name: str
    passed: bool
    extracted: Dict[str, Any]
    comparisons: List[FieldComparison]
    error: Optional[str] = None


# --- The context that flows through the pipeline -----------------------------


@dataclass
class PipelineContext:
    """Carried through all five stages; each stage enriches it in place.

    Keeping every intermediate result on one object makes the pipeline
    observable: ``-v`` can dump any stage's contribution.
    """

    schema: OutputSchema
    sample_html: str = ""
    sample_label: str = ""
    test_cases: List[TestCase] = field(default_factory=list)

    # Filled progressively by the stages.
    discovery: str = ""
    dom_map: Dict[str, Any] = field(default_factory=dict)
    program: Optional[ExtractionProgram] = None
    test_results: List[TestCaseResult] = field(default_factory=list)
    evaluation_report: str = ""

    @property
    def verdict_passed(self) -> bool:
        return bool(self.test_results) and all(r.passed for r in self.test_results)

    @property
    def num_failed(self) -> int:
        return sum(1 for r in self.test_results if not r.passed)
