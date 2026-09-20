"""Deterministic diff checks. These are the viral demo's loud bars, without a model."""

from __future__ import annotations

import re
from typing import Any

from .diffparse import ParsedDiff

# Marker used in synthetic fixtures so leakcheck can allow them.
FIXTURE_NEEDLE = "EXAMPLE_NOT_A_KEY"

SECRET_NEEDLES = (
    FIXTURE_NEEDLE,
    "sk_live_",
    "sk_test_",
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
)

SQL_FSTRING = re.compile(
    r"""(?:query|execute|executemany)\s*\(\s*f['"].*\b(?:SELECT|INSERT|UPDATE|DELETE)\b""",
    re.IGNORECASE,
)
SQL_PERCENT = re.compile(
    r"""(?:query|execute)\s*\(\s*['"][^'"]*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^'"]*%s""",
    re.IGNORECASE,
)
SQL_PLUS = re.compile(
    r"""(?:query|execute)\s*\([^)]*\+[^)]*\b(?:SELECT|INSERT|email|user)""",
    re.IGNORECASE,
)

AUTH_PATH = re.compile(r"(?:^|/)(?:auth|jwt|password|session)(?:/|\.|_)", re.IGNORECASE)
DEBUG_LINE = re.compile(r"^\s*(?:print\s*\(|console\.log\s*\(|debugger\b)", re.IGNORECASE)
TODO_SHIP = re.compile(r"TODO (?:remove|before merge)", re.IGNORECASE)


def _added_lines(diff: ParsedDiff) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in diff.files:
        for line in f.added:
            out.append((f.path, line))
    return out


def scan_hardcoded_secret(diff: ParsedDiff) -> dict[str, Any]:
    hits = []
    for path, line in _added_lines(diff):
        for needle in SECRET_NEEDLES:
            if needle in line:
                hits.append(f"{path}: {line.strip()[:120]}")
                break
    return _result("hardcoded_secret", hits, "literal secret-shaped assignment in added lines")


def scan_injection_risk(diff: ParsedDiff) -> dict[str, Any]:
    hits = []
    for path, line in _added_lines(diff):
        if SQL_FSTRING.search(line) or SQL_PERCENT.search(line) or SQL_PLUS.search(line):
            hits.append(f"{path}: {line.strip()[:120]}")
    return _result("injection_risk", hits, "SQL built with f-string / %s / concat in added lines")


def scan_touches_auth(diff: ParsedDiff) -> dict[str, Any]:
    paths = sorted({f.path for f in diff.files if AUTH_PATH.search(f.path.replace("\\", "/"))})
    return _result("touches_auth", paths, "changed path looks like auth/jwt/password/session")


def scan_debug_leftovers(diff: ParsedDiff) -> dict[str, Any]:
    hits = []
    for path, line in _added_lines(diff):
        if DEBUG_LINE.search(line) or TODO_SHIP.search(line):
            hits.append(f"{path}: {line.strip()[:120]}")
    return _result("debug_leftovers", hits, "print/console.log/TODO-remove in added lines")


def scan_docs_only(diff: ParsedDiff) -> dict[str, Any]:
    if not diff.files:
        return _result("docs_only", [], "no files")
    only = all(f.is_docs for f in diff.files)
    return {
        "id": "docs_only",
        "lane": "scan",
        "hit": only,
        "evidence": [f.path for f in diff.files] if only else [],
        "why": "every changed file is markdown/text",
    }


def scan_adds_tests(diff: ParsedDiff) -> dict[str, Any]:
    n = sum(len(f.added) for f in diff.files if f.is_test)
    return {
        "id": "adds_tests",
        "lane": "scan",
        "hit": n > 0,
        "evidence": [f"{n} added test lines"] if n else [],
        "why": "added lines in a test path",
    }


def scan_weakens_tests(diff: ParsedDiff) -> dict[str, Any]:
    removed = sum(len(f.removed) for f in diff.files if f.is_test)
    added = sum(len(f.added) for f in diff.files if f.is_test)
    hit = removed > added and removed >= 3
    return {
        "id": "weakens_tests",
        "lane": "scan",
        "hit": hit,
        "evidence": [f"test lines removed={removed} added={added}"] if hit else [],
        "why": "net deletion of test lines",
    }


def scan_data_migration(diff: ParsedDiff) -> dict[str, Any]:
    paths = [
        f.path
        for f in diff.files
        if "alembic" in f.path.lower() or "/migrations/" in f.path.replace("\\", "/").lower()
    ]
    return _result("data_migration", paths, "alembic/migrations path changed")


def run_scans(diff: ParsedDiff) -> list[dict[str, Any]]:
    return [
        scan_hardcoded_secret(diff),
        scan_injection_risk(diff),
        scan_touches_auth(diff),
        scan_weakens_tests(diff),
        scan_adds_tests(diff),
        scan_debug_leftovers(diff),
        scan_docs_only(diff),
        scan_data_migration(diff),
    ]


def _result(cid: str, evidence: list[str], why: str) -> dict[str, Any]:
    return {
        "id": cid,
        "lane": "scan",
        "hit": bool(evidence),
        "evidence": evidence,
        "why": why,
    }
