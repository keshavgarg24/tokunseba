from tokunseba import config
from tokunseba.protocols.anthropic import AnthropicAdapter
from tokunseba.tier3 import effort, routing

A = AnthropicAdapter()


def norm(model="claude-opus-5", turns=1):
    msgs = [{"role": "user", "content": "hi"}]
    for i in range(turns - 1):
        msgs += [{"role": "assistant", "content": "ok"}, {"role": "user", "content": f"m{i}"}]
    body = {"model": model, "messages": msgs}
    return A.parse(body), body


def cfg_on(**kw):
    c = config.Config()
    c.tier3 = True
    for k, v in kw.items():
        setattr(c.tier3_opts, k, v)
    return c


EASY = {"difficulty": 0.0, "domain": "chitchat"}
HARD = {"difficulty": 3.0, "domain": "code"}


def test_effort_off_by_default():
    n, b = norm()
    assert effort.apply(n, b, EASY, config.Config()) is False
    assert "output_config" not in b


def test_effort_lowers_on_easy_turns():
    n, b = norm()
    assert effort.apply(n, b, EASY, cfg_on(effort_routing=True)) is True
    assert b["output_config"]["effort"] == "low"


def test_effort_left_alone_on_hard_turns():
    n, b = norm()
    assert effort.apply(n, b, HARD, cfg_on(effort_routing=True)) is False


def test_effort_abstains_without_a_signal():
    n, b = norm()
    assert effort.apply(n, b, {}, cfg_on(effort_routing=True)) is False


def test_effort_never_overrides_an_explicit_setting():
    n, b = norm()
    b["output_config"] = {"effort": "max"}
    assert effort.apply(n, b, EASY, cfg_on(effort_routing=True)) is False
    assert b["output_config"]["effort"] == "max"


def test_effort_skips_non_anthropic():
    n, b = norm(model="gpt-4o")
    assert effort.apply(n, b, EASY, cfg_on(effort_routing=True)) is False


def test_routing_only_at_session_start():
    n, b = norm(turns=3)
    c = cfg_on(model_routing=True, model_map={"claude-opus-5": "claude-sonnet-5"})
    up, reason = routing.apply(n, b, EASY, c)
    assert up is None and reason == "not-session-start"
    assert b["model"] == "claude-opus-5"


def test_model_routing_swaps_on_easy_first_turn():
    n, b = norm()
    c = cfg_on(model_routing=True, model_map={"claude-opus-5": "claude-sonnet-5"})
    up, reason = routing.apply(n, b, EASY, c)
    assert up is None and reason == "model_routed" and b["model"] == "claude-sonnet-5"


def test_model_routing_leaves_hard_turns_alone():
    n, b = norm()
    c = cfg_on(model_routing=True, model_map={"claude-opus-5": "claude-sonnet-5"})
    assert routing.apply(n, b, HARD, c)[1] == "not-easy"
    assert b["model"] == "claude-opus-5"


def test_local_routing_only_for_safe_domains():
    n, b = norm(model="gpt-4o")
    n.provider = "openai"
    c = cfg_on(local_routing=True, local_model="llama3.1")
    up, reason = routing.apply(n, b, {"difficulty": 0.0, "domain": "chitchat"}, c)
    assert up == "ollama" and reason == "local_routed" and b["model"] == "llama3.1"

    n2, b2 = norm(model="gpt-4o")
    n2.provider = "openai"
    assert routing.apply(n2, b2, {"difficulty": 0.0, "domain": "code"}, c)[0] is None
    assert b2["model"] == "gpt-4o"


def test_tier3_off_means_no_routing():
    n, b = norm()
    c = config.Config()
    c.tier3_opts.model_routing = True
    c.tier3_opts.model_map = {"claude-opus-5": "claude-sonnet-5"}
    assert routing.apply(n, b, EASY, c) == (None, "")
    assert b["model"] == "claude-opus-5"


async def test_control_arm_is_never_modified(client, proxy_app):
    """Every tier 3 change must be measurable against an untouched control."""
    app, cfg, led, up = proxy_app
    cfg.tier3 = True
    cfg.tier3_opts.effort_routing = True
    import tokunseba.server as srv
    srv.random.choice = lambda _opts: "control"
    await client.post("/anthropic/v1/messages",
                      json={"model": "claude-opus-5", "max_tokens": 10, "system": "s" * 6000,
                            "messages": [{"role": "user", "content": "hi"}]},
                      headers={"x-api-key": "k"})
    assert "output_config" not in up.last["body"]
    assert led.recent_sessions()[0]["arm"] == "control"
