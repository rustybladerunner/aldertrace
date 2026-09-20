"""CLI payload builder — no Ollama."""

from __future__ import annotations

import unittest
from pathlib import Path

from logitpick.pick_payload import build_pick_payload
from logitpick.schema import PickError, parse_request

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "testdata" / "fixtures" / "triage.json"


class PayloadTests(unittest.TestCase):
    def test_from_json_loads_two_questions(self) -> None:
        raw = build_pick_payload(
            from_json=TRIAGE,
            state=None,
            instructions=None,
            option=None,
            qid="q",
            model="llama3.2",
        )
        req = parse_request(raw)
        self.assertEqual([q.id for q in req.questions], ["route", "noise"])
        self.assertEqual(req.model, "llama3.2")

    def test_flag_form_still_one_question(self) -> None:
        raw = build_pick_payload(
            from_json=None,
            state="rename a button",
            instructions="Which mode?",
            option=["fast=UI", "full=multi-file"],
            qid="route",
            model="llama3.2",
        )
        req = parse_request(raw)
        self.assertEqual(len(req.questions), 1)
        self.assertEqual(req.questions[0].id, "route")

    def test_mixed_form_is_an_error(self) -> None:
        with self.assertRaises(PickError) as ctx:
            build_pick_payload(
                from_json=TRIAGE,
                state="also flags",
                instructions=None,
                option=None,
                qid="q",
                model="llama3.2",
            )
        self.assertEqual(ctx.exception.code, "mixed_pick")
