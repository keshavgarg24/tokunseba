"""The judge layer.

One rule governs every use: a judge may only make a decision whose wrong answer costs tokens,
never correctness. Low confidence means abstain, and abstaining always means doing the
conservative thing.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Answer:
    type: str  # noul | choice | score
    value: str | float
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


class Judge(Protocol):
    name: str

    def available(self) -> bool: ...
    def ask(self, state, questions: dict) -> dict[str, Answer]: ...


def gate(a: Answer | None, threshold: float) -> bool | None:
    """True, False, or None for abstain."""
    if a is None or a.confidence < threshold:
        return None
    if a.type == "noul":
        try:
            return float(a.value) >= 0.5
        except (TypeError, ValueError):
            return None
    return True


class JudgeChain:
    def __init__(self, backends: list, threshold: float = 0.8, ledger=None, timeout: float = 5.0):
        self.backends = [b for b in backends if b is not None]
        self.threshold = threshold
        self.ledger = ledger
        self.timeout = timeout
        self._locks = {id(b): asyncio.Lock() for b in self.backends}

    def available_names(self) -> list[str]:
        return [b.name for b in self.backends if b.available()]

    def ready_names(self) -> list[str]:
        """Backends that can answer immediately. A cold model is not one of them."""
        return [b.name for b in self.backends
                if b.available() and getattr(b, "ready", lambda: True)()]

    async def ask(self, state, questions: dict, timeout: float | None = None) -> dict[str, Answer]:
        out: dict[str, Answer] = {}
        remaining = dict(questions)
        for b in self.backends:
            if not remaining:
                break
            if not b.available():
                continue
            try:
                async with self._locks[id(b)]:
                    got = await asyncio.wait_for(
                        asyncio.to_thread(b.ask, state, remaining),
                        timeout or self.timeout)
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 - a judge must never break a request
                if self.ledger is not None:
                    self.ledger.record_event("judge_error", {"backend": b.name, "error": str(exc)[:200]})
                continue
            for k, v in (got or {}).items():
                if k in remaining and v is not None:
                    out[k] = v
                    remaining.pop(k, None)
        return out

    def decide(self, answers: dict[str, Answer], key: str, want=True,
               threshold: float | None = None) -> bool | None:
        a = answers.get(key)
        g = gate(a, self.threshold if threshold is None else threshold)
        if g is None:
            return None
        if a.type == "noul":
            return g is bool(want)
        return a.value == want

    def value(self, answers: dict[str, Answer], key: str, threshold: float | None = None):
        a = answers.get(key)
        if a is None or a.confidence < (self.threshold if threshold is None else threshold):
            return None
        return a.value
