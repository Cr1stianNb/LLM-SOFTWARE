"""Prompt text and small helpers shared by the LLM stages."""

from __future__ import annotations

from ..core.types import OutputSchema

MAX_HTML_CHARS = 14000


def truncate_html(html: str, limit: int = MAX_HTML_CHARS) -> str:
    if len(html) <= limit:
        return html
    return html[:limit] + f"\n<!-- ...truncated, {len(html) - limit} chars omitted -->"


def schema_lines(schema: OutputSchema) -> str:
    return "\n".join(
        f"- {f.name} ({f.type})" + (f": {f.description}" if f.description else "")
        for f in schema.fields
    )


# Documented contract for the declarative extraction program the Implementation
# stage must emit. Kept declarative (not executable code) so the Test Runner can
# apply it deterministically and safely.
RULE_FORMAT = """\
Return ONLY a JSON object of this exact shape (no prose, no code fence):

{
  "rules": [
    {
      "field": "<field name from the schema>",
      "selector": "<CSS selector, e.g. '.product_main h1'>",
      "extract": "text" | "attr" | "html",   // default "text"
      "attr": "<attribute name, required only when extract=attr>",
      "regex": "<optional regex; group 1 is kept, else the whole match>",
      "value_map": { "RawText": mappedValue },  // optional exact-string remap
      "transforms": ["strip", "collapse_ws", "lower", "upper",
                     "strip_currency", "to_number", "to_int"],  // applied in order
      "multiple": false,        // true -> return a list of values
      "default": null           // value when the selector matches nothing
    }
  ]
}

Provide exactly one rule per schema field. Choose transforms so the value type
matches the schema (use to_number for number fields, to_int for integer fields).
"""
