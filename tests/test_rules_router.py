"""The rules backend answering the router questions.

The point of these is calibration, not accuracy. A wrong label costs nothing as long as the
confidence attached to it stays under the gate, so most of what is asserted here is where
the confidence lands rather than which label won.
"""
import sys

import pytest

from tokunseba.judge import router_questions
from tokunseba.judge.rules import RulesJudge

GATE = 0.80  # the default judge.gate_threshold; nothing acts below this
Q = router_questions()


def ask(text: str) -> dict:
    return RulesJudge().ask({"request": text}, Q)


def test_every_router_question_is_answered():
    out = ask("refactor the retry loop in src/client.py")
    assert set(out) == set(Q)


@pytest.mark.parametrize("text", ["hey!", "hey there", "thanks again", "good morning all",
                                  "ok", "sounds good."])
def test_a_greeting_is_trivial_and_chitchat(text):
    out = ask(text)
    assert out["difficulty"].value == 0.0
    assert out["difficulty"].confidence >= 0.9
    assert out["domain"].value == "chitchat"


@pytest.mark.parametrize("text", [
    "what is the capital of Norway?",
    "who is the CEO of Anthropic",
    "define idempotent",
])
def test_a_short_lookup_is_easy_and_confident(text):
    """The one non-greeting shape allowed to clear the gate as easy."""
    out = ask(text)
    assert out["difficulty"].value == 1.0
    assert out["difficulty"].confidence >= GATE


@pytest.mark.parametrize("text", [
    "design a distributed rate limiter, then benchmark it, and finally write the migration",
    "optimize this query for performance and explain the trade-offs of each index you add",
    "x " * 130,
])
def test_multi_step_and_specialist_work_is_hard(text):
    out = ask(text)
    assert out["difficulty"].value == 3.0
    assert out["difficulty"].confidence >= GATE


@pytest.mark.parametrize("text", [
    "make it better",
    "the tests are red",
    "can you take a look",
    "thoughts?",
    "continue",
])
def test_ambiguous_prompts_stay_under_the_gate(text):
    """A prompt with nothing to go on must not be labelled easy with any authority."""
    d = ask(text)["difficulty"]
    assert d.confidence < GATE


def test_no_ordinary_work_is_ever_confidently_easy():
    """The mistake that matters is calling a real task easy, because that is what can send it
    to a weaker model. Nothing in this corpus may do both at once."""
    corpus = [
        "fix the failing test in tests/test_ledger.py",
        "why does this raise a KeyError",
        "write a blog post about prompt caching",
        "summarise the last three commits",
        "add a retry with backoff to the http client",
        "what is wrong with my dockerfile",
        "explain what this regex does",
        "rename the variable and update the callers",
    ]
    for text in corpus:
        d = ask(text)["difficulty"]
        assert not (d.value < 2 and d.confidence >= GATE), text


@pytest.mark.parametrize("text,domain", [
    ("the traceback in src/proxy.py says the async def raised an exception", "code"),
    ("select user_id, count(*) from events group by 1 and chart the distribution", "data_analysis"),
    ("prove that the sum of two odd primes is even", "math_or_logic"),
    ("draft a short email to the team with a friendlier tone", "writing"),
])
def test_domain_signals(text, domain):
    a = ask(text)["domain"]
    assert a.value == domain
    assert a.confidence >= 0.6


def test_domain_abstains_when_nothing_matches():
    assert "domain" not in ask("please proceed with that")


def test_domain_confidence_falls_when_two_domains_compete():
    """A prompt that is half SQL and half application code should not be confident about
    either, because acting on the wrong one is what sends a turn to the wrong model."""
    mixed = ("write the sql query with a group by and a join, then wire it into the "
             "python class in src/report.py and add a unit test")
    assert ask(mixed)["domain"].confidence < GATE


def test_needs_tools_is_confident_about_private_context():
    assert ask("read my config.toml and tell me what is wrong")["needs_tools"].value == 1.0
    assert ask("search for the latest release notes")["needs_tools"].confidence >= GATE


def test_needs_tools_is_never_confident_about_a_negative():
    """Absence of a filename is not evidence that nothing is needed."""
    a = ask("explain the difference between a mutex and a semaphore")["needs_tools"]
    assert a.value == 0.0
    assert a.confidence < GATE


@pytest.mark.parametrize("text", [
    "should I put my savings into index funds",
    "is this rash something I should see a doctor about",
    "review this contract for liability exposure",
])
def test_sensitive_topics_are_flagged(text):
    assert ask(text)["is_sensitive"].value == 1.0


def test_answering_the_router_does_not_import_torch():
    """The whole reason these heuristics exist is that the alternative weighs 2.2 GB."""
    ask("refactor the retry loop in src/client.py")
    assert "torch" not in sys.modules
    assert "laya" not in sys.modules


def test_state_may_be_a_dict_or_a_string():
    a = RulesJudge().ask("hey!", Q)
    b = RulesJudge().ask({"request": "hey!"}, Q)
    assert a["domain"].value == b["domain"].value == "chitchat"
