"""Parse a unified git diff enough for scan-first checks."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
PLUS = re.compile(r"^\+(?!\+\+)")
MINUS = re.compile(r"^-(?!--)")


@dataclass
class DiffFile:
    path: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def is_test(self) -> bool:
        name = self.path.replace("\\", "/").lower()
        base = name.rsplit("/", 1)[-1]
        return (
            "/test" in f"/{name}"
            or base.startswith("test_")
            or base.endswith("_test.py")
            or base.endswith(".test.js")
            or "/tests/" in f"/{name}"
        )

    @property
    def is_docs(self) -> bool:
        lower = self.path.lower()
        return lower.endswith((".md", ".rst", ".txt")) or lower.endswith("license")


@dataclass
class ParsedDiff:
    title: str
    body: str
    files: list[DiffFile]

    @property
    def raw_added(self) -> str:
        parts = []
        for f in self.files:
            for line in f.added:
                parts.append(f"{f.path}: {line}")
        return "\n".join(parts)


def parse_diff(text: str, *, title: str = "", body: str = "") -> ParsedDiff:
    files: list[DiffFile] = []
    current: DiffFile | None = None
    for line in text.splitlines():
        if line.startswith("# SYNTHETIC_FIXTURE"):
            continue
        m = HEADER.match(line)
        if m:
            current = DiffFile(path=m.group(2))
            files.append(current)
            continue
        if current is None:
            continue
        if PLUS.match(line):
            current.added.append(line[1:])
        elif MINUS.match(line):
            current.removed.append(line[1:])
    return ParsedDiff(title=title, body=body, files=files)
