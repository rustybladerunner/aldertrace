"""Keep/drop compaction. Last observation per identity wins. No summarizer."""

from __future__ import annotations

from typing import Any

STICKY_KINDS = frozenset({"user", "goal", "system"})


def compact(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("trace must be a JSON object")
    items = raw.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty array")

    parsed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] must be an object")
        iid = item.get("id")
        if not isinstance(iid, str) or not iid.strip():
            raise ValueError(f"items[{i}] needs a string id")
        if iid in seen_ids:
            raise ValueError(f"duplicate id {iid!r}")
        seen_ids.add(iid)
        kind = item.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f"items[{i}] needs a string kind")
        parsed.append(
            {
                "id": iid,
                "kind": kind.strip().lower(),
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "cmd": str(item.get("cmd") or ""),
                "ok": bool(item.get("ok", True)),
                "excerpt": str(item.get("excerpt") or ""),
                "sticky": bool(item.get("sticky", False)),
            }
        )

    action: dict[str, str] = {}
    reason: dict[str, str] = {}
    buckets: dict[str, list[str]] = {}

    for item in parsed:
        if item["kind"] in STICKY_KINDS or item["sticky"]:
            action[item["id"]] = "keep"
            reason[item["id"]] = "sticky"
            continue
        key = _identity(item)
        buckets.setdefault(key, []).append(item["id"])

    for _key, group in buckets.items():
        for earlier in group[:-1]:
            action[earlier] = "drop"
            reason[earlier] = "superseded"
        last = group[-1]
        action[last] = "keep"
        reason[last] = "latest"

    decisions = []
    for item in parsed:
        iid = item["id"]
        decisions.append(
            {
                "id": iid,
                "action": action[iid],
                "reason": reason[iid],
                "lane": "scan",
                "kind": item["kind"],
                "identity": item["kind"] if reason[iid] == "sticky" else _identity(item),
                "chars": len(item["excerpt"]),
            }
        )

    kept = [d["id"] for d in decisions if d["action"] == "keep"]
    dropped = [d["id"] for d in decisions if d["action"] == "drop"]
    chars_in = sum(d["chars"] for d in decisions)
    chars_out = sum(d["chars"] for d in decisions if d["action"] == "keep")
    return {
        "goal": str(raw.get("goal") or ""),
        "kept": kept,
        "dropped": dropped,
        "decisions": decisions,
        "model_used": False,
        "chars_in": chars_in,
        "chars_out": chars_out,
        "why": "last observation per identity; user/goal/system never drop",
    }


def _identity(item: dict[str, Any]) -> str:
    kind = item["kind"]
    if item["path"]:
        return f"{kind}:{item['path']}"
    if item["cmd"]:
        return f"{kind}:{item['cmd'][:120]}"
    name = item["name"] or kind
    return f"{kind}:{name}"
