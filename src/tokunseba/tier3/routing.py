"""Opt-in: send easy turns to a cheaper or local model, but only at the start of a conversation.

Switching model mid-conversation forfeits the prompt cache and, on newer Anthropic models,
the thinking blocks bound to the producing model. So routing only ever happens on turn one.
"""
from __future__ import annotations

from .effort import is_easy

LOCAL_OK_DOMAINS = {"chitchat", "writing"}


def apply(norm, body: dict, signals: dict, cfg) -> tuple[str | None, str]:
    """Return (new_upstream_name_or_None, reason)."""
    if not cfg.tier3:
        return None, ""
    if len(norm.messages) != 1:
        return None, "not-session-start"
    if not is_easy(signals):
        return None, "not-easy"

    o = cfg.tier3_opts
    if o.local_routing and o.local_model and norm.provider == "openai":
        if signals.get("domain") in LOCAL_OK_DOMAINS:
            body["model"] = o.local_model
            return "ollama", "local_routed"

    if o.model_routing and norm.model in o.model_map:
        body["model"] = o.model_map[norm.model]
        return None, "model_routed"
    return None, ""
