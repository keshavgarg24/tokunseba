"""Deterministic backend. Always available, costs nothing, never wrong about what it knows.

This backend exists so prompt-aware routing works without a download. It answers the same
router questions the local model answers, from regexes and counts, and it reports an honest
confidence for each one. Everything downstream is gated on that confidence, so a heuristic
that is unsure changes nothing: the turn goes to the model it was already going to.

The thresholds below are deliberately lopsided. Saying "this turn is hard" costs nothing,
because hard turns keep the model they had. Saying "this turn is easy" is what can send a
turn to a cheaper model, so only two narrow shapes of prompt ever clear the gate for it: a
greeting, and a short single-sentence lookup with no code and no file in sight.
"""
from __future__ import annotations

import json
import re

from ..transform import summarize
from .base import Answer

# A regex can be strongly suggestive and still be a regex, so no answer here is ever
# reported above this.
MAX_CONFIDENCE = 0.95

_DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "code": (
        r"\b(?:function|class|method|variable|import|compile|runtime|async|await)\b",
        r"\b(?:bug|crash|traceback|stack ?trace|exception|segfault|panic)\b",
        r"\b(?:refactor|debug|implement|deploy|merge|rebase|lint|unit test)\b",
        r"\b(?:api|sdk|cli|repo|repository|branch|commit|pull request|docker|kubernetes)\b",
        r"\b(?:python|javascript|typescript|rust|golang|java|c\+\+|swift|kotlin|sql)\b",
        r"[\w/.-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|php|c|h|cpp|sh|yml|yaml|toml|json)\b",
        r"```|\bdef \w+\(|\bclass \w+[:(]|\bnpm \b|\bgit \b|\buv \b|\bpip \b",
    ),
    "math_or_logic": (
        r"\b(?:prove|proof|theorem|lemma|derivative|integral|matrix|vector|modulo)\b",
        r"\b(?:probabilit|permutation|combinator|factorial|primes?|equations?|solve for)",
        r"\b(?:algebra|calculus|geometry|topology|arithmetic)\b",
        r"\d+\s*[+\-*/^]\s*\d+",
    ),
    "writing": (
        r"\b(?:write|draft|rewrite|edit|proofread|paraphrase|summari[sz]e)\b.{0,40}"
        r"\b(?:email|essay|blog|post|article|story|poem|letter|copy|caption|tagline)\b",
        r"\b(?:tone|voice|prose|narrative|headline|subject line|call to action)\b",
        r"\b(?:more (?:casual|formal|concise)|make it (?:shorter|punchier|friendlier))\b",
    ),
    "factual_lookup": (
        r"^\s*(?:what|who|when|where|which) (?:is|are|was|were|did|does)\b",
        r"\b(?:define|definition of|meaning of|stands for|abbreviation for)\b",
        r"\b(?:capital of|population of|born in|invented|history of)\b",
    ),
    "data_analysis": (
        r"\b(?:select |group by|join |where |having |cte\b|query)\b",
        r"\b(?:dataframe|pandas|numpy|csv|spreadsheet|pivot|histogram|regression)\b",
        r"\b(?:median|percentile|correlation|variance|std ?dev|p-?value|distribution)\b",
        r"\b(?:metric|kpi|dashboard|cohort|funnel|retention)\b",
    ),
    "chitchat": (
        r"^\s*(?:hi|hey|hello|yo|sup|thanks|thank you|thx|ok|okay|cool|nice|lol)\b",
        r"\b(?:how are you|good morning|good evening|what's up|nevermind|never mind)\b",
    ),
}

# Matched against the whole prompt, not searched inside it. A message that is nothing but a
# greeting is the one case where a heuristic can be near certain.
_PLEASANTRY = re.compile(
    r"^\s*(?:hi|hey|hello|yo|sup|thanks(?: a lot| so much| again)?|thank you|thx|ty|"
    r"ok|okay|k|cool|nice|great|perfect|got it|sounds good|good morning|"
    r"good afternoon|good evening|how are you|how's it going|what's up)"
    # a greeting plus one vocative is still only a greeting
    r"(?:\s+(?:there|again|all|everyone|team|folks|friend|buddy|mate|man|"
    r"claude|assistant|bot))?"
    r"[\s!.?,]*$", re.I)

_LOOKUP = re.compile(
    r"^\s*(?:what|who|when|where|which)\s+(?:is|are|was|were)\b"
    r"|^\s*(?:define|definition of|meaning of)\b"
    r"|^\s*how (?:do you|to) (?:spell|pronounce|say)\b", re.I)

# Each of these is one step the answer has to take. Three of them is a project, not a turn.
_MULTISTEP = re.compile(
    r"\b(?:and then|after that|first,|second,|third,|finally,|next,|also |additionally|"
    r"step \d|\d\.\s|\bthen\b.{0,30}\bthen\b)", re.I)

_SPECIALIST = re.compile(
    r"\b(?:architect|architecture|design a |distributed|concurrency|race condition|"
    r"optimi[sz]e|performance|migration|scalab|thread ?safe|memory leak|deadlock|"
    r"cryptograph|security audit|refactor|end ?to ?end|from scratch|trade-?offs?)\b", re.I)

_CODEY = re.compile(r"```|\btraceback\b|^\s{4,}\S|[\w/.-]+\.(?:py|js|ts|go|rs|java|rb)\b",
                    re.I | re.M)

# What makes a turn need something outside the model: a file, a repo, this machine, the
# present day, or a search.
_NEEDS_TOOLS = re.compile(
    r"\bthis (?:repo|repository|project|codebase|file|directory|folder|branch|machine)\b"
    r"|\b(?:my|our) \w+"
    r"|\b(?:search|look ?up|google|fetch|download|browse) \b"
    r"|\b(?:latest|current|today|right now|this week|recent)\b"
    r"|https?://|\b[\w/.-]+\.(?:py|js|ts|tsx|go|rs|java|rb|json|yaml|yml|toml|csv|log)\b"
    r"|\b(?:run|execute|install|deploy|commit|push) (?:the|this|it|a )\b", re.I)

_SENSITIVE = re.compile(
    r"\b(?:invest|stocks?|portfolio|salary|tax|refund|invoice|payment|bank|mortgage|loan|"
    r"insurance|savings|funds?|financial|money|budget|debt|pension|retirement|crypto|"
    r"contract|lawsuit|legal|liability|gdpr|hipaa|compliance|attorney|"
    r"diagnos|symptom|dosage|prescription|medical|medication|therapy|doctor|physician|"
    r"hospital|clinic|illness|disease|injur|"
    r"safety|hazard|emergency|self-?harm|credentials?|password|api key|secret)\b", re.I)


def _compiled(patterns: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.I | re.M) for p in patterns)


_DOMAIN_RE = {k: _compiled(v) for k, v in _DOMAIN_SIGNALS.items()}


def _text_of(state) -> str:
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        parts = [v for v in state.values() if isinstance(v, str)]
        if parts:
            return "\n".join(parts)
    return json.dumps(state, default=str)


def classify_domain(text: str) -> tuple[str, float, dict[str, float]]:
    """The likeliest domain, how sure we are, and the whole score distribution.

    One point per distinct pattern that matches, so a prompt that mentions a traceback and a
    .py file and the word refactor scores three for code rather than one. Confidence is
    ``top / (top + runner_up + 1)``: it rises with evidence and falls when a second domain
    is making the same claim.
    """
    if _PLEASANTRY.match(text):
        return "chitchat", 0.90, {"chitchat": 0.90}
    scores = {name: sum(1 for p in pats if p.search(text))
              for name, pats in _DOMAIN_RE.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, second = ranked[0], ranked[1]
    if top[1] == 0:
        return "", 0.0, {}
    conf = min(top[1] / (top[1] + second[1] + 1), MAX_CONFIDENCE)
    total = sum(scores.values()) or 1
    return top[0], conf, {k: round(v / total, 3) for k, v in scores.items() if v}


def rate_difficulty(text: str) -> tuple[float, float]:
    """A 0-3 difficulty and a confidence, on laya's own rubric.

    Only the first two branches can produce a score below 2 with enough confidence to reach
    the tier 3 gate, which is the whole point: those are the only two shapes of prompt where
    being wrong about "this is easy" is cheap.
    """
    stripped = text.strip()
    words = len(stripped.split())
    if _PLEASANTRY.match(stripped):
        return 0.0, 0.92
    multistep = len(_MULTISTEP.findall(text))
    specialist = len(_SPECIALIST.findall(text))
    codey = bool(_CODEY.search(text))
    if (_LOOKUP.match(stripped) and words <= 14 and not codey
            and not multistep and not specialist and stripped.count("?") <= 1
            and not _NEEDS_TOOLS.search(stripped)):
        # "what is wrong with my dockerfile" opens like a dictionary question and is not
        # one. Anything reaching for a file, a repo or today's news is disqualified.
        return 1.0, 0.85
    if words >= 120 or multistep >= 3 or specialist >= 2:
        return 3.0, 0.85
    if words >= 40 or multistep >= 1 or specialist >= 1 or codey:
        return 2.0, 0.70
    # Everything else is a short request that is not obviously a lookup. Moderate is the
    # safe guess and the low confidence keeps it out of every decision.
    return 2.0, 0.45


def _noul(hit: bool, strong: bool) -> Answer:
    """A yes/no answer. Evidence of presence is stronger than absence of evidence, so a
    negative never gets the confidence a positive does."""
    if hit:
        return Answer("noul", 1.0, 0.85 if strong else 0.65)
    return Answer("noul", 0.0, 0.55)


class RulesJudge:
    name = "rules"

    def available(self) -> bool:
        return True

    def ask(self, state, questions: dict) -> dict[str, Answer]:
        text = _text_of(state)
        out: dict[str, Answer] = {}
        if "output_type" in questions:
            label, conf = summarize.detect_type_regex_only(text, None, None)
            if conf >= 0.6:
                out["output_type"] = Answer("choice", label, conf, {label: conf})
        if "domain" in questions:
            label, conf, dist = classify_domain(text)
            if label:
                out["domain"] = Answer("choice", label, conf, dist)
        if "difficulty" in questions:
            score, conf = rate_difficulty(text)
            out["difficulty"] = Answer("score", score, conf)
        if "needs_tools" in questions:
            hits = len(_NEEDS_TOOLS.findall(text))
            out["needs_tools"] = _noul(hits > 0, hits >= 2)
        if "is_sensitive" in questions:
            hits = len(_SENSITIVE.findall(text))
            out["is_sensitive"] = _noul(hits > 0, hits >= 2)
        return out
