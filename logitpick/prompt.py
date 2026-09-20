"""Frozen prompt template. Changing this invalidates testdata/live-baseline.json."""

from __future__ import annotations

# Keep this string exact. Live baseline hashes it.
TEMPLATE = """Reply with exactly one letter. No punctuation. No explanation.

State:
{state}

Question:
{instructions}

Options:
{options}

Answer:"""


def render(
    state: str,
    instructions: str,
    options: dict[str, str],
    codes: dict[str, str],
) -> str:
    lines = []
    for oid, code in codes.items():
        desc = options[oid].strip() or oid
        lines.append(f"{code}. {desc}")
    return TEMPLATE.format(
        state=state.strip(),
        instructions=instructions.strip(),
        options="\n".join(lines),
    )
