"""Scan-first gate: scanners decide secrets/SQL; model is optional."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from logitpick.gate import gate
from logitpick.ollama import NextToken, TokenAlt
from logitpick.policy import apply_policy

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "testdata" / "fixtures"


class _YesBackend:
    def next_token(self, prompt: str, *, model: str) -> NextToken:
        return NextToken(
            generated="A",
            alts=(TokenAlt("A", -0.05), TokenAlt("B", -4.0)),
            eval_count=1,
            eval_duration_ns=1_000_000,
        )


class _UncertainBackend:
    def next_token(self, prompt: str, *, model: str) -> NextToken:
        # ~0.5 / 0.5 after softmax
        return NextToken(
            generated="A",
            alts=(TokenAlt("A", 0.0), TokenAlt("B", 0.0)),
            eval_count=1,
            eval_duration_ns=1_000_000,
        )


class GateScanTests(unittest.TestCase):
    def test_password_reset_blocks_without_a_model(self) -> None:
        text = (FIX / "password-reset.diff").read_text(encoding="utf-8")
        out = gate(text, title="Add password reset endpoint")
        self.assertFalse(out["model_used"])
        self.assertEqual(out["verdict"], "block")
        self.assertIn("hardcoded_secret", out["reasons"])
        self.assertIn("injection_risk", out["reasons"])
        ids = {c["id"]: c for c in out["checks"]}
        self.assertTrue(ids["hardcoded_secret"]["hit"])
        self.assertTrue(ids["injection_risk"]["hit"])
        self.assertTrue(ids["touches_auth"]["hit"])
        self.assertEqual(ids["hardcoded_secret"]["lane"], "scan")

    def test_model_that_says_yes_cannot_override_a_secret(self) -> None:
        text = (FIX / "password-reset.diff").read_text(encoding="utf-8")
        out = gate(text, title="harmless docs", backend=_YesBackend())
        self.assertTrue(out["model_used"])
        self.assertEqual(out["verdict"], "block")
        self.assertIn("hardcoded_secret", out["reasons"])

    def test_pagination_is_nits_from_print(self) -> None:
        text = (FIX / "pagination.diff").read_text(encoding="utf-8")
        out = gate(text, title="Add pagination to GET /orders")
        self.assertEqual(out["verdict"], "nits")
        self.assertIn("debug_leftovers", out["reasons"])
        ids = {c["id"]: c for c in out["checks"]}
        self.assertFalse(ids["hardcoded_secret"]["hit"])
        self.assertFalse(ids["injection_risk"]["hit"])
        self.assertTrue(ids["adds_tests"]["hit"])

    def test_docs_typo_merges(self) -> None:
        text = (FIX / "docs-typo.diff").read_text(encoding="utf-8")
        out = gate(text, title="Fix typos in README")
        self.assertEqual(out["verdict"], "merge")
        ids = {c["id"]: c for c in out["checks"]}
        self.assertTrue(ids["docs_only"]["hit"])

    def test_uncertain_model_escalates_when_scans_are_clean(self) -> None:
        text = (FIX / "docs-typo.diff").read_text(encoding="utf-8")
        out = gate(text, title="Fix typos", backend=_UncertainBackend())
        self.assertEqual(out["verdict"], "escalate")
        self.assertIn("description_matches", out["reasons"])


class PolicyUnitTests(unittest.TestCase):
    def test_block_beats_security(self) -> None:
        checks = [
            {"id": "hardcoded_secret", "hit": True, "lane": "scan"},
            {"id": "touches_auth", "hit": True, "lane": "scan"},
        ]
        out = apply_policy(checks, model_used=False)
        self.assertEqual(out["verdict"], "block")


class GateCliTests(unittest.TestCase):
    def test_cli_blocks_secret_diff(self) -> None:
        from logitpick.__main__ import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(
                [
                    "gate",
                    str(FIX / "password-reset.diff"),
                    "--title",
                    "Add password reset",
                ]
            )
        self.assertEqual(code, 1)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["verdict"], "block")
        self.assertFalse(data["model_used"])

    def test_cli_merges_docs_diff(self) -> None:
        from logitpick.__main__ import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["gate", str(FIX / "docs-typo.diff"), "--title", "Fix typos"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["verdict"], "merge")


if __name__ == "__main__":
    unittest.main()
