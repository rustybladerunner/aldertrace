"""Refuse to ship a folder that looks like it grew secrets or personal data."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Workspace-local only: these are the patterns that would make a public extract
# a leak. Keep them boring. Do not add operator-specific emails here.
PLAINTEXT = re.compile(
    r"(api[_-]?key|secret|token|password|Bearer )\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}",
    re.IGNORECASE,
)
SK_LIVE = re.compile(r"sk-[A-Za-z0-9]{20,}")
ENV_ASSIGN = re.compile(r"^(GROQ|OPENAI|GEMINI|ANTHROPIC|X_BEARER)_[A-Z0-9_]*=\S+", re.MULTILINE)

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv"}
TEXT_SUFFIX = {".py", ".md", ".json", ".txt", ".toml", ".yml", ".yaml", ".gitignore", ".diff"}
SYNTHETIC_MARK = "# SYNTHETIC_FIXTURE"


def iter_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIX and path.name not in {".gitignore"}:
            continue
        out.append(path)
    return out


def scan() -> list[str]:
    hits: list[str] = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        synthetic = SYNTHETIC_MARK in text[:400]
        if not synthetic:
            if PLAINTEXT.search(text):
                hits.append(f"{rel}: plaintext credential assignment")
            if ENV_ASSIGN.search(text):
                hits.append(f"{rel}: provider env assignment")
        if SK_LIVE.search(text):
            hits.append(f"{rel}: sk- live-looking token")
    return hits


def main() -> int:
    hits = scan()
    if hits:
        print("LEAKCHECK FAIL")
        for h in hits:
            print(f"  {h}")
        return 1
    print(f"LEAKCHECK OK ({len(iter_files())} files)")
    return 0
