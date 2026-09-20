"""Scan-first PR gate. Model is optional garnish."""

from __future__ import annotations

from typing import Any

from .diffparse import parse_diff
from .engine import pick
from .policy import apply_policy
from .scans import run_scans
from .schema import parse_request


def gate(
    diff_text: str,
    *,
    title: str = "",
    body: str = "",
    backend: Any | None = None,
    model: str = "llama3.2",
) -> dict[str, Any]:
    parsed = parse_diff(diff_text, title=title, body=body)
    checks = run_scans(parsed)
    model_used = backend is not None
    if backend is not None:
        checks.extend(_model_checks(parsed, backend, model))
    decision = apply_policy(checks, model_used=model_used)
    return {
        "title": title,
        "files": [f.path for f in parsed.files],
        "checks": checks,
        **decision,
    }


def _model_checks(parsed: Any, backend: Any, model: str) -> list[dict[str, Any]]:
    state = f"Title: {parsed.title}\n\n{parsed.body}\n\nAdded lines:\n{parsed.raw_added[:4000]}"
    req = parse_request(
        {
            "state": state or "empty diff",
            "model": model,
            "questions": {
                "description_matches": {
                    "instructions": "Does the title/body honestly describe the added code?",
                    "options": {
                        "yes": "title matches the diff",
                        "no": "title hides or mismatches the diff",
                    },
                }
            },
        }
    )
    result = pick(req, backend)
    ans = result["answers"]["description_matches"]
    p_yes = float(ans["probabilities"].get("yes") or 0.0)
    return [
        {
            "id": "description_matches",
            "lane": "model",
            "hit": p_yes >= 0.5,
            "p_yes": p_yes,
            "status": ans["status"],
            "why": "optional logitpick yes/no; not used for secret/SQL",
        }
    ]
