"""Compose scan hits (and optional model answers) into a ship/don't-ship verdict.

The interesting part of the viral Jev PR demo is this file, not the model.
Blocking secrets/SQL is a scanner. The 0.35–0.65 band is abstention.
"""

from __future__ import annotations

from typing import Any

BLOCKING = ("hardcoded_secret", "injection_risk")
SECURITY = ("touches_auth", "weakens_tests")
NIT = ("debug_leftovers",)
UNCERTAIN_LO = 0.35
UNCERTAIN_HI = 0.65
CRITICAL_MODEL = ("description_matches", "breaks_api")


def apply_policy(
    checks: list[dict[str, Any]],
    *,
    model_used: bool,
) -> dict[str, Any]:
    by_id = {c["id"]: c for c in checks}
    blocking = [c["id"] for c in checks if c["id"] in BLOCKING and c.get("hit")]
    if blocking:
        return _verdict("block", blocking, model_used, "blocking scanner hit")

    security = [c["id"] for c in checks if c["id"] in SECURITY and c.get("hit")]
    if security:
        return _verdict("security_review", security, model_used, "auth or tests look risky")

    uncertain = []
    for cid in CRITICAL_MODEL:
        c = by_id.get(cid)
        if not c or c.get("lane") != "model":
            continue
        p = c.get("p_yes")
        if isinstance(p, float) and UNCERTAIN_LO <= p <= UNCERTAIN_HI:
            uncertain.append(cid)
    if uncertain:
        return _verdict("escalate", uncertain, model_used, "critical model check in 0.35–0.65")

    nits = [c["id"] for c in checks if c["id"] in NIT and c.get("hit")]
    docs = by_id.get("docs_only")
    if nits:
        return _verdict("nits", nits, model_used, "leftovers, not a merge block")
    if docs and docs.get("hit"):
        return _verdict("merge", ["docs_only"], model_used, "docs-only change, no blocking scan")
    return _verdict("merge", [], model_used, "no blocking or security scan hit")


def _verdict(name: str, reasons: list[str], model_used: bool, why: str) -> dict[str, Any]:
    return {
        "verdict": name,
        "reasons": reasons,
        "model_used": model_used,
        "why": why,
    }
