"""Schema and letter-code guards."""

from __future__ import annotations

import unittest

from logitpick.codes import assign_codes
from logitpick.schema import PickError, parse_request


class CodesTests(unittest.TestCase):
    def test_two_options_ab(self) -> None:
        self.assertEqual(assign_codes(["yes", "no"]), {"yes": "A", "no": "B"})

    def test_rejects_one_option(self) -> None:
        with self.assertRaises(ValueError):
            assign_codes(["only"])

    def test_rejects_seventeen(self) -> None:
        with self.assertRaises(ValueError):
            assign_codes([f"o{i}" for i in range(17)])

    def test_rejects_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            assign_codes(["a", "a"])


class ParseTests(unittest.TestCase):
    def test_ok(self) -> None:
        req = parse_request(
            {
                "state": "rename a button",
                "questions": {
                    "route": {
                        "instructions": "Which mode?",
                        "options": {"fast": "UI tweak", "full": "multi-file"},
                    }
                },
            }
        )
        self.assertEqual(req.model, "llama3.2")
        self.assertEqual(req.questions[0].id, "route")

    def test_empty_state(self) -> None:
        with self.assertRaises(PickError) as ctx:
            parse_request({"state": "  ", "questions": {"q": {"instructions": "x", "options": {"a": "a", "b": "b"}}}})
        self.assertEqual(ctx.exception.code, "invalid_state")

    def test_rejects_path_model(self) -> None:
        with self.assertRaises(PickError) as ctx:
            parse_request(
                {
                    "state": "x",
                    "model": "../evil",
                    "questions": {"q": {"instructions": "x", "options": {"a": "a", "b": "b"}}},
                }
            )
        self.assertEqual(ctx.exception.code, "invalid_model")

    def test_too_many_questions(self) -> None:
        qs = {
            f"q{i}": {"instructions": "x", "options": {"a": "a", "b": "b"}}
            for i in range(9)
        }
        with self.assertRaises(PickError) as ctx:
            parse_request({"state": "x", "questions": qs})
        self.assertEqual(ctx.exception.code, "too_many_questions")


if __name__ == "__main__":
    unittest.main()
