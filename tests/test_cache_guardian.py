from tokunseba.cache import guardian
from tokunseba.protocols.anthropic import AnthropicAdapter

A = AnthropicAdapter()


def make(system, cc=True, tools=None, messages=None):
    body = {"model": "claude-opus-5",
            "system": [{"type": "text", "text": system, **({"cache_control": {"type": "ephemeral"}} if cc else {})}],
            "tools": tools if tools is not None else [],
            "messages": messages or [{"role": "user", "content": "hi"}]}
    return A.parse(body)


def test_guardian_detects_timestamp_drift():
    a = make("Today's date is 2026-09-22")
    b = make("Today's date is 2026-09-23")
    ev = guardian.check(guardian.breakpoints(a), guardian.breakpoints(b),
                        guardian.regions(a), b, {"system": a.system_text})
    assert ev and ev[0].region == "system" and ev[0].cause == "timestamp"


def test_no_drift_when_prefix_stable():
    a = make("stable")
    b = make("stable", messages=[{"role": "user", "content": "hi"},
                                 {"role": "assistant", "content": "yo"},
                                 {"role": "user", "content": "more"}])
    assert guardian.check(guardian.breakpoints(a), guardian.breakpoints(b),
                          guardian.regions(a), b, {"system": a.system_text}) == []


def test_volatile_id_cause():
    a = make("session 3f2504e0-4f89-11d3-9a0c-0305e82c3301 ready")
    b = make("session 9a2504e0-4f89-11d3-9a0c-0305e82c3399 ready")
    ev = guardian.check(guardian.breakpoints(a), guardian.breakpoints(b),
                        guardian.regions(a), b, {"system": a.system_text})
    assert ev[0].cause == "volatile_id"


def test_content_change_cause():
    a, b = make("you are helpful"), make("you are terse")
    ev = guardian.check(guardian.breakpoints(a), guardian.breakpoints(b),
                        guardian.regions(a), b, {"system": a.system_text})
    assert ev[0].cause == "content_changed"


def test_tool_set_change_detected():
    a = make("s", tools=[{"name": "a", "cache_control": {"type": "ephemeral"}}])
    b = make("s", tools=[{"name": "b", "cache_control": {"type": "ephemeral"}}])
    ev = guardian.check(guardian.breakpoints(a), guardian.breakpoints(b),
                        guardian.regions(a), b, {"tools": a.tools_json})
    assert ev and ev[0].region == "tools"


def test_breakpoints_found_in_render_order():
    n = make("s", tools=[{"name": "t", "cache_control": {"type": "ephemeral"}}])
    labels = [l for l, _ in guardian.breakpoints(n)]
    assert labels[0] == "tools" and labels[1] == "system[0]"


def test_no_breakpoints_when_no_markers():
    assert guardian.breakpoints(make("s", cc=False)) == []


def test_post_check():
    assert guardian.post_check(0, True, 0) is None
    assert guardian.post_check(3, True, 0) == "cache_miss_unexplained"
    assert guardian.post_check(3, True, 900) is None
    assert guardian.post_check(3, False, 0) is None
