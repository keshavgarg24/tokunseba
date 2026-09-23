"""Opt-in: send a turn to a cheaper or local model, but only at the start of a conversation.

Switching model mid-conversation forfeits the prompt cache and, on newer Anthropic models,
the thinking blocks bound to the producing model. So routing only ever happens on turn one.

Rules are matched against the signals the judge produced for the opening prompt. A signal is
only present when its confidence cleared the gate, so an unsure judge matches nothing and
the turn keeps the model it arrived with. That is the whole safety story: the failure mode
of every heuristic here is "no change".
"""
from __future__ import annotations

from .effort import is_easy

LOCAL_OK_DOMAINS = {"chitchat", "writing"}

# Which upstreams can receive a request that arrived in a given protocol. tokunseba rewrites
# a body, it does not translate between protocols, so anything not listed here would send an
# Anthropic-shaped body to an OpenAI-shaped endpoint and get a 400 back. Ollama is reachable
# from OpenAI clients because it serves an OpenAI-compatible route.
COMPATIBLE: dict[str, set[str]] = {
    "anthropic": {"anthropic"},
    "openai": {"openai", "ollama"},
    "gemini": {"gemini"},
    "ollama": {"ollama", "openai"},
}


def compatible(provider: str, kind: str) -> bool:
    return kind in COMPATIBLE.get(provider, {provider})


def match(rule: dict, signals: dict) -> bool:
    """Whether every condition this rule states is met by the signals.

    A rule with no conditions never matches. Routing everything unconditionally is a thing
    somebody could ask for by accident and would never ask for on purpose.
    """
    conditions = 0
    want_domain = rule.get("domain") or ""
    if want_domain:
        conditions += 1
        if signals.get("domain") != want_domain:
            return False
    max_difficulty = rule.get("max_difficulty", -1)
    if max_difficulty is not None and max_difficulty >= 0:
        conditions += 1
        got = signals.get("difficulty")
        if got is None:
            return False
        try:
            if float(got) > float(max_difficulty):
                return False
        except (TypeError, ValueError):
            return False
    want_tools = rule.get("needs_tools")
    if want_tools is not None and want_tools != "":
        conditions += 1
        got = signals.get("needs_tools")
        if got is None or bool(float(got)) is not bool(want_tools):
            return False
    return conditions > 0


def first_match(rules: list, signals: dict) -> dict | None:
    for rule in rules or []:
        if isinstance(rule, dict) and match(rule, signals):
            return rule
    return None


def describe(rule: dict) -> str:
    """One line for a table, the same wording the CLI and the ledger both use."""
    bits = []
    if rule.get("domain"):
        bits.append(f"domain={rule['domain']}")
    if rule.get("max_difficulty", -1) is not None and rule.get("max_difficulty", -1) >= 0:
        bits.append(f"difficulty<={rule['max_difficulty']:g}")
    if rule.get("needs_tools") not in (None, ""):
        bits.append(f"needs_tools={'yes' if rule['needs_tools'] else 'no'}")
    target = rule.get("upstream") or "same upstream"
    if rule.get("model"):
        target += f" / {rule['model']}"
    return f"{' and '.join(bits) or 'nothing'} -> {target}"


def apply(norm, body: dict, signals: dict, cfg) -> tuple[str | None, str]:
    """Return (new_upstream_name_or_None, reason)."""
    if not cfg.tier3:
        return None, ""
    if len(norm.messages) != 1:
        return None, "not-session-start"

    o = cfg.tier3_opts

    rule = first_match(getattr(o, "rules", []), signals)
    if rule is not None:
        name = rule.get("upstream") or ""
        if name:
            target = cfg.upstreams.get(name)
            if target is None:
                return None, f"rule-upstream-missing:{name}"
            if not compatible(norm.provider, target.kind):
                return None, f"rule-incompatible:{norm.provider}->{target.kind}"
        if rule.get("model"):
            body["model"] = rule["model"]
        return (name or None), "rule_routed"

    if not is_easy(signals):
        return None, "not-easy"

    if o.local_routing and o.local_model and norm.provider == "openai":
        if signals.get("domain") in LOCAL_OK_DOMAINS:
            body["model"] = o.local_model
            return "ollama", "local_routed"

    if o.model_routing and norm.model in o.model_map:
        body["model"] = o.model_map[norm.model]
        return None, "model_routed"
    return None, ""
