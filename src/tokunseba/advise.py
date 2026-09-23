"""Offline routing advice.

The local judge is too slow to sit in front of every request and, on its own admission,
unreliable on unfamiliar questions. But run over requests that have *already happened*, with
no latency budget and no ability to affect an answer, it is genuinely useful: it can tell you
which of your turns looked easy, what those turns actually cost, and what they would have cost
on a cheaper model.

That turns "should I route by prompt?" from a guess into a measurement you can check before
letting anything route automatically.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .pricing import Price, price_for

# Laya's difficulty rubric, in order. Index 0 and 1 are the two easy levels.
DIFFICULTY_LEVELS = ["trivial", "easy", "moderate", "hard"]

# Measured on laya 0.3.5, 2026-09-22, on real prompts and on a deliberately easy-versus-hard
# control set:
#
#   domain     high confidence and correct: math_or_logic 1.00, code 0.96, chitchat 0.99
#   difficulty correctly ordered (trivial 1.00-1.23, hard 2.13-2.24) but confidence never
#              rose above 0.39, so it can never clear the 0.80 gate the rest of the tool uses
#
# So domain is treated as a gated decision, and difficulty only as a ranked score with its own
# much lower gate. Reporting difficulty as though it were confident would be dishonest, and
# routing on it at the normal gate would simply never fire.
DIFFICULTY_GATE = 0.25
EASY_SCORE = 1.30


@dataclass
class Turn:
    request_id: str
    session_id: str
    model: str
    provider: str
    prompt: str
    input_tokens: int
    cache_read: int
    cache_write: int
    output_tokens: int
    cost_usd: float
    difficulty: float | None = None
    difficulty_confidence: float = 0.0
    domain: str = ""
    domain_confidence: float = 0.0


@dataclass
class Advice:
    turns: list[Turn] = field(default_factory=list)
    judged: int = 0
    confident: int = 0
    by_level: dict[str, list[Turn]] = field(default_factory=dict)
    by_domain: dict[str, int] = field(default_factory=dict)
    backend: str = ""
    note: str = ""

    @property
    def total_cost(self) -> float:
        return sum(t.cost_usd for t in self.turns)

    @property
    def easy_turns(self) -> list[Turn]:
        """Turns the judge scored as easy, by raw score rather than by its own confidence."""
        return [t for t in self.turns
                if t.difficulty is not None and t.difficulty <= EASY_SCORE]

    @property
    def confident_domains(self) -> dict[str, list[Turn]]:
        out: dict[str, list[Turn]] = {}
        for t in self.turns:
            if t.domain and t.domain_confidence >= 0.80:
                out.setdefault(t.domain, []).append(t)
        return out


WRAPPERS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S | re.I),
    re.compile(r"<local-command-[a-z-]+>.*?</local-command-[a-z-]+>", re.S | re.I),
    re.compile(r"<command-(?:name|message|args)>.*?</command-(?:name|message|args)>", re.S | re.I),
    re.compile(r"<session>|</session>", re.I),
    re.compile(r"<EXTREMELY_IMPORTANT>.*?</EXTREMELY_IMPORTANT>", re.S),
]


def strip_wrappers(text: str) -> str:
    """Remove the harness scaffolding around what the human actually typed.

    A Claude Code turn arrives wrapped in system reminders, injected skill text and command
    metadata. Judging that blob instead of the request is how you get a meaningless answer.
    """
    for pat in WRAPPERS:
        text = pat.sub(" ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def first_user_text(body: dict) -> str:
    """The opening human turn of a conversation, which is what a router would see."""
    for m in body.get("messages", []) or []:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            got = strip_wrappers(c)
        elif isinstance(c, list):
            parts = [b.get("text", "") for b in c
                     if isinstance(b, dict) and b.get("type") == "text"]
            got = strip_wrappers("\n".join(parts)) if parts else ""
        else:
            got = ""
        if got:
            return got
    return ""


def collect_turns(ledger, bodies_dir: Path, since_ts: float, limit: int = 200) -> list[Turn]:
    """One Turn per conversation, taken from its first recorded request."""
    rows = ledger.first_requests(since_ts, limit)
    out: list[Turn] = []
    for r in rows:
        path = bodies_dir / f"{r['id']}.orig.json"
        if not path.exists():
            continue
        try:
            body = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        prompt = first_user_text(body).strip()
        if not prompt:
            continue
        out.append(Turn(
            request_id=r["id"], session_id=r["session_id"], model=r["model"],
            provider=r["provider"], prompt=prompt, input_tokens=r["input_tokens"],
            cache_read=r["cache_read"], cache_write=r["cache_write"],
            output_tokens=r["output_tokens"], cost_usd=r["cost_usd"]))
    return out


def judge_turns(turns: list[Turn], judge_chain, threshold: float) -> Advice:
    """Rate each opening prompt with the best backend available.

    This used to require the local model, which made the whole command unusable for anyone
    who had not downloaded 800 MB. The rules backend answers the same questions from
    regexes, so the advice is always available; it is simply less certain, and since every
    conclusion here is gated on confidence, less certain means fewer claims rather than
    worse ones.
    """
    from .judge import router_questions
    adv = Advice(turns=turns)
    questions = router_questions()

    backend = next((b for b in judge_chain.backends if b.available()), None)
    if backend is None:
        adv.note = "no judge backend is available"
        return adv
    adv.backend = getattr(backend, "name", "")

    for t in turns:
        try:
            answers = backend.ask({"request": t.prompt[:1200]}, questions)
        except Exception as exc:  # noqa: BLE001
            adv.note = f"judge failed: {str(exc)[:120]}"
            break
        adv.judged += 1
        d = answers.get("difficulty")
        if d is not None:
            t.difficulty = float(d.value)
            t.difficulty_confidence = d.confidence
        dom = answers.get("domain")
        if dom is not None:
            t.domain = str(dom.value)
            t.domain_confidence = dom.confidence
        if t.difficulty is not None and t.difficulty_confidence >= DIFFICULTY_GATE:
            adv.confident += 1
            level = DIFFICULTY_LEVELS[min(int(t.difficulty), len(DIFFICULTY_LEVELS) - 1)]
            adv.by_level.setdefault(level, []).append(t)
        if t.domain_confidence >= threshold and t.domain:
            adv.by_domain[t.domain] = adv.by_domain.get(t.domain, 0) + 1
    return adv


def counterfactual_cost(turns: list[Turn], target_model: str, overrides: dict) -> float | None:
    """What these turns would have cost on another model, at the same token counts."""
    total = 0.0
    for t in turns:
        p: Price | None = price_for(t.provider, target_model, overrides)
        if p is None:
            return None
        total += (t.input_tokens * p.input + t.cache_read * p.cache_read
                  + t.cache_write * p.cache_write + t.output_tokens * p.output) / 1e6
    return total
