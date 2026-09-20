"""Build a pick request dict from CLI flags or a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from .schema import PickError


def build_pick_payload(
    *,
    from_json: Path | None,
    state: str | None,
    instructions: str | None,
    option: list[str] | None,
    qid: str,
    model: str,
) -> dict:
    if from_json is not None:
        if state is not None or instructions is not None or option:
            raise PickError(
                "mixed_pick",
                "use --from-json alone, or the flag form",
                "from_json",
            )
        if not from_json.is_file():
            raise PickError("missing_json", f"no such file: {from_json}", "from_json")
        try:
            raw = json.loads(from_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise PickError("malformed", f"invalid JSON: {e}", "from_json") from e
        if not isinstance(raw, dict):
            raise PickError("malformed", "from-json must be a JSON object", "from_json")
        out = dict(raw)
        out["model"] = model
        return out

    if not state or not instructions or not option:
        raise PickError(
            "missing_flags",
            "need --state, --instructions, and at least one --option (or --from-json)",
        )
    options: dict[str, str] = {}
    for item in option:
        if "=" not in item:
            raise PickError("invalid_option", "each --option needs id=description", "option")
        oid, desc = item.split("=", 1)
        options[oid] = desc
    return {
        "state": state,
        "model": model,
        "questions": {
            qid: {
                "instructions": instructions,
                "options": options,
            }
        },
    }
