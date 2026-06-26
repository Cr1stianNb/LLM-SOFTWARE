"""The deterministic extraction engine.

Given HTML and an :class:`ExtractionProgram`, it produces a plain result dict.
This is what makes the Test Runner deterministic: no LLM is involved, the same
HTML and program always yield the same output.

Each rule runs the pipeline:
    select node(s) -> raw value (text/attr/html)
    -> optional regex (group 1, else group 0)
    -> optional value_map lookup
    -> ordered transforms.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from .core.errors import DataError
from .core.types import ExtractionProgram, Rule

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise DataError(
        "the 'beautifulsoup4' package is required for extraction. "
        "Install dependencies with: pip install -r requirements.txt"
    ) from exc

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_INT_RE = re.compile(r"-?\d+")


# --- transform library (all pure & deterministic) ----------------------------


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMBER_RE.search(str(value))
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    m = _INT_RE.search(str(value))
    if not m:
        return None
    return int(m.group(0))


_TRANSFORMS = {
    "strip": lambda v: str(v).strip(),
    "lower": lambda v: str(v).lower(),
    "upper": lambda v: str(v).upper(),
    "collapse_ws": lambda v: re.sub(r"\s+", " ", str(v)).strip(),
    "strip_currency": lambda v: re.sub(r"[^\d.,\-]", "", str(v)),
    "to_number": _to_number,
    "to_int": _to_int,
}


def _apply_transform(name: str, value: Any) -> Any:
    fn = _TRANSFORMS.get(name)
    if fn is None:
        raise DataError(
            f"unknown transform '{name}'. Available: {', '.join(sorted(_TRANSFORMS))}."
        )
    if value is None:
        return None
    return fn(value)


# --- raw value extraction from one node --------------------------------------


def _raw_value(node: Any, rule: Rule) -> Optional[str]:
    if rule.extract == "text":
        return node.get_text()
    if rule.extract == "html":
        return node.decode_contents() if hasattr(node, "decode_contents") else str(node)
    # attr
    val = node.get(rule.attr)
    if val is None:
        return None
    if isinstance(val, list):  # e.g. class="a b" -> ["a", "b"]
        return " ".join(val)
    return str(val)


def _post_process(raw: Optional[str], rule: Rule) -> Any:
    if raw is None:
        return rule.default
    value: Any = raw
    if rule.regex:
        m = re.search(rule.regex, raw)
        if not m:
            return rule.default
        value = m.group(1) if m.groups() else m.group(0)
    if rule.value_map and isinstance(value, str) and value in rule.value_map:
        value = rule.value_map[value]
    for t in rule.transforms:
        value = _apply_transform(t, value)
    return value


def _apply_rule(soup: "BeautifulSoup", rule: Rule) -> Any:
    try:
        nodes = soup.select(rule.selector)
    except Exception as exc:  # invalid CSS selector
        raise DataError(
            f"rule for '{rule.field}': invalid selector '{rule.selector}': {exc}"
        ) from exc

    if rule.multiple:
        return [_post_process(_raw_value(n, rule), rule) for n in nodes]
    if not nodes:
        return rule.default
    return _post_process(_raw_value(nodes[0], rule), rule)


def apply_program(html: str, program: ExtractionProgram) -> dict:
    """Run every rule against the HTML and return a field -> value dict."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {}
    for rule in program.rules:
        result[rule.field] = _apply_rule(soup, rule)
    return result
