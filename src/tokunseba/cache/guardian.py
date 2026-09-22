"""Detect prompt-cache prefix drift. A cache miss costs ten times a cache hit, so drift is the
most expensive thing that can happen silently."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..protocols.base import NormalizedRequest, canonical_json, sha256_text

TIMESTAMP = re.compile(
    r"\b20\d\d-\d\d-\d\d\b|\b\d{1,2}:\d\d(?::\d\d)?\s?(?:AM|PM|am|pm)?\b|Today's date|"
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
UUIDISH = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


@dataclass
class DriftEvent:
    region: str
    cause: str


def regions(norm: NormalizedRequest) -> dict[str, str]:
    """Hash each cacheable region so the next request can be compared against it."""
    out = {"tools": sha256_text(norm.tools_json), "system": sha256_text(norm.system_text)}
    for i, m in enumerate(norm.messages):
        out[f"messages[{i}]"] = m.raw_hash
    return out


def region_text(norm: NormalizedRequest, label: str) -> str:
    if label == "tools":
        return norm.tools_json
    if label == "system":
        return norm.system_text
    m = re.match(r"messages\[(\d+)\]", label)
    if m:
        i = int(m.group(1))
        if i < len(norm.messages):
            return canonical_json(norm.raw.get("messages", [])[i]) if i < len(norm.raw.get("messages", []) or []) else ""
    return ""


def breakpoints(norm: NormalizedRequest) -> list[tuple[str, str]]:
    """Walk the render order (tools, system, messages) and emit (label, prefix_sha) at each
    cache_control marker. The sha covers everything up to and including that block."""
    out: list[tuple[str, str]] = []
    acc: list[str] = []
    raw = norm.raw

    tools = raw.get("tools") or []
    for t in tools:
        acc.append(canonical_json(t))
        if isinstance(t, dict) and "cache_control" in t:
            out.append(("tools", sha256_text("".join(acc))))

    system = raw.get("system")
    if isinstance(system, list):
        for i, b in enumerate(system):
            acc.append(canonical_json(b))
            if isinstance(b, dict) and "cache_control" in b:
                out.append((f"system[{i}]", sha256_text("".join(acc))))
    elif isinstance(system, str):
        acc.append(system)

    for i, m in enumerate(raw.get("messages") or []):
        content = m.get("content")
        if isinstance(content, list):
            for j, b in enumerate(content):
                acc.append(canonical_json(b))
                if isinstance(b, dict) and "cache_control" in b:
                    out.append((f"messages[{i}][{j}]", sha256_text("".join(acc))))
        else:
            acc.append(canonical_json(content))
    if isinstance(raw.get("cache_control"), dict) and not out:
        out.append(("auto", sha256_text("".join(acc))))
    return out


def _cause(prev_text: str, cur_text: str) -> str:
    if not prev_text:
        # the previous text was not retained, so the cause cannot be attributed
        return "unknown"
    if prev_text == cur_text:
        return "unknown"
    if TIMESTAMP.search(prev_text) or TIMESTAMP.search(cur_text):
        p = TIMESTAMP.sub("<T>", prev_text)
        c = TIMESTAMP.sub("<T>", cur_text)
        if p == c:
            return "timestamp"
    if UUIDISH.search(prev_text) or UUIDISH.search(cur_text):
        if UUIDISH.sub("<U>", prev_text) == UUIDISH.sub("<U>", cur_text):
            return "volatile_id"
    try:
        import json
        if json.loads(prev_text) == json.loads(cur_text):
            return "key_order"
    except (ValueError, TypeError):
        pass
    return "content_changed"


def check(prev_breakpoints: list[tuple[str, str]], cur_breakpoints: list[tuple[str, str]],
          prev_regions: dict[str, str], cur: NormalizedRequest,
          prev_region_text: dict[str, str] | None = None) -> list[DriftEvent]:
    """Report drift only where a cached prefix changed. Positions that simply grew are not drift."""
    events: list[DriftEvent] = []
    prev_map = dict(prev_breakpoints)
    cur_map = dict(cur_breakpoints)
    shared = [lbl for lbl in cur_map if lbl in prev_map and prev_map[lbl] != cur_map[lbl]]
    if not shared:
        return events
    cur_regions = regions(cur)
    changed = [lbl for lbl in ("tools", "system") if lbl in prev_regions and prev_regions[lbl] != cur_regions.get(lbl)]
    for lbl in changed:
        prev_text = (prev_region_text or {}).get(lbl, "")
        events.append(DriftEvent(lbl, _cause(prev_text, region_text(cur, lbl))))
    if not events:
        for i in range(len(cur.messages)):
            key = f"messages[{i}]"
            if key in prev_regions and prev_regions[key] != cur_regions.get(key):
                events.append(DriftEvent(key, "history_edited"))
                break
    if not events:
        events.append(DriftEvent(shared[0], "content_changed"))
    return events


def post_check(turn_index: int, has_breakpoints: bool, cache_read: int) -> str | None:
    """After the response: a cached request on a later turn that read nothing is a silent miss."""
    if turn_index >= 1 and has_breakpoints and cache_read == 0:
        return "cache_miss_unexplained"
    return None
