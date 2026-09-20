"""Live Ollama smoke. Skipped unless LOGITPICK_LIVE=1. Unloads the model after."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from logitpick.engine import pick
from logitpick.ollama import OllamaBackend, OllamaError
from logitpick.schema import parse_request

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "testdata" / "live-baseline.json"
LAST = ROOT / "live-last.json"

TOY = {
    "state": "Elementary arithmetic. 2 + 2 = 4.",
    "model": "llama3.2",
    "questions": {
        "arith": {
            "instructions": "Is 2+2 equal to 4?",
            "options": {"yes": "yes, it equals four", "no": "no, it does not"},
        }
    },
}

INVOICE = {
    "state": (
        "Invoice 4412 from Acme Supplies for $48.00. Matches PO 9912. "
        "Line items: paper, toner. No duplicate in 90 days. Vendor used for 6 months."
    ),
    "model": "llama3.2",
    "questions": {
        "fraud": {
            "instructions": "How should software treat this invoice?",
            "options": {
                "fraud": "treat as fraudulent",
                "clean": "treat as legitimate",
                "review": "send to a human",
            },
        }
    },
}


@unittest.skipUnless(os.environ.get("LOGITPICK_LIVE") == "1", "set LOGITPICK_LIVE=1 to hit Ollama")
class LiveOllamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = OllamaBackend(keep_alive="0")

    def test_toy_yes_beats_no(self) -> None:
        req = parse_request(TOY)
        try:
            result = pick(req, self.backend)
        except OllamaError as e:
            self.fail(f"Ollama live call failed: {e}")
        LAST.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        ans = result["answers"]["arith"]
        self.assertEqual(ans["choice"], "yes")
        self.assertEqual(ans["status"], "ok")
        self.assertGreater(ans["probabilities"]["yes"], ans["probabilities"]["no"])
        self.assertGreater(ans["mass_on_codes"], 0.9)
        if BASELINE.exists():
            recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
            self.assertEqual(recorded["answers"]["arith"]["choice"], ans["choice"])

    def test_three_way_invoice_scores_declared_options(self) -> None:
        """Same envelope as the Jev cartoon. Do not assert their 0.88/0.1s."""
        req = parse_request(INVOICE)
        try:
            result = pick(req, self.backend)
        except OllamaError as e:
            self.fail(f"Ollama live call failed: {e}")
        proof = ROOT / "testdata" / "live-proof-invoice.json"
        proof.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        ans = result["answers"]["fraud"]
        self.assertIn(ans["choice"], ("fraud", "clean", "review"))
        self.assertEqual(set(ans["probabilities"]), {"fraud", "clean", "review"})
        self.assertGreater(sum(ans["probabilities"].values()), 0.99)
        self.assertGreater(ans["mass_on_codes"], 0.5)
        self.assertIn(ans["status"], ("ok", "incomplete_topk"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.backend.unload("llama3.2")
