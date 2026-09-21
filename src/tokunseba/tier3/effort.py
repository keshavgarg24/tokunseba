"""Opt-in: lower the effort level on turns a calibrated judge is confident are easy.

This is the first thing in tokunseba that can change an answer, so it is off by default,
gated on confidence, applied only to the treatment arm, and measured against a control.
"""
from __future__ import annotations

EASY_LEVELS = 2  # the two lowest levels of Laya's difficulty rubric


def is_easy(signals: dict) -> bool:
    d = signals.get("difficulty")
    if d is None:
        return False
    try:
        return float(d) < EASY_LEVELS
    except (TypeError, ValueError):
        return False


def apply(norm, body: dict, signals: dict, cfg) -> bool:
    if not (cfg.tier3 and cfg.tier3_opts.effort_routing):
        return False
    if norm.provider != "anthropic" or not str(norm.model).startswith("claude-"):
        return False
    if (body.get("output_config") or {}).get("effort"):
        return False
    if not is_easy(signals):
        return False
    body.setdefault("output_config", {})["effort"] = "low"
    return True
