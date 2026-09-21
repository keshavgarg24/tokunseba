"""Add prompt-cache breakpoints where a client forgot them. This changes billing, never output."""
from __future__ import annotations

import statistics


def ttl_advice(gaps: list[float]) -> str | None:
    """A slow-paced session keeps paying to rewrite a 5-minute cache. Advise the 1h TTL."""
    if len(gaps) >= 5 and statistics.median(gaps) > 300:
        return "1h"
    return None


def _marker(ttl: str | None) -> dict:
    m = {"type": "ephemeral"}
    if ttl:
        m["ttl"] = ttl
    return m


def inject(norm, body: dict, delta_start: int, estimator, min_tokens: int, ttl: str | None) -> int:
    """Return how many breakpoints were added. Never touches existing markers."""
    if norm.provider != "anthropic" or norm.has_cache_control:
        return 0
    if not str(norm.model).startswith("claude-"):
        return 0
    stable = (norm.tools_json or "") + (norm.system_text or "")
    if estimator.count(stable, norm.provider, norm.model) < min_tokens:
        return 0

    added = 0
    system = body.get("system")
    if isinstance(system, str) and system:
        body["system"] = [{"type": "text", "text": system, "cache_control": _marker(ttl)}]
        added += 1
    elif isinstance(system, list) and system:
        for b in reversed(system):
            if isinstance(b, dict) and b.get("type") == "text":
                b["cache_control"] = _marker(ttl)
                added += 1
                break

    tools = body.get("tools")
    if isinstance(tools, list) and tools and isinstance(tools[-1], dict):
        tools[-1]["cache_control"] = _marker(ttl)
        added += 1

    msgs = body.get("messages") or []
    if msgs:
        last = msgs[-1]
        content = last.get("content")
        if isinstance(content, str):
            last["content"] = [{"type": "text", "text": content, "cache_control": _marker(ttl)}]
            added += 1
        elif isinstance(content, list) and content:
            for b in reversed(content):
                if isinstance(b, dict) and b.get("type") in ("text", "tool_result", "image", "document"):
                    b["cache_control"] = _marker(ttl)
                    added += 1
                    break
    return added
