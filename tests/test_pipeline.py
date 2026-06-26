"""Deterministic-core tests.

These exercise the pieces that must be reproducible without an LLM: the
extraction engine, the schema/program types, and the Test Runner's comparison.
Each pipeline stage is importable and testable on its own; here we cover the
deterministic ones. Run with:  python -m unittest discover -s tests
"""

import os
import unittest

from llmscrape.core.types import ExtractionProgram, OutputSchema
from llmscrape.extract import apply_program
from llmscrape.pipeline.test_runner import compare

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")

PROGRAM = {
    "rules": [
        {"field": "title", "selector": ".product_main h1", "transforms": ["strip"]},
        {"field": "price", "selector": ".product_main p.price_color",
         "transforms": ["strip_currency", "to_number"]},
        {"field": "availability", "selector": ".product_main p.availability",
         "transforms": ["collapse_ws"]},
        {"field": "rating", "selector": ".product_main p.star-rating", "extract": "attr",
         "attr": "class", "regex": r"star-rating (\w+)",
         "value_map": {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5},
         "transforms": ["to_int"]},
        {"field": "upc", "selector": "table.table tr:nth-of-type(1) td",
         "transforms": ["strip"]},
    ]
}

SCHEMA = OutputSchema.from_dict({
    "title": "string", "price": "number", "availability": "string",
    "rating": "integer", "upc": "string",
})


def _html():
    with open(os.path.join(FIXTURES, "books_toscrape_product.html"), encoding="utf-8") as fh:
        return fh.read()


class ExtractionEngineTest(unittest.TestCase):
    def test_extracts_typed_values(self):
        program = ExtractionProgram.from_dict(PROGRAM)
        result = apply_program(_html(), program)
        self.assertEqual(result["title"], "A Light in the Attic")
        self.assertEqual(result["price"], 51.77)
        self.assertEqual(result["availability"], "In stock (22 available)")
        self.assertEqual(result["rating"], 3)
        self.assertEqual(result["upc"], "a897fe39b1053632")

    def test_missing_selector_yields_default(self):
        program = ExtractionProgram.from_dict(
            {"rules": [{"field": "x", "selector": ".does-not-exist", "default": None}]}
        )
        self.assertIsNone(apply_program(_html(), program)["x"])


class ComparisonTest(unittest.TestCase):
    def test_verdict_is_type_aware_and_exact(self):
        expected = {"title": "A Light in the Attic", "price": 51.77,
                    "availability": "In stock (22 available)", "rating": 3,
                    "upc": "a897fe39b1053632"}
        actual = apply_program(_html(), ExtractionProgram.from_dict(PROGRAM))
        comparisons = compare(expected, actual, SCHEMA)
        self.assertTrue(all(c.passed for c in comparisons))

    def test_detects_mismatch(self):
        comparisons = compare({"price": 99.0}, {"price": 51.77},
                              OutputSchema.from_dict({"price": "number"}))
        self.assertFalse(comparisons[0].passed)


if __name__ == "__main__":
    unittest.main()
