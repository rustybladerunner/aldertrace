"""Engine scoring with a FakeBackend — no Ollama."""

from __future__ import annotations

import threading
import unittest

from logitpick.engine import pick, score_question
from logitpick.ollama import NextToken, TokenAlt
from logitpick.prompt import TEMPLATE, render
from logitpick.schema import parse_request


class FakeBackend:
    def __init__(self, generated: str, alts: list[tuple[str, float]]) -> None:
        self.generated = generated
        self.alts = alts
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def next_token(self, prompt: str, *, model: str) -> NextToken:
        with self._lock:
            self.prompts.append(prompt)
        return NextToken(
            generated=self.generated,
            alts=tuple(TokenAlt(token=t, logprob=lp) for t, lp in self.alts),
            eval_count=1,
            eval_duration_ns=12_000_000,
        )


class PromptTests(unittest.TestCase):
    def test_template_is_frozen(self) -> None:
        self.assertIn("Reply with exactly one letter", TEMPLATE)
        text = render("s", "q", {"yes": "it is four", "no": "it is not"}, {"yes": "A", "no": "B"})
        self.assertIn("A. it is four", text)
        self.assertIn("B. it is not", text)
        self.assertTrue(text.endswith("Answer:"))


class EngineTests(unittest.TestCase):
    def test_probe_numbers_pick_yes(self) -> None:
        backend = FakeBackend(
            "A",
            [("A", -0.05221666395664215), ("B", -3.340428590774536)],
        )
        out = score_question(
            "arithmetic",
            "Is 2+2 equal to 4?",
            {"yes": "yes", "no": "no"},
            backend,
            "llama3.2",
        )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["choice"], "yes")
        self.assertGreater(out["probabilities"]["yes"], 0.95)
        self.assertEqual(out["missing_options"], [])
        self.assertGreater(out["mass_on_codes"], 0.9)
        self.assertLess(out["mass_on_codes"], 1.0)
        self.assertEqual(out["eval_ms"], 12.0)

    def test_missing_letter_is_incomplete(self) -> None:
        backend = FakeBackend("A", [("A", -0.1), ("Z", -1.0)])
        out = score_question("s", "q", {"yes": "y", "no": "n"}, backend, "m")
        self.assertEqual(out["status"], "incomplete_topk")
        self.assertEqual(out["missing_options"], ["no"])
        self.assertAlmostEqual(out["probabilities"]["yes"], 1.0)
        self.assertEqual(out["probabilities"]["no"], 0.0)

    def test_no_codes_at_all(self) -> None:
        backend = FakeBackend("Y", [("Y", -0.1), ("N", -0.2)])
        out = score_question("s", "q", {"yes": "y", "no": "n"}, backend, "m")
        self.assertEqual(out["status"], "no_codes_in_topk")
        self.assertIsNone(out["choice"])

    def test_pick_wraps_question_id(self) -> None:
        backend = FakeBackend("A", [("A", 0.0), ("B", -2.0)])
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
        result = pick(req, backend)
        self.assertEqual(result["backend"], "ollama-generate-logprobs")
        self.assertEqual(result["mode"], "one_question")
        self.assertEqual(result["forward_passes"], 1)
        self.assertIsInstance(result["elapsed_ms"], float)
        self.assertEqual(result["answers"]["route"]["choice"], "fast")
        self.assertIn("Reply with exactly one letter", backend.prompts[0])

    def test_multi_question_is_n_passes_in_request_order(self) -> None:
        class SplitFake:
            def __init__(self) -> None:
                self.prompts: list[str] = []
                self._lock = threading.Lock()

            def next_token(self, prompt: str, *, model: str) -> NextToken:
                with self._lock:
                    self.prompts.append(prompt)
                if "Which mode?" in prompt:
                    return NextToken(
                        generated="A",
                        alts=(TokenAlt("A", 0.0), TokenAlt("B", -4.0)),
                        eval_count=1,
                        eval_duration_ns=1_000_000,
                    )
                return NextToken(
                    generated="B",
                    alts=(TokenAlt("A", -3.0), TokenAlt("B", 0.0)),
                    eval_count=1,
                    eval_duration_ns=1_000_000,
                )

        backend = SplitFake()
        req = parse_request(
            {
                "state": "PR adds a button rename and a debug print",
                "questions": {
                    "route": {
                        "instructions": "Which mode?",
                        "options": {"fast": "UI tweak", "full": "multi-file"},
                    },
                    "noise": {
                        "instructions": "Is this mostly noise?",
                        "options": {"yes": "noise", "no": "real work"},
                    },
                },
            }
        )
        result = pick(req, backend)
        self.assertEqual(result["mode"], "concurrent_questions")
        self.assertEqual(result["forward_passes"], 2)
        self.assertEqual(list(result["answers"]), ["route", "noise"])
        self.assertEqual(result["answers"]["route"]["choice"], "fast")
        self.assertEqual(result["answers"]["noise"]["choice"], "no")
        self.assertEqual(len(backend.prompts), 2)

    def test_concurrent_error_does_not_return_partial(self) -> None:
        class Boom:
            def next_token(self, prompt: str, *, model: str) -> NextToken:
                raise RuntimeError("upstream down")

        req = parse_request(
            {
                "state": "rename a button",
                "questions": {
                    "route": {
                        "instructions": "Which mode?",
                        "options": {"fast": "UI", "full": "multi-file"},
                    },
                    "noise": {
                        "instructions": "Is this mostly noise?",
                        "options": {"yes": "noise", "no": "real work"},
                    },
                },
            }
        )
        with self.assertRaises(RuntimeError):
            pick(req, Boom())


if __name__ == "__main__":
    unittest.main()
