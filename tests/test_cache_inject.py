from tokunseba.cache.inject import inject, ttl_advice
from tokunseba.protocols.anthropic import AnthropicAdapter


class FakeEstimator:
    def count(self, text, provider, model):
        return len(text) // 4


def _body():
    return {"model": "claude-opus-5", "system": "x" * 5000,
            "tools": [{"name": "t", "input_schema": {}}],
            "messages": [{"role": "user", "content": "hi"}]}


def test_inject_adds_three_markers_and_is_idempotent():
    body = _body()
    norm = AnthropicAdapter().parse(body)
    assert inject(norm, body, 0, FakeEstimator(), 1024, None) == 3
    norm2 = AnthropicAdapter().parse(body)
    assert norm2.has_cache_control and inject(norm2, body, 0, FakeEstimator(), 1024, None) == 0


def test_inject_shapes_are_valid():
    body = _body()
    inject(AnthropicAdapter().parse(body), body, 0, FakeEstimator(), 1024, None)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][-1]["cache_control"]["type"] == "ephemeral"
    assert body["messages"][-1]["content"][0]["text"] == "hi"


def test_ttl_is_applied_when_given():
    body = _body()
    inject(AnthropicAdapter().parse(body), body, 0, FakeEstimator(), 1024, "1h")
    assert body["system"][0]["cache_control"]["ttl"] == "1h"


def test_small_prompts_are_left_alone():
    body = {"model": "claude-opus-5", "system": "tiny", "messages": [{"role": "user", "content": "hi"}]}
    assert inject(AnthropicAdapter().parse(body), body, 0, FakeEstimator(), 1024, None) == 0


def test_non_anthropic_and_non_claude_are_skipped():
    body = _body()
    norm = AnthropicAdapter().parse(body)
    norm.provider = "openai"
    assert inject(norm, body, 0, FakeEstimator(), 1024, None) == 0
    body2 = _body()
    body2["model"] = "gpt-4o"
    assert inject(AnthropicAdapter().parse(body2), body2, 0, FakeEstimator(), 1024, None) == 0


def test_marks_last_tool_result_block():
    body = _body()
    body["messages"] = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "a", "content": "out"}]}]
    inject(AnthropicAdapter().parse(body), body, 0, FakeEstimator(), 1024, None)
    assert "cache_control" in body["messages"][-1]["content"][-1]


def test_ttl_advice():
    assert ttl_advice([600] * 6) == "1h"
    assert ttl_advice([10] * 6) is None
    assert ttl_advice([600, 600]) is None
