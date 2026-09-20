"""Keep/drop compaction: last observation wins. No model."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from logitpick.compact import compact

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "testdata" / "fixtures" / "traces-auth.json"


class CompactTests(unittest.TestCase):
    def test_fixture_drops_superseded_reads_and_checks(self) -> None:
        raw = json.loads(FIX.read_text(encoding="utf-8"))
        out = compact(raw)
        self.assertFalse(out["model_used"])
        self.assertEqual(out["kept"], ["u1", "r2", "s2", "g1"])
        self.assertEqual(out["dropped"], ["r1", "s1"])
        self.assertLess(out["chars_out"], out["chars_in"])
        by_id = {d["id"]: d for d in out["decisions"]}
        self.assertEqual(by_id["u1"]["reason"], "sticky")
        self.assertEqual(by_id["r1"]["reason"], "superseded")
        self.assertEqual(by_id["r2"]["reason"], "latest")

    def test_two_user_messages_both_keep(self) -> None:
        out = compact(
            {
                "items": [
                    {"id": "a", "kind": "user", "excerpt": "first"},
                    {"id": "b", "kind": "user", "excerpt": "second"},
                ]
            }
        )
        self.assertEqual(out["kept"], ["a", "b"])
        self.assertEqual(out["dropped"], [])

    def test_cli(self) -> None:
        from logitpick.__main__ import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["compact", str(FIX)])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["dropped"], ["r1", "s1"])


if __name__ == "__main__":
    unittest.main()
