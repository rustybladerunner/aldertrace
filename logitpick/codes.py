"""Map caller option ids to single-letter codes A..P."""

from __future__ import annotations

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MIN_OPTIONS = 2
MAX_OPTIONS = 16


def assign_codes(option_ids: list[str]) -> dict[str, str]:
    if len(option_ids) != len(set(option_ids)):
        raise ValueError("option ids must be unique")
    n = len(option_ids)
    if n < MIN_OPTIONS or n > MAX_OPTIONS:
        raise ValueError(f"need {MIN_OPTIONS}–{MAX_OPTIONS} options, got {n}")
    for oid in option_ids:
        if not oid or not isinstance(oid, str):
            raise ValueError("option ids must be non-empty strings")
        if oid.strip() != oid:
            raise ValueError(f"option id has surrounding whitespace: {oid!r}")
    return {oid: LETTERS[i] for i, oid in enumerate(option_ids)}


def letter_token(code: str) -> str:
    if len(code) != 1 or code not in LETTERS:
        raise ValueError(f"not a letter code: {code!r}")
    return code
