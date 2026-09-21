"""Deterministic backend. Always available, costs nothing, never wrong about what it knows."""
from __future__ import annotations

import json

from ..transform import summarize
from .base import Answer


class RulesJudge:
    name = "rules"

    def available(self) -> bool:
        return True

    def ask(self, state, questions: dict) -> dict[str, Answer]:
        text = state if isinstance(state, str) else json.dumps(state, default=str)
        out: dict[str, Answer] = {}
        if "output_type" in questions:
            label, conf = summarize.detect_type_regex_only(text, None, None)
            if conf >= 0.6:
                out["output_type"] = Answer("choice", label, conf, {label: conf})
        return out
