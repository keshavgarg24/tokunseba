"""Routing advice, and the measured limits it encodes."""
from tokunseba.advise import (DIFFICULTY_GATE, DIFFICULTY_LEVELS, EASY_SCORE, Advice, Turn,
                              counterfactual_cost, first_user_text, strip_wrappers)


def _turn(**kw):
    base = dict(request_id="r", session_id="s", model="claude-opus-5", provider="anthropic",
                prompt="p", input_tokens=1000, cache_read=0, cache_write=0,
                output_tokens=100, cost_usd=0.01)
    base.update(kw)
    return Turn(**base)


def test_strip_removes_system_reminders():
    t = strip_wrappers("<system-reminder>\nlots of rules\n</system-reminder>\nfix the typo")
    assert t == "fix the typo"


def test_strip_removes_session_and_command_wrappers():
    assert strip_wrappers("<session>\nhello\n</session>").strip() == "hello"
    assert "do it" in strip_wrappers("<command-name>/x</command-name>\ndo it")


def test_strip_removes_injected_skill_text():
    raw = "<EXTREMELY_IMPORTANT>\n" + "skill text\n" * 200 + "</EXTREMELY_IMPORTANT>\nreal ask"
    assert strip_wrappers(raw) == "real ask"


def test_strip_leaves_a_plain_prompt_alone():
    assert strip_wrappers("just fix the bug") == "just fix the bug"


def test_first_user_text_string_and_blocks():
    assert first_user_text({"messages": [{"role": "user", "content": "hi there"}]}) == "hi there"
    body = {"messages": [{"role": "assistant", "content": "x"},
                         {"role": "user", "content": [{"type": "text", "text": "the ask"}]}]}
    assert first_user_text(body) == "the ask"


def test_first_user_text_skips_an_empty_wrapper_only_turn():
    body = {"messages": [{"role": "user", "content": "<system-reminder>only rules</system-reminder>"},
                         {"role": "user", "content": "the real one"}]}
    assert first_user_text(body) == "the real one"


def test_first_user_text_handles_nothing():
    assert first_user_text({"messages": []}) == ""
    assert first_user_text({}) == ""


def test_difficulty_gate_is_deliberately_low():
    """Measured: laya's difficulty confidence never exceeded 0.39, so the normal 0.80 gate
    would mean the signal is never usable at all."""
    assert DIFFICULTY_GATE < 0.80
    assert DIFFICULTY_LEVELS[:2] == ["trivial", "easy"]


def test_easy_turns_use_score_not_confidence():
    adv = Advice(turns=[_turn(difficulty=1.0, difficulty_confidence=0.08),
                        _turn(difficulty=2.4, difficulty_confidence=0.9)])
    assert len(adv.easy_turns) == 1
    assert adv.easy_turns[0].difficulty <= EASY_SCORE


def test_confident_domains_require_a_high_gate():
    adv = Advice(turns=[_turn(domain="code", domain_confidence=0.96),
                        _turn(domain="chitchat", domain_confidence=0.30)])
    assert list(adv.confident_domains) == ["code"]


def test_counterfactual_cost_uses_the_target_price():
    turns = [_turn(input_tokens=1_000_000, output_tokens=0, cost_usd=5.0)]
    assert counterfactual_cost(turns, "claude-sonnet-5", {}) == 2.0
    assert counterfactual_cost(turns, "claude-haiku-4-5", {}) == 1.0


def test_counterfactual_returns_none_for_an_unknown_model():
    assert counterfactual_cost([_turn()], "no-such-model", {}) is None


def test_total_cost_sums():
    assert Advice(turns=[_turn(cost_usd=0.1), _turn(cost_usd=0.2)]).total_cost == 0.30000000000000004


def test_collect_turns_skips_missing_bodies(home, tmp_path):
    from tokunseba.ledger import Ledger
    from tokunseba.advise import collect_turns
    led = Ledger(home / "l.sqlite")
    assert collect_turns(led, tmp_path, 0) == []
