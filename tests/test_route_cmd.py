"""Prompt-driven routing: the rules, and the command group that manages them."""
import pytest
from click.testing import CliRunner

from tokunseba import config
from tokunseba.cli import main
from tokunseba.tier3 import routing


def run(args, **kw):
    return CliRunner().invoke(main, args, **kw)


def flat(result) -> str:
    """Rich wraps to the terminal width, so assertions join on whitespace."""
    return " ".join(result.output.split())


class Norm:
    """The few fields routing.apply actually reads."""
    def __init__(self, provider="anthropic", model="claude-opus-5", turns=1):
        self.provider = provider
        self.model = model
        self.messages = [object()] * turns


def cfg_with(home, rules, tier3=True):
    cfg = config.load()
    cfg.tier3 = tier3
    cfg.tier3_opts.rules = rules
    config.save(cfg)
    return cfg


# --- matching -------------------------------------------------------------------------

def test_a_rule_with_no_conditions_never_matches():
    """Otherwise a typo would silently reroute every conversation."""
    assert routing.match({"model": "x"}, {"domain": "code", "difficulty": 0.0}) is False


def test_conditions_are_all_required():
    rule = {"domain": "chitchat", "max_difficulty": 1.0}
    assert routing.match(rule, {"domain": "chitchat", "difficulty": 1.0})
    assert not routing.match(rule, {"domain": "code", "difficulty": 1.0})
    assert not routing.match(rule, {"domain": "chitchat", "difficulty": 2.0})


def test_a_missing_signal_never_matches():
    """Signals are absent when the judge was not confident, and an unsure judge must not
    be read as agreement."""
    assert not routing.match({"max_difficulty": 1.0}, {})
    assert not routing.match({"domain": "code"}, {})
    assert not routing.match({"needs_tools": False}, {})


def test_needs_tools_matches_either_way():
    assert routing.match({"needs_tools": True}, {"needs_tools": 1.0})
    assert routing.match({"needs_tools": False}, {"needs_tools": 0.0})
    assert not routing.match({"needs_tools": True}, {"needs_tools": 0.0})


def test_first_match_wins():
    rules = [{"domain": "code", "model": "a"}, {"max_difficulty": 3.0, "model": "b"}]
    assert routing.first_match(rules, {"domain": "code", "difficulty": 0.0})["model"] == "a"
    assert routing.first_match(rules, {"domain": "writing", "difficulty": 0.0})["model"] == "b"


# --- applying -------------------------------------------------------------------------

def test_a_model_swap_keeps_the_upstream(home):
    cfg = cfg_with(home, [{"max_difficulty": 1.0, "model": "claude-haiku-4-5-20251001"}])
    body = {"model": "claude-opus-5"}
    up, reason = routing.apply(Norm(), body, {"difficulty": 0.0}, cfg)
    assert up is None and reason == "rule_routed"
    assert body["model"] == "claude-haiku-4-5-20251001"


def test_routing_never_fires_after_the_first_turn(home):
    cfg = cfg_with(home, [{"max_difficulty": 1.0, "model": "cheap"}])
    body = {"model": "claude-opus-5"}
    up, reason = routing.apply(Norm(turns=4), body, {"difficulty": 0.0}, cfg)
    assert up is None and reason == "not-session-start"
    assert body["model"] == "claude-opus-5"


def test_routing_does_nothing_while_tier3_is_off(home):
    cfg = cfg_with(home, [{"max_difficulty": 3.0, "model": "cheap"}], tier3=False)
    body = {"model": "claude-opus-5"}
    assert routing.apply(Norm(), body, {"difficulty": 0.0}, cfg) == (None, "")
    assert body["model"] == "claude-opus-5"


def test_a_cross_protocol_target_is_refused_not_attempted(home):
    """The proxy rewrites bodies, it does not translate between providers."""
    cfg = cfg_with(home, [{"domain": "chitchat", "upstream": "ollama", "model": "llama3.1"}])
    body = {"model": "claude-opus-5"}
    up, reason = routing.apply(Norm(provider="anthropic"), body, {"domain": "chitchat"}, cfg)
    assert up is None
    assert reason.startswith("rule-incompatible")
    assert body["model"] == "claude-opus-5"


def test_an_openai_client_may_reach_ollama(home):
    cfg = cfg_with(home, [{"domain": "chitchat", "upstream": "ollama", "model": "llama3.1"}])
    body = {"model": "gpt-4o"}
    up, reason = routing.apply(Norm(provider="openai"), body, {"domain": "chitchat"}, cfg)
    assert (up, reason) == ("ollama", "rule_routed")
    assert body["model"] == "llama3.1"


def test_a_rule_naming_an_unknown_upstream_is_refused(home):
    cfg = cfg_with(home, [{"domain": "code", "upstream": "nope", "model": "x"}])
    body = {"model": "gpt-4o"}
    up, reason = routing.apply(Norm(provider="openai"), body, {"domain": "code"}, cfg)
    assert up is None and reason == "rule-upstream-missing:nope"


def test_legacy_model_map_still_works(home):
    """Configs written before rules existed must keep behaving."""
    cfg = config.load()
    cfg.tier3 = True
    cfg.tier3_opts.model_routing = True
    cfg.tier3_opts.model_map = {"claude-opus-5": "claude-haiku-4-5-20251001"}
    config.save(cfg)
    body = {"model": "claude-opus-5"}
    up, reason = routing.apply(Norm(), body, {"difficulty": 0.0}, cfg)
    assert (up, reason) == (None, "model_routed")


# --- the command group ----------------------------------------------------------------

def test_status_without_rules_explains_how_to_add_one(home):
    out = flat(run(["route"]))
    assert "no rules" in out
    assert "route add" in out


def test_add_requires_a_condition(home):
    r = run(["route", "add", "--model", "cheap"])
    assert r.exit_code == 2
    assert "at least one condition" in flat(r)
    assert config.load().tier3_opts.rules == []


def test_add_requires_a_target(home):
    r = run(["route", "add", "--domain", "code"])
    assert r.exit_code == 2
    assert "somewhere to send" in flat(r)


def test_add_rejects_an_unknown_upstream(home):
    r = run(["route", "add", "--domain", "code", "--to", "nope"])
    assert r.exit_code == 2
    assert "No upstream named nope" in flat(r)


def test_add_then_remove_round_trips(home):
    assert run(["route", "add", "--domain", "chitchat", "--to", "ollama",
                "--model", "llama3.1"]).exit_code == 0
    assert config.load().tier3_opts.rules == [
        {"domain": "chitchat", "upstream": "ollama", "model": "llama3.1"}]
    assert run(["route", "rm", "1"]).exit_code == 0
    assert config.load().tier3_opts.rules == []


def test_rm_rejects_an_index_that_does_not_exist(home):
    r = run(["route", "rm", "3"])
    assert r.exit_code == 2
    assert "no rule 3" in flat(r)


def test_add_warns_that_tier3_is_off(home):
    out = flat(run(["route", "add", "--domain", "code", "--model", "cheap"]))
    assert "Tier 3 is off" in out


def test_add_warns_about_a_cross_protocol_target(home):
    out = flat(run(["route", "add", "--domain", "chitchat", "--to", "ollama",
                    "--model", "llama3.1"]))
    assert "anthropic" in out and "translated" in out


def test_enable_asks_first_and_disable_keeps_the_rules(home):
    run(["route", "add", "--domain", "code", "--model", "cheap"])
    assert run(["route", "enable"], input="n\n").exit_code == 0
    assert config.load().tier3 is False
    assert run(["route", "enable", "-y"]).exit_code == 0
    assert config.load().tier3 is True
    assert run(["route", "disable"]).exit_code == 0
    cfg = config.load()
    assert cfg.tier3 is False and len(cfg.tier3_opts.rules) == 1


def test_clear_confirms(home):
    run(["route", "add", "--domain", "code", "--model", "cheap"])
    run(["route", "clear"], input="n\n")
    assert len(config.load().tier3_opts.rules) == 1
    run(["route", "clear", "-y"])
    assert config.load().tier3_opts.rules == []


def test_test_shows_the_signals_and_the_gate(home):
    out = flat(run(["route", "test", "hey there"]))
    assert "chitchat" in out
    assert "above the gate" in out
    assert "No rule matches" in out


def test_test_discards_answers_below_the_gate(home):
    out = flat(run(["route", "test", "make it better"]))
    assert "discarded" in out
    assert "No rule matches" in out


def test_test_reports_where_a_matching_turn_would_go(home):
    run(["route", "add", "--max-difficulty", "1", "--model", "claude-haiku-4-5-20251001"])
    out = flat(run(["route", "test", "what is a mutex"]))
    assert "claude-haiku-4-5-20251001" in out
    assert "Routing is off" in out


def test_test_warns_when_the_protocols_do_not_line_up(home):
    run(["route", "add", "--domain", "chitchat", "--to", "ollama", "--model", "llama3.1"])
    out = flat(run(["route", "test", "--provider", "anthropic", "hey there"]))
    assert "cannot be sent" in out
    out = flat(run(["route", "test", "--provider", "openai", "hey there"]))
    assert "would go to ollama" in out


def test_test_sends_nothing_and_loads_nothing(home, monkeypatch):
    """The command exists so people can see routing without turning it on."""
    import sys
    run(["route", "test", "refactor src/app.py"])
    assert "torch" not in sys.modules


@pytest.mark.parametrize("rule,expected", [
    ({"domain": "code", "model": "x"}, "domain=code -> same upstream / x"),
    ({"max_difficulty": 1.0, "upstream": "ollama"}, "difficulty<=1 -> ollama"),
    ({"needs_tools": False, "model": "x"}, "needs_tools=no -> same upstream / x"),
])
def test_describe_reads_as_a_sentence(rule, expected):
    assert routing.describe(rule) == expected


# --- end to end through the proxy ------------------------------------------------------

def _first_turn(text: str) -> dict:
    return {"model": "claude-opus-5", "max_tokens": 50,
            "messages": [{"role": "user", "content": text}]}


async def test_a_greeting_is_routed_to_the_cheaper_model(client, proxy_app, monkeypatch):
    """The whole feature, with nothing installed and no model loaded: the prompt alone
    decides, and the upstream receives the model the rule named."""
    _app, cfg, _led, up = proxy_app
    cfg.tier3 = True
    cfg.tier3_opts.rules = [{"max_difficulty": 1.0, "model": "claude-haiku-4-5-20251001"}]
    monkeypatch.setattr("random.choice", lambda seq: "treatment")
    await client.post("/anthropic/v1/messages", json=_first_turn("hey there"),
                      headers={"x-api-key": "k"})
    assert up.last["body"]["model"] == "claude-haiku-4-5-20251001"


async def test_real_work_keeps_the_model_it_asked_for(client, proxy_app, monkeypatch):
    _app, cfg, _led, up = proxy_app
    cfg.tier3 = True
    cfg.tier3_opts.rules = [{"max_difficulty": 1.0, "model": "claude-haiku-4-5-20251001"}]
    monkeypatch.setattr("random.choice", lambda seq: "treatment")
    await client.post("/anthropic/v1/messages",
                      json=_first_turn("refactor the retry loop in src/client.py and add "
                                       "a test for the backoff"),
                      headers={"x-api-key": "k"})
    assert up.last["body"]["model"] == "claude-opus-5"


async def test_the_control_arm_is_never_routed(client, proxy_app, monkeypatch):
    """Tier 3 measures itself against an untouched arm, so routing must skip it."""
    _app, cfg, _led, up = proxy_app
    cfg.tier3 = True
    cfg.tier3_opts.rules = [{"max_difficulty": 1.0, "model": "claude-haiku-4-5-20251001"}]
    monkeypatch.setattr("random.choice", lambda seq: "control")
    await client.post("/anthropic/v1/messages", json=_first_turn("hey there"),
                      headers={"x-api-key": "k"})
    assert up.last["body"]["model"] == "claude-opus-5"


async def test_a_routed_turn_is_recorded(client, proxy_app, monkeypatch):
    _app, cfg, led, _up = proxy_app
    cfg.tier3 = True
    cfg.tier3_opts.rules = [{"max_difficulty": 1.0, "model": "claude-haiku-4-5-20251001"}]
    monkeypatch.setattr("random.choice", lambda seq: "treatment")
    await client.post("/anthropic/v1/messages", json=_first_turn("hey there"),
                      headers={"x-api-key": "k"})
    kinds = [e["kind"] for e in led.events()]
    assert "rule_routed" in kinds
