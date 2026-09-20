"""Guards against overclaim and off-loopback bind. No model."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from pathlib import Path

from logitpick.leakcheck import scan
from logitpick.ollama import NextToken, TokenAlt
from logitpick.serve import serve

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
PUBLISH = (ROOT / "PUBLISH.md").read_text(encoding="utf-8")


class _Fake:
    def next_token(self, prompt: str, *, model: str) -> NextToken:
        return NextToken(
            generated="A",
            alts=(TokenAlt("A", -0.05), TokenAlt("B", -3.3)),
            eval_count=1,
            eval_duration_ns=1_000_000,
        )


class ClaimTests(unittest.TestCase):
    def test_readme_names_the_limits(self) -> None:
        lower = README.lower()
        self.assertIn("not jev", lower)
        self.assertIn("not calibrated", lower)
        self.assertIn("incomplete_topk", README)
        self.assertIn("127.0.0.1", README)
        self.assertIn("forward_passes", README)
        self.assertIn("concurrent_questions", README)

    def test_readme_does_not_overclaim(self) -> None:
        lower = README.lower()
        for banned in (
            "jev killer",
            "200× faster",
            "200x faster",
            "can't hallucinate",
            "cannot hallucinate",
            "kv-cache broadcast",
            "5.6x",
            "5.6×",
        ):
            self.assertNotIn(banned, lower)

    def test_publish_gate_exists(self) -> None:
        self.assertIn("visibility must remain private", PUBLISH)
        self.assertIn("explicit public-release approval", PUBLISH)
        self.assertIn("repo-extract", PUBLISH)


class ServeTests(unittest.TestCase):
    def test_refuses_all_interfaces(self) -> None:
        with self.assertRaises(ValueError):
            serve("0.0.0.0", 7340)

    def test_loopback_pick_roundtrip(self) -> None:
        httpd = serve("127.0.0.1", 0, backend=_Fake())
        _host, port = httpd.server_address
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps(
                {
                    "state": "rename a button",
                    "questions": {
                        "route": {
                            "instructions": "Which mode?",
                            "options": {"fast": "UI", "full": "multi-file"},
                        }
                    },
                }
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/pick",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            self.assertEqual(data["answers"]["route"]["choice"], "fast")
            self.assertEqual(data["mode"], "one_question")
            self.assertEqual(data["forward_passes"], 1)
            health = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5)
            self.assertEqual(json.loads(health.read().decode())["ok"], True)
        finally:
            httpd.shutdown()
            httpd.server_close()


class LeakTests(unittest.TestCase):
    def test_tree_is_clean(self) -> None:
        hits = scan()
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
